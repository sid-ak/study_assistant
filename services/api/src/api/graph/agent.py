"""The agent: a bounded state machine over search, a relevance grade, and generation.

    retrieve -> grade_relevance -> review_sources -> generate    (relevant, approved)
                                -> rewrite_query -> retrieve     (not relevant, hops left)
                                -> insufficient_context          (nothing left to try)

    review_sources -> rewrite_query -> retrieve                  (rejected, hops left)
                   -> insufficient_context                       (rejected, no hops left)

Every path ends after at most ``max_hops`` searches. Relevance is graded from the search's own
similarity score, so the only model requests are the rewrite and the answer, one per step.

``review_sources`` is the human-in-the-loop checkpoint. Without ``require_approval`` it passes
straight through; with it, the run stops there and waits for a decision under its thread id.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, Interrupt, interrupt

from api.generate import GenerationError, GeneratorProtocol
from api.graph.prompts import answer_messages, answer_schema, rewrite_messages
from api.graph.review import (
    PendingReview,
    decision_is_approval,
    review_from_payload,
    review_payload,
)
from api.graph.state import AgentState
from api.mcp_client import MAX_SEARCH_LIMIT, SearchClientProtocol, SearchHit

# The compiled agent graph, as build_graph returns it and ask runs it.
CompiledAgent = CompiledStateGraph[AgentState]

ANSWERED = "answered"
INSUFFICIENT_CONTEXT = "insufficient_context"


@dataclass(frozen=True)
class AgentConfig:
    """How far the agent may go: hops, the relevance threshold, and results per search."""

    # Searches per run, counting the first. Two allows one rewrite.
    max_hops: int = 2
    # The top hit's relevance needed to call the context relevant: the reranker's score, from 0 to
    # 1, when the search reranks, otherwise the cosine similarity.
    relevance_threshold: float = 0.65
    # Chunks per search, which are also the chunks the answer step sees.
    search_limit: int = 5
    # Whether the run stops at the checkpoint to have its sources approved before generating.
    require_approval: bool = False

    def __post_init__(self) -> None:
        """Reject settings no run could satisfy."""
        if self.max_hops < 1:
            raise ValueError(f"max_hops must be at least 1, not {self.max_hops}.")
        if self.relevance_threshold < 0.0 or self.relevance_threshold > 1.0:
            raise ValueError(f"relevance_threshold must be 0 to 1, not {self.relevance_threshold}.")
        if self.search_limit < 1 or self.search_limit > MAX_SEARCH_LIMIT:
            raise ValueError(
                f"search_limit must be 1 to {MAX_SEARCH_LIMIT}, the search tool's maximum, "
                f"not {self.search_limit}."
            )


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


# What one leg of a run returns: the answer, or the checkpoint it stopped at.
AgentOutcome = AgentAnswer | PendingReview


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
        """Call the hits relevant when the best one's relevance clears the threshold.

        No model request: the grade is the top hit's relevance as the search reported it, the
        reranker's score when the server reranks and the cosine similarity otherwise, against
        ``relevance_threshold``. No hits at all is not relevant.
        """
        hits = state["hits"]
        best_relevance = 0.0
        if hits:
            # Hits arrive ordered by relevance, so the first is the best.
            best_relevance = hits[0].relevance
        # With no hits there is nothing to answer from, whatever the threshold.
        relevant = bool(hits) and best_relevance >= self.config.relevance_threshold
        return {"relevant": relevant, "context": hits}

    def route(self, state: AgentState) -> str:
        """The step after grading: offer the sources for approval, or try again, or stop."""
        if state["relevant"]:
            return "review_sources"
        return self.retry_or_stop(state)

    async def review_sources(self, state: AgentState) -> AgentState:
        """The checkpoint: pause for a decision on the graded sources, when one is required.

        ``interrupt`` stops the run here and saves it. What a later resume passes back in becomes
        its return value, and this step runs again from the top, so nothing before it is repeated.
        Without ``require_approval`` the step approves the sources itself and the run goes on.
        """
        if not self.config.require_approval:
            return {"approved": True}
        decision = interrupt(review_payload(state))
        return {"approved": decision_is_approval(decision)}

    def route_after_review(self, state: AgentState) -> str:
        """The step after the checkpoint: generate the answer, or try again, or stop."""
        if state["approved"]:
            return "generate"
        return self.retry_or_stop(state)

    def retry_or_stop(self, state: AgentState) -> str:
        """Rewrite and search again while a hop is left, otherwise stop without an answer."""
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
) -> CompiledAgent:
    """Compile the agent over ``search`` and ``generator``.

    With a ``checkpointer``, each run's state is saved under the thread id passed to ``ask``,
    ``start``, or ``resume``. ``require_approval`` needs one, since a pause that is saved nowhere
    could never be resumed; without it, this raises ``ValueError``.
    """
    if config is None:
        config = AgentConfig()
    if config.require_approval and checkpointer is None:
        raise ValueError(
            "require_approval needs a checkpointer: a run paused with nothing to save its state "
            "to could not be resumed."
        )
    nodes = AgentNodes(search, generator, config)
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("grade_relevance", nodes.grade_relevance)
    graph.add_node("rewrite_query", nodes.rewrite_query)
    graph.add_node("review_sources", nodes.review_sources)
    graph.add_node("generate", nodes.generate)
    graph.add_node("insufficient_context", nodes.insufficient_context)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "grade_relevance")
    # route returns the name of the next step; every name it can return is listed here.
    graph.add_conditional_edges(
        "grade_relevance",
        nodes.route,
        ["review_sources", "rewrite_query", "insufficient_context"],
    )
    graph.add_conditional_edges(
        "review_sources",
        nodes.route_after_review,
        ["generate", "rewrite_query", "insufficient_context"],
    )
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("generate", END)
    graph.add_edge("insufficient_context", END)
    return graph.compile(checkpointer=checkpointer)


# The key LangGraph adds to a run's result when the run stopped at an interrupt.
INTERRUPT_KEY = "__interrupt__"

# What one call to the graph returns: the run's state, plus INTERRUPT_KEY when it paused.
RunResult = dict[str, Any]


def paused_at(final: RunResult) -> Interrupt | None:
    """The interrupt a leg of a run stopped at, or none when the run finished."""
    interrupts = final.get(INTERRUPT_KEY)
    if not interrupts:
        return None
    # One interrupt per pause: the checkpoint is the graph's only one.
    first: Interrupt = interrupts[0]
    return first


def outcome_from(final: RunResult, thread_id: str) -> AgentOutcome:
    """The checkpoint a leg of a run stopped at, or the answer it finished with."""
    interrupt_stopped_at = paused_at(final)
    if interrupt_stopped_at is not None:
        return review_from_payload(interrupt_stopped_at.value, thread_id)
    return answer_from(final)


def start_state(question: str) -> AgentState:
    """The state a run begins with: the question, searched as it stands on the first hop."""
    return {"question": question, "query": question, "queries": [], "hops": 0}


def thread_config(thread_id: str) -> RunnableConfig:
    """The run configuration that names a run's saved state."""
    return {"configurable": {"thread_id": thread_id}}


