"""The agent: a bounded state machine over search, a relevance grade, and generation.

    retrieve -> grade_relevance -> generate                      (relevant)
                                -> rewrite_query -> retrieve     (not relevant, hops left)
                                -> insufficient_context          (not relevant, no hops left)

Every path ends after at most ``max_hops`` searches. Relevance is graded from the search's own
similarity score, so the only model requests are the rewrite and the answer, one per step.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from api.generate import GenerationError, GeneratorProtocol
from api.graph.prompts import answer_messages, answer_schema, rewrite_messages
from api.graph.state import AgentState
from api.mcp_client import SearchClientProtocol, SearchHit

ANSWERED = "answered"
INSUFFICIENT_CONTEXT = "insufficient_context"


@dataclass(frozen=True)
class AgentConfig:
    """How far the agent may go: hops, the relevance threshold, and results per search."""

    # Searches per run, counting the first. Two allows one rewrite.
    max_hops: int = 2
    # The top hit's cosine similarity (1 minus distance) needed to call the context relevant.
    relevance_threshold: float = 0.65
    # Chunks per search, which are also the chunks the answer step sees.
    search_limit: int = 5

    def __post_init__(self) -> None:
        """Reject settings no run could satisfy."""
        if self.max_hops < 1:
            raise ValueError(f"max_hops must be at least 1, not {self.max_hops}.")
        if self.relevance_threshold < 0.0 or self.relevance_threshold > 1.0:
            raise ValueError(f"relevance_threshold must be 0 to 1, not {self.relevance_threshold}.")
        if self.search_limit < 1:
            raise ValueError(f"search_limit must be at least 1, not {self.search_limit}.")


@dataclass(frozen=True)
class AgentAnswer:
    """The outcome of one run.

    ``status`` is ``"answered"`` or ``"insufficient_context"``. ``citations`` are the context
    chunks the answer cites; ``cited_chunk_ids`` is what the model returned, kept whole so a cited
    id that names no context chunk stays visible.
    """

    status: str
    answer: str
    cited_chunk_ids: list[str]
    citations: list[SearchHit]
    context: list[SearchHit]
    queries: list[str]
    hops: int


class AgentNodes:
    """The graph's steps, bound to the search client, the generator, and the settings."""

    def __init__(
        self, search: SearchClientProtocol, generator: GeneratorProtocol, config: AgentConfig
    ) -> None:
        """Run steps against ``search`` and ``generator`` within ``config``."""
        self.search = search
        self.generator = generator
        self.config = config

    async def retrieve(self, state: AgentState) -> AgentState:
        """Search for the current query: one hop."""
        query = state["query"]
        hits = await self.search.search(query, self.config.search_limit)
        queries = list(state.get("queries", []))
        queries.append(query)
        return {"hits": hits, "hops": state.get("hops", 0) + 1, "queries": queries}

    async def grade_relevance(self, state: AgentState) -> AgentState:
        """Call the hits relevant when the nearest one is similar enough to the query.

        No model request: the grade is the top hit's cosine similarity, 1 minus its distance,
        against ``relevance_threshold``. No hits at all is not relevant.
        """
        hits = state["hits"]
        best_similarity = 0.0
        if hits:
            # Hits arrive nearest first, so the first has the highest similarity.
            best_similarity = 1.0 - hits[0].distance
        relevant = best_similarity >= self.config.relevance_threshold
        return {"relevant": relevant, "context": hits}

    def route(self, state: AgentState) -> str:
        """The step after grading: generate, rewrite and search again, or stop."""
        if state["relevant"]:
            return "generate"
        if state["hops"] < self.config.max_hops:
            return "rewrite_query"
        return "insufficient_context"

    async def rewrite_query(self, state: AgentState) -> AgentState:
        """Ask the model for a better query: one free-text request."""
        messages = rewrite_messages(state["question"], state["query"])
        # The generator is synchronous; running it in a thread keeps the event loop, and with it
        # the MCP connection, responsive while the request is out.
        reply = await asyncio.to_thread(self.generator.generate, messages)
        query = reply.strip()
        if not query:
            query = state["question"]
        return {"query": query}

    async def generate(self, state: AgentState) -> AgentState:
        """Ask for a cited answer from the graded context: one strict-schema request."""
        context = state["hits"]
        reply = await asyncio.to_thread(
            self.generator.generate,
            answer_messages(state["question"], context),
            response_schema=answer_schema(context),
        )
        answerable, answer, cited = parse_answer(reply)
        if not answerable:
            return {"status": INSUFFICIENT_CONTEXT, "answer": "", "cited_chunk_ids": []}
        return {"status": ANSWERED, "answer": answer, "cited_chunk_ids": cited}

    async def insufficient_context(self, state: AgentState) -> AgentState:
        """Stop without an answer: the hop limit was reached with nothing relevant."""
        return {"status": INSUFFICIENT_CONTEXT, "answer": "", "cited_chunk_ids": []}


