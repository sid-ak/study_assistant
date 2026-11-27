"""Behavior of the approval checkpoint: the graph pauses after grading and resumes by thread id.

The search client and the generator are fakes, and the paused state is kept by the in-memory
checkpointer, so each test fixes what retrieval returns and what the model replies, then checks
where the run stopped, what it offered for approval, and which path the decision took.
"""

import asyncio
import json

import pytest
from api_fakes import FakeSearchClient, ScriptedGenerator
from langgraph.checkpoint.memory import InMemorySaver

from api.graph import (
    APPROVE,
    REJECT,
    AgentAnswer,
    AgentConfig,
    CompiledAgent,
    PendingReview,
    ask,
    build_graph,
    resume,
    start,
)
from api.mcp_client import SearchHit

QUESTION = "Which Bazel flag runs tests under AddressSanitizer?"
REWRITTEN = "bazel config asan AddressSanitizer test flag"
THREAD = "thread-1"
REVIEW_CONFIG = AgentConfig(
    max_hops=2, relevance_threshold=0.65, search_limit=5, require_approval=True
)


def hit(chunk_id: str, distance: float, section: str, content: str = "Some text.") -> SearchHit:
    """A search hit whose relevance is the cosine similarity, 1 minus ``distance``."""
    return SearchHit(
        id=chunk_id,
        document="build_systems/bazel-basics.md",
        section=section,
        content=content,
        distance=distance,
        relevance=1.0 - distance,
    )


RELEVANT = [
    hit("chunk-asan", 0.20, "Bazel basics > Configs in .bazelrc", "bazel test --config=asan //..."),
    hit("chunk-other", 0.40, "Bazel basics > Remote cache"),
]
SECOND_RELEVANT = [hit("chunk-asan-2", 0.15, "Sanitizers > AddressSanitizer")]
IRRELEVANT = [hit("chunk-far", 0.60, "Bazel basics > Workspace layout")]


def answer_reply(answer: str, cited: list[str]) -> str:
    """The JSON the model returns for the answer step."""
    return json.dumps({"answerable": True, "answer": answer, "cited_chunk_ids": cited})


def review_graph(
    search: FakeSearchClient,
    generator: ScriptedGenerator,
    config: AgentConfig = REVIEW_CONFIG,
) -> CompiledAgent:
    """The graph over the fakes, with approval required and its state kept in memory."""
    return build_graph(search, generator, config=config, checkpointer=InMemorySaver())


def test_a_run_that_needs_approval_pauses_after_grading() -> None:
    """Relevant context is offered for approval instead of being answered straight away."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([])
    graph = review_graph(search, generator)

    outcome = asyncio.run(start(graph, QUESTION, thread_id=THREAD))

    assert isinstance(outcome, PendingReview)
    assert outcome.thread_id == THREAD
    assert outcome.question == QUESTION
    assert outcome.query == QUESTION
    assert outcome.hops == 1
    assert [source.id for source in outcome.sources] == ["chunk-asan", "chunk-other"]
    assert outcome.sources[0].document == "build_systems/bazel-basics.md"
    assert outcome.sources[0].section == "Bazel basics > Configs in .bazelrc"
    # The answer step is after the checkpoint, so nothing has been generated yet.
    assert generator.requests == []


def test_approving_the_sources_generates_a_cited_answer() -> None:
    """A resume with the approval decision runs the answer step on the approved context."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])
    graph = review_graph(search, generator)
    asyncio.run(start(graph, QUESTION, thread_id=THREAD))

    outcome = asyncio.run(resume(graph, APPROVE, thread_id=THREAD))

    assert isinstance(outcome, AgentAnswer)
    assert outcome.status == "answered"
    assert outcome.answer == "Use --config=asan."
    assert [citation.id for citation in outcome.citations] == ["chunk-asan"]
    assert outcome.hops == 1
    # The approved run searched once, before the pause, and never again.
    assert search.queries == [QUESTION]


def test_rejecting_the_sources_rewrites_the_query_and_pauses_again() -> None:
    """A rejection spends the next hop: the model rewrites, the graph searches and pauses again."""
    search = FakeSearchClient({QUESTION: RELEVANT, REWRITTEN: SECOND_RELEVANT})
    generator = ScriptedGenerator([REWRITTEN])
    graph = review_graph(search, generator)
    asyncio.run(start(graph, QUESTION, thread_id=THREAD))

    outcome = asyncio.run(resume(graph, REJECT, thread_id=THREAD))

    assert isinstance(outcome, PendingReview)
    assert outcome.query == REWRITTEN
    assert outcome.hops == 2
    assert [source.id for source in outcome.sources] == ["chunk-asan-2"]
    assert search.queries == [QUESTION, REWRITTEN]


