"""Behavior of the agent graph: retrieve, grade by score, then generate or rewrite, at most twice.

The search client and the generator are fakes, so each test fixes what retrieval returns and what
the model replies, then checks the path the graph took: which queries it searched, how many model
requests it made, and what it returned.
"""

import asyncio
import json
from typing import Any

import pytest
from api_fakes import FakeSearchClient, ScriptedGenerator
from langgraph.checkpoint.memory import InMemorySaver

from api.generate import GenerationError
from api.graph import AgentAnswer, AgentConfig, ask, build_graph
from api.mcp_client import SearchHit

QUESTION = "Which Bazel flag runs tests under AddressSanitizer?"
REWRITTEN = "bazel config asan AddressSanitizer test flag"
CONFIG = AgentConfig(max_hops=2, relevance_threshold=0.65, search_limit=5)


def hit(
    chunk_id: str, distance: float, content: str = "Some text.", relevance: float | None = None
) -> SearchHit:
    """A search hit; its relevance defaults to the cosine similarity, 1 minus ``distance``."""
    if relevance is None:
        relevance = 1.0 - distance
    return SearchHit(
        id=chunk_id,
        document="build_systems/bazel-basics.md",
        section="Bazel basics > Configs in .bazelrc",
        content=content,
        distance=distance,
        relevance=relevance,
    )


RELEVANT = [hit("chunk-asan", 0.20, "bazel test --config=asan //..."), hit("chunk-other", 0.40)]
IRRELEVANT = [hit("chunk-far", 0.60), hit("chunk-farther", 0.70)]


def answer_reply(answer: str, cited: list[str], answerable: bool = True) -> str:
    """The JSON the model returns for the answer step."""
    return json.dumps({"answerable": answerable, "answer": answer, "cited_chunk_ids": cited})


def run(
    search: FakeSearchClient,
    generator: ScriptedGenerator,
    config: AgentConfig = CONFIG,
) -> AgentAnswer:
    """Build the graph over the fakes and ask it ``QUESTION``."""
    graph = build_graph(search, generator, config=config)
    return asyncio.run(ask(graph, QUESTION))


def test_relevant_context_is_answered_after_one_search() -> None:
    """A first search above the threshold goes straight to generation: one search, one request."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])

    result = run(search, generator)

    assert result.status == "answered"
    assert result.answer == "Use --config=asan."
    assert result.cited_chunk_ids == ["chunk-asan"]
    assert [citation.id for citation in result.citations] == ["chunk-asan"]
    assert result.queries == [QUESTION]
    assert result.hops == 1
    assert search.queries == [QUESTION]
    assert len(generator.requests) == 1


def test_irrelevant_context_is_rewritten_and_searched_again() -> None:
    """Below the threshold, the model rewrites the query once and the graph searches again."""
    search = FakeSearchClient({QUESTION: IRRELEVANT, REWRITTEN: RELEVANT})
    generator = ScriptedGenerator([REWRITTEN, answer_reply("Use --config=asan.", ["chunk-asan"])])

    result = run(search, generator)

    assert result.status == "answered"
    assert result.queries == [QUESTION, REWRITTEN]
    assert result.hops == 2
    assert search.queries == [QUESTION, REWRITTEN]


def test_still_irrelevant_after_the_hop_limit_ends_with_insufficient_context() -> None:
    """Two searches below the threshold stop the loop without asking the model for an answer."""
    search = FakeSearchClient({QUESTION: IRRELEVANT, REWRITTEN: IRRELEVANT})
    generator = ScriptedGenerator([REWRITTEN])

    result = run(search, generator)

    assert result.status == "insufficient_context"
    assert result.answer == ""
    assert result.cited_chunk_ids == []
    assert result.hops == 2
    assert search.queries == [QUESTION, REWRITTEN]
    assert len(generator.requests) == 1


def test_the_hop_limit_is_a_setting() -> None:
    """With one hop allowed, an irrelevant first search ends the run without a rewrite."""
    search = FakeSearchClient({QUESTION: IRRELEVANT})
    generator = ScriptedGenerator([])

    result = run(search, generator, AgentConfig(max_hops=1, relevance_threshold=0.65))

    assert result.status == "insufficient_context"
    assert search.queries == [QUESTION]
    assert generator.requests == []


def test_no_hits_at_all_counts_as_irrelevant() -> None:
    """An empty search result is graded like an irrelevant one."""
    search = FakeSearchClient({})
    generator = ScriptedGenerator([REWRITTEN])

    result = run(search, generator)

    assert result.status == "insufficient_context"
    assert result.context == []


def test_grading_reads_the_relevance_the_search_reports() -> None:
    """A reranked hit far in vector space but scored relevant is graded on its score."""
    reranked = [hit("chunk-asan", 0.60, "bazel test --config=asan //...", relevance=0.92)]
    search = FakeSearchClient({QUESTION: reranked})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])

    result = run(search, generator)

    assert result.status == "answered"
    assert result.hops == 1


def test_a_low_reranker_score_is_irrelevant_however_near_the_vector() -> None:
    """A hit close in vector space but scored low by the reranker sends the graph to a rewrite."""
    near_but_wrong = [hit("chunk-near", 0.10, relevance=0.20)]
    search = FakeSearchClient({QUESTION: near_but_wrong})
    generator = ScriptedGenerator([REWRITTEN])

    result = run(search, generator)

    assert result.status == "insufficient_context"
    assert search.queries == [QUESTION, REWRITTEN]


def test_no_hits_is_never_relevant_even_at_a_zero_threshold() -> None:
    """With nothing retrieved there is nothing to answer from, so generation is never reached."""
    search = FakeSearchClient({})
    generator = ScriptedGenerator([REWRITTEN])

    result = run(search, generator, AgentConfig(max_hops=2, relevance_threshold=0.0))

    assert result.status == "insufficient_context"
    assert len(generator.requests) == 1


def test_the_model_can_judge_relevant_context_insufficient() -> None:
    """Context above the threshold may still not answer the question; the model says so."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("", [], answerable=False)])

    result = run(search, generator)

    assert result.status == "insufficient_context"
    assert result.cited_chunk_ids == []