def parse_answer(reply: str) -> tuple[bool, str, list[str]]:
    """Read ``(answerable, answer, cited_chunk_ids)`` from the answer step's JSON reply.

    Raises ``GenerationError`` if the reply is not a JSON object with those three fields.
    """
    try:
        parsed: Any = json.loads(reply)
    except ValueError as error:
        raise GenerationError("The answer was not JSON.") from error
    if not isinstance(parsed, dict):
        raise GenerationError("The answer was not a JSON object.")
    answerable = parsed.get("answerable")
    answer = parsed.get("answer")
    cited = parsed.get("cited_chunk_ids")
    if not isinstance(answerable, bool) or not isinstance(answer, str):
        raise GenerationError("The answer is missing answerable or answer.")
    if not isinstance(cited, list):
        raise GenerationError("The answer is missing cited_chunk_ids.")
    cited_ids: list[str] = []
    for chunk_id in cited:
        if not isinstance(chunk_id, str):
            raise GenerationError("A cited chunk id is not a string.")
        cited_ids.append(chunk_id)
    return answerable, answer, cited_ids


def build_graph(
    search: SearchClientProtocol,
    generator: GeneratorProtocol,
    *,
    config: AgentConfig | None = None,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> CompiledStateGraph[AgentState]:
    """Compile the agent over ``search`` and ``generator``.

    With a ``checkpointer``, each run's state is saved under the thread id passed to ``ask``.
    """
    if config is None:
        config = AgentConfig()
    nodes = AgentNodes(search, generator, config)
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("grade_relevance", nodes.grade_relevance)
    graph.add_node("rewrite_query", nodes.rewrite_query)
    graph.add_node("generate", nodes.generate)
    graph.add_node("insufficient_context", nodes.insufficient_context)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "grade_relevance")
    # route returns the name of the next step; every name it can return is listed here.
    graph.add_conditional_edges(
        "grade_relevance",
        nodes.route,
        ["generate", "rewrite_query", "insufficient_context"],
    )
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("generate", END)
    graph.add_edge("insufficient_context", END)
    return graph.compile(checkpointer=checkpointer)


async def ask(
    graph: CompiledStateGraph[AgentState], question: str, *, thread_id: str | None = None
) -> AgentAnswer:
    """Run ``graph`` on ``question`` and return its answer.

    ``thread_id`` names the run's saved state when the graph has a checkpointer.
    """
    start: AgentState = {"question": question, "query": question, "queries": [], "hops": 0}
    run_config: RunnableConfig | None = None
    if thread_id is not None:
        run_config = {"configurable": {"thread_id": thread_id}}
    final = await graph.ainvoke(start, config=run_config)
    context: list[SearchHit] = final.get("context", [])
    cited: list[str] = final.get("cited_chunk_ids", [])
    by_id: dict[str, SearchHit] = {}
    for hit in context:
        by_id[hit.id] = hit
    citations: list[SearchHit] = []
    for chunk_id in cited:
        if chunk_id in by_id:
            citations.append(by_id[chunk_id])
    return AgentAnswer(
        status=final["status"],
        answer=final.get("answer", ""),
        cited_chunk_ids=cited,
        citations=citations,
        context=context,
        queries=final["queries"],
        hops=final["hops"],
    )