def test_a_second_approval_answers_from_the_rewritten_search() -> None:
    """Approving after a rejection answers from the sources the rewritten query found."""
    search = FakeSearchClient({QUESTION: RELEVANT, REWRITTEN: SECOND_RELEVANT})
    generator = ScriptedGenerator([REWRITTEN, answer_reply("Use --config=asan.", ["chunk-asan-2"])])
    graph = review_graph(search, generator)
    asyncio.run(start(graph, QUESTION, thread_id=THREAD))
    asyncio.run(resume(graph, REJECT, thread_id=THREAD))

    outcome = asyncio.run(resume(graph, APPROVE, thread_id=THREAD))

    assert isinstance(outcome, AgentAnswer)
    assert outcome.status == "answered"
    assert [citation.id for citation in outcome.citations] == ["chunk-asan-2"]
    assert outcome.queries == [QUESTION, REWRITTEN]
    assert outcome.hops == 2


def test_rejecting_the_sources_on_the_last_hop_stops_without_an_answer() -> None:
    """The hop limit bounds rejections too: with no hop left, the run ends unanswered."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([])
    graph = review_graph(
        search,
        generator,
        AgentConfig(max_hops=1, relevance_threshold=0.65, require_approval=True),
    )
    asyncio.run(start(graph, QUESTION, thread_id=THREAD))

    outcome = asyncio.run(resume(graph, REJECT, thread_id=THREAD))

    assert isinstance(outcome, AgentAnswer)
    assert outcome.status == "insufficient_context"
    assert outcome.answer == ""
    assert search.queries == [QUESTION]
    assert generator.requests == []


def test_irrelevant_context_is_never_offered_for_approval() -> None:
    """There is nothing to approve below the threshold: the graph rewrites on its own."""
    search = FakeSearchClient({QUESTION: IRRELEVANT, REWRITTEN: RELEVANT})
    generator = ScriptedGenerator([REWRITTEN])
    graph = review_graph(search, generator)

    outcome = asyncio.run(start(graph, QUESTION, thread_id=THREAD))

    assert isinstance(outcome, PendingReview)
    # The pause is on the second hop's relevant context, not the first hop's irrelevant one.
    assert outcome.hops == 2
    assert outcome.query == REWRITTEN
    assert [source.id for source in outcome.sources] == ["chunk-asan", "chunk-other"]


def test_a_run_that_needs_no_approval_answers_without_pausing() -> None:
    """Without ``require_approval`` the graph keeps its one-shot path through generation."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])
    graph = build_graph(
        search, generator, config=AgentConfig(require_approval=False), checkpointer=InMemorySaver()
    )

    outcome = asyncio.run(start(graph, QUESTION, thread_id=THREAD))

    assert isinstance(outcome, AgentAnswer)
    assert outcome.status == "answered"


def test_approval_without_a_checkpointer_is_refused() -> None:
    """A pause with nowhere to save it could not be resumed, so the graph refuses to compile."""
    with pytest.raises(ValueError, match="checkpointer"):
        build_graph(FakeSearchClient({}), ScriptedGenerator([]), config=REVIEW_CONFIG)


def test_ask_refuses_a_graph_that_pauses_for_approval() -> None:
    """``ask`` returns one answer, so it rejects a graph whose run stops at the checkpoint."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    graph = review_graph(search, ScriptedGenerator([]))

    with pytest.raises(ValueError, match="approval"):
        asyncio.run(ask(graph, QUESTION, thread_id=THREAD))


def test_resuming_a_thread_with_no_paused_run_is_refused() -> None:
    """A thread id that names no paused run must not quietly start a new run."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    graph = review_graph(search, ScriptedGenerator([]))

    with pytest.raises(ValueError, match="no-such-thread"):
        asyncio.run(resume(graph, APPROVE, thread_id="no-such-thread"))

    assert search.queries == []


def test_resuming_a_finished_run_is_refused() -> None:
    """Once the answer is in, the thread is no longer waiting for a decision."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])
    graph = review_graph(search, generator)
    asyncio.run(start(graph, QUESTION, thread_id=THREAD))
    asyncio.run(resume(graph, APPROVE, thread_id=THREAD))

    with pytest.raises(ValueError, match=THREAD):
        asyncio.run(resume(graph, APPROVE, thread_id=THREAD))


def test_a_decision_that_is_neither_approval_nor_rejection_is_refused() -> None:
    """An unknown decision must fail loudly rather than count as a rejection."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    graph = review_graph(search, ScriptedGenerator([]))
    asyncio.run(start(graph, QUESTION, thread_id=THREAD))

    with pytest.raises(ValueError, match="maybe"):
        asyncio.run(resume(graph, "maybe", thread_id=THREAD))


def test_two_threads_pause_independently() -> None:
    """Each thread id carries its own paused run, so one decision cannot resume the other."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])
    graph = review_graph(search, generator)
    asyncio.run(start(graph, QUESTION, thread_id="thread-a"))
    asyncio.run(start(graph, QUESTION, thread_id="thread-b"))

    answer = asyncio.run(resume(graph, APPROVE, thread_id="thread-a"))
    still_paused = asyncio.run(graph.aget_state({"configurable": {"thread_id": "thread-b"}}))

    assert isinstance(answer, AgentAnswer)
    assert still_paused.next == ("review_sources",)