def test_each_model_request_does_one_job() -> None:
    """The rewrite is free text; the answer is one strict-schema request, not a tool call."""
    search = FakeSearchClient({QUESTION: IRRELEVANT, REWRITTEN: RELEVANT})
    generator = ScriptedGenerator([REWRITTEN, answer_reply("Use --config=asan.", ["chunk-asan"])])

    run(search, generator)

    rewrite_messages, rewrite_schema = generator.requests[0]
    answer_messages, answer_schema = generator.requests[1]
    assert rewrite_schema is None
    assert QUESTION in rewrite_messages[-1].content
    assert answer_schema is not None
    assert answer_schema.schema["additionalProperties"] is False
    assert set(answer_schema.schema["required"]) == {"answerable", "answer", "cited_chunk_ids"}


def test_the_answer_schema_only_allows_ids_from_the_context() -> None:
    """The cited ids are an enum of the chunks the model was shown, so no other id can be cited."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])

    run(search, generator)

    messages, schema = generator.requests[0]
    assert schema is not None
    items: dict[str, Any] = schema.schema["properties"]["cited_chunk_ids"]["items"]
    assert items["enum"] == ["chunk-asan", "chunk-other"]
    prompt = messages[-1].content
    assert "chunk-asan" in prompt
    assert "bazel test --config=asan //..." in prompt
    assert QUESTION in prompt


def test_the_prompt_keeps_citations_out_of_the_answer_text() -> None:
    """The instructions say ids go in the cited-ids field only, never in the answer."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])

    run(search, generator)

    instructions = generator.requests[0][0][0]
    assert instructions.role == "system"
    assert "cited_chunk_ids" in instructions.content
    assert "never" in instructions.content.lower()


def test_an_id_outside_the_context_is_kept_but_not_resolved() -> None:
    """A cited id that names no context chunk stays visible, so grounding checks can catch it."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan", "made-up"])])

    result = run(search, generator)

    assert result.cited_chunk_ids == ["chunk-asan", "made-up"]
    assert [citation.id for citation in result.citations] == ["chunk-asan"]


@pytest.mark.parametrize(
    "reply",
    ["not json", json.dumps({"answer": "x"}), json.dumps([1, 2])],
    ids=["not JSON", "missing fields", "not an object"],
)
def test_an_unreadable_answer_raises_generation_error(reply: str) -> None:
    """A reply that does not match the schema is an error, not a silently empty answer."""
    search = FakeSearchClient({QUESTION: RELEVANT})

    with pytest.raises(GenerationError):
        run(search, ScriptedGenerator([reply]))


def test_a_blank_rewrite_searches_with_the_original_question() -> None:
    """If the model returns no query, the second search reuses the question."""
    search = FakeSearchClient({QUESTION: IRRELEVANT})
    generator = ScriptedGenerator(["   "])

    run(search, generator)

    assert search.queries == [QUESTION, QUESTION]


def test_the_graph_compiles_without_a_checkpointer_by_default() -> None:
    """No checkpointer unless one is passed, so runs keep no state between calls."""
    graph = build_graph(FakeSearchClient({}), ScriptedGenerator([]), config=CONFIG)

    assert graph.checkpointer is None


def test_a_checkpointer_saves_the_runs_state() -> None:
    """With a checkpointer and a thread id, the final state can be read back after the run."""
    search = FakeSearchClient({QUESTION: RELEVANT})
    generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])
    graph = build_graph(search, generator, config=CONFIG, checkpointer=InMemorySaver())

    asyncio.run(ask(graph, QUESTION, thread_id="thread-1"))

    saved = graph.get_state({"configurable": {"thread_id": "thread-1"}})
    assert saved.values["question"] == QUESTION
    assert saved.values["status"] == "answered"


@pytest.mark.parametrize(
    "settings",
    [{"max_hops": 0}, {"relevance_threshold": 1.5}, {"search_limit": 0}, {"search_limit": 21}],
    ids=["no hops", "threshold above one", "no results", "more results than the tool returns"],
)
def test_agent_config_rejects_values_that_cannot_work(settings: dict[str, Any]) -> None:
    """A run needs at least one hop and one result, and a similarity threshold within 0 to 1."""
    with pytest.raises(ValueError):
        AgentConfig(**settings)
