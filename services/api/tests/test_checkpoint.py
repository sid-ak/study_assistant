"""The checkpointer that saves paused runs: its serializer, its settings, and a Postgres round trip.

A paused run is only resumable if what it saved comes back as the objects the graph put there. The
serializer tests pin that for the hits the graph carries, and the integration test pins it through
a real database.
"""

import asyncio
import json

import psycopg
import pytest
from api_fakes import FakeSearchClient, ScriptedGenerator
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from api.graph import APPROVE, AgentAnswer, AgentConfig, PendingReview, build_graph, resume, start
from api.graph.checkpoint import checkpoint_serializer, postgres_checkpointer
from api.mcp_client import SearchHit

QUESTION = "Which Bazel flag runs tests under AddressSanitizer?"
THREAD = "thread-postgres-1"
REVIEW_CONFIG = AgentConfig(
    max_hops=2, relevance_threshold=0.65, search_limit=5, require_approval=True
)
HIT = SearchHit(
    id="chunk-asan",
    document="build_systems/bazel-basics.md",
    section="Bazel basics > Configs in .bazelrc",
    content="bazel test --config=asan //...",
    distance=0.20,
    relevance=0.80,
)


def answer_reply(answer: str, cited: list[str]) -> str:
    """The JSON the model returns for the answer step."""
    return json.dumps({"answerable": True, "answer": answer, "cited_chunk_ids": cited})


def test_the_checkpoint_serializer_keeps_a_search_hit_a_search_hit() -> None:
    """A resumed run reads its hits back as hits, so the answer step can still use their fields."""
    serializer = checkpoint_serializer()

    restored = serializer.loads_typed(serializer.dumps_typed([HIT]))

    assert restored == [HIT]
    assert isinstance(restored[0], SearchHit)


def test_a_serializer_without_the_allowed_type_degrades_a_search_hit_to_a_dict() -> None:
    """Why the allowlist is set: without it a strict serializer restores plain dicts instead.

    LangGraph will refuse unlisted types by default in a later version, and a dict in place of a
    hit would fail only later, inside the answer step.
    """
    strict = JsonPlusSerializer(allowed_msgpack_modules=None)

    restored = strict.loads_typed(strict.dumps_typed([HIT]))

    assert restored == [
        {
            "id": "chunk-asan",
            "document": "build_systems/bazel-basics.md",
            "section": "Bazel basics > Configs in .bazelrc",
            "content": "bazel test --config=asan //...",
            "distance": 0.20,
            "relevance": 0.80,
        }
    ]


@pytest.mark.parametrize("url", ["", "   "], ids=["empty", "blank"])
def test_a_checkpointer_without_a_database_url_is_refused(url: str) -> None:
    """A saver with nowhere to connect would fail at the pause, after the search was paid for."""

    async def open_it() -> None:
        async with postgres_checkpointer(url):
            pass

    with pytest.raises(ValueError, match="database"):
        asyncio.run(open_it())


@pytest.mark.integration
def test_a_paused_run_is_saved_in_postgres_and_read_back(checkpoint_database_url: str) -> None:
    """A second saver over the same database finds the paused run, its hits still hits."""

    async def pause_then_read() -> tuple[PendingReview, list[SearchHit]]:
        search = FakeSearchClient({QUESTION: [HIT]})
        async with postgres_checkpointer(checkpoint_database_url) as saver:
            graph = build_graph(
                search, ScriptedGenerator([]), config=REVIEW_CONFIG, checkpointer=saver
            )
            outcome = await start(graph, QUESTION, thread_id=THREAD)
        assert isinstance(outcome, PendingReview)
        # A second saver, so the state comes from the database and not from the first one's memory.
        async with postgres_checkpointer(checkpoint_database_url) as other_saver:
            graph = build_graph(
                FakeSearchClient({}),
                ScriptedGenerator([]),
                config=REVIEW_CONFIG,
                checkpointer=other_saver,
            )
            saved = await graph.aget_state({"configurable": {"thread_id": THREAD}})
        return outcome, saved.values["hits"]

    pending, hits = asyncio.run(pause_then_read())

    assert [source.id for source in pending.sources] == ["chunk-asan"]
    assert hits == [HIT]
    assert isinstance(hits[0], SearchHit)
    # The row itself, so the state is in the database and not only in the saver's answers.
    with psycopg.connect(checkpoint_database_url) as connection:
        rows = connection.execute(
            "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (THREAD,)
        ).fetchone()
    assert rows is not None
    assert rows[0] > 0


@pytest.mark.integration
def test_a_run_saved_in_postgres_is_resumed_to_a_cited_answer(checkpoint_database_url: str) -> None:
    """The decision can arrive against a saver that never saw the run start."""

    async def pause_then_resume() -> AgentAnswer:
        async with postgres_checkpointer(checkpoint_database_url) as saver:
            graph = build_graph(
                FakeSearchClient({QUESTION: [HIT]}),
                ScriptedGenerator([]),
                config=REVIEW_CONFIG,
                checkpointer=saver,
            )
            await start(graph, QUESTION, thread_id=THREAD)
        async with postgres_checkpointer(checkpoint_database_url) as other_saver:
            # No hits prepared and no query answered: the context must come from the saved run.
            search = FakeSearchClient({})
            generator = ScriptedGenerator([answer_reply("Use --config=asan.", ["chunk-asan"])])
            graph = build_graph(search, generator, config=REVIEW_CONFIG, checkpointer=other_saver)
            outcome = await resume(graph, APPROVE, thread_id=THREAD)
        assert isinstance(outcome, AgentAnswer)
        assert search.queries == []
        return outcome

    answer = asyncio.run(pause_then_resume())

    assert answer.status == "answered"
    assert answer.answer == "Use --config=asan."
    assert [citation.section for citation in answer.citations] == [
        "Bazel basics > Configs in .bazelrc"
    ]