def answer_from(final: RunResult) -> AgentAnswer:
    """The ``AgentAnswer`` a finished run's state describes, with its citations resolved."""
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


async def ask(graph: CompiledAgent, question: str, *, thread_id: str | None = None) -> AgentAnswer:
    """Run ``graph`` on ``question`` from start to answer and return it.

    ``thread_id`` names the run's saved state when the graph has a checkpointer. A graph that
    pauses for approval cannot finish in one call, so this raises ``ValueError`` for one; use
    ``start`` and ``resume`` instead.
    """
    run_config = None if thread_id is None else thread_config(thread_id)
    final: RunResult = await graph.ainvoke(start_state(question), config=run_config)
    if paused_at(final) is not None:
        raise ValueError(
            "The run stopped for approval of its sources. Use start and resume, or build the "
            "graph without require_approval."
        )
    return answer_from(final)


async def start(graph: CompiledAgent, question: str, *, thread_id: str) -> AgentOutcome:
    """Run ``graph`` on ``question`` until it answers or stops at the checkpoint.

    The state is saved under ``thread_id``, which ``resume`` names to continue a paused run.
    """
    final: RunResult = await graph.ainvoke(start_state(question), config=thread_config(thread_id))
    return outcome_from(final, thread_id)


async def resume(graph: CompiledAgent, decision: str, *, thread_id: str) -> AgentOutcome:
    """Continue the run paused under ``thread_id`` with ``decision`` on its sources.

    Approval goes on to the answer; rejection searches again while a hop is left. The run can stop
    at the checkpoint again, on the sources the rewritten query found. Raises ``ValueError`` if no
    run under ``thread_id`` is waiting for a decision, so a stale thread id cannot start a new run.
    """
    config = thread_config(thread_id)
    saved = await graph.aget_state(config)
    # Resuming a thread that is not paused would run the graph from the start on empty state.
    if not saved.interrupts:
        raise ValueError(f"No run under thread id {thread_id!r} is waiting for a decision.")
    # Checked here as well as in the node, so a bad decision costs no saved state.
    decision_is_approval(decision)
    final: RunResult = await graph.ainvoke(Command(resume=decision), config=config)
    return outcome_from(final, thread_id)
