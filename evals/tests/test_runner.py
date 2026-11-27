"""Tests for ``run_eval`` and ``write_run``: scoring the golden set and saving the run."""

import json
from pathlib import Path
from typing import Any

import pytest

from evals.golden import ExpectedSection, GoldenQuestion
from evals.metrics import percentile
from evals.runner import EvalRun, run_eval, write_run
from rag_core_testing import HashingEmbedder, InMemoryStore, OverlapReranker


class CountingEmbedder(HashingEmbedder):
    """A hashing embedder that counts the queries it embeds."""

    def __init__(self) -> None:
        """Start with no queries embedded."""
        super().__init__()
        self.queries = 0

    def embed_query(self, text: str) -> list[float]:
        """Embed ``text`` and count it."""
        self.queries += 1
        return super().embed_query(text)


def test_run_eval_scores_each_question_and_the_whole_set(
    store: InMemoryStore,
    embedder: HashingEmbedder,
    caching_question: GoldenQuestion,
    mislabeled_question: GoldenQuestion,
) -> None:
    """Each question gets its recall and reciprocal rank, and the run their means."""
    run = run_eval([caching_question, mislabeled_question], embedder=embedder, store=store, k=1)

    by_id = {}
    for result in run.questions:
        by_id[result.id] = result
    assert by_id["caching"].recall == 1.0
    assert by_id["caching"].reciprocal_rank == 1.0
    assert by_id["mislabeled"].recall == 0.0
    assert by_id["mislabeled"].reciprocal_rank == 0.0
    assert run.recall_at_k == 0.5
    assert run.mrr == 0.5


def test_run_eval_gives_partial_recall_when_some_labels_are_missed(
    store: InMemoryStore, embedder: HashingEmbedder
) -> None:
    """A question with two labels and one found has recall 0.5."""
    question = GoldenQuestion(
        id="two",
        text="ccache compiled objects",
        expected=(
            ExpectedSection("build.md", "Caching"),
            ExpectedSection("ci/pthread.md", "Cause"),
        ),
    )

    run = run_eval([question], embedder=embedder, store=store, k=1)

    assert run.questions[0].recall == 0.5


def test_run_eval_records_the_ranked_sections(
    store: InMemoryStore, embedder: HashingEmbedder, caching_question: GoldenQuestion
) -> None:
    """Each question keeps what was retrieved, nearest first, by document and heading path."""
    run = run_eval([caching_question], embedder=embedder, store=store, k=3)

    retrieved = run.questions[0].retrieved
    assert len(retrieved) == 3
    assert retrieved[0].document == "build.md"
    assert retrieved[0].section == "Build > Caching"
    assert retrieved[0].distance <= retrieved[1].distance <= retrieved[2].distance


def test_run_eval_times_every_repeat_after_one_untimed_warm_up(
    store: InMemoryStore, caching_question: GoldenQuestion, mislabeled_question: GoldenQuestion
) -> None:
    """Each question is retrieved ``repeats`` times, plus one warm-up query before any timing."""
    embedder = CountingEmbedder()

    run = run_eval(
        [caching_question, mislabeled_question], embedder=embedder, store=store, k=1, repeats=3
    )

    assert embedder.queries == 2 * 3 + 1
    samples: list[float] = []
    for result in run.questions:
        assert len(result.latencies_ms) == 3
        samples.extend(result.latencies_ms)
    assert run.latency_p50_ms == percentile(samples, 50)
    assert run.latency_p95_ms == percentile(samples, 95)


def test_run_eval_records_its_settings(
    store: InMemoryStore, embedder: HashingEmbedder, caching_question: GoldenQuestion
) -> None:
    """The run names the model and the settings it was measured with."""
    run = run_eval([caching_question], embedder=embedder, store=store, k=2, ef_search=10, repeats=2)

    assert run.model_id == embedder.info.model_id
    assert run.dimension == embedder.info.dimension
    assert run.k == 2
    assert run.ef_search == 10
    assert run.repeats == 2


@pytest.mark.parametrize(
    "settings",
    [
        {"k": 0},
        {"repeats": 0},
        {"k": 5, "ef_search": 2},
        {"k": 5, "reranker": OverlapReranker(), "candidates": 2},
    ],
    ids=["k below one", "repeats below one", "ef_search below k", "candidates below k"],
)
def test_run_eval_rejects_invalid_settings(
    store: InMemoryStore,
    embedder: HashingEmbedder,
    caching_question: GoldenQuestion,
    settings: dict[str, Any],
) -> None:
    """Settings retrieval cannot honor raise ``ValueError``."""
    with pytest.raises(ValueError):
        run_eval([caching_question], embedder=embedder, store=store, **settings)


def test_run_eval_rejects_an_empty_golden_set(
    store: InMemoryStore, embedder: HashingEmbedder
) -> None:
    """A run needs at least one question."""
    with pytest.raises(ValueError):
        run_eval([], embedder=embedder, store=store)


@pytest.fixture
def run(
    store: InMemoryStore, embedder: HashingEmbedder, caching_question: GoldenQuestion
) -> EvalRun:
    """A finished run over one question."""
    return run_eval([caching_question], embedder=embedder, store=store, k=2)


def test_write_run_saves_a_json_file_named_after_the_run(run: EvalRun, tmp_path: Path) -> None:
    """The saved file holds the name, a timestamp, the totals, and every question's result."""
    path = write_run(run, tmp_path / "results", name="dense-baseline")

    assert path == tmp_path / "results" / "dense-baseline.json"
    saved = json.loads(path.read_text())
    assert saved["name"] == "dense-baseline"
    assert saved["created_at"]
    assert saved["model_id"] == run.model_id
    assert saved["recall_at_k"] == run.recall_at_k
    assert saved["latency_p95_ms"] == run.latency_p95_ms
    assert saved["questions"][0]["id"] == "caching"
    assert saved["questions"][0]["retrieved"][0]["section"] == "Build > Caching"


def test_write_run_never_overwrites_a_saved_run(run: EvalRun, tmp_path: Path) -> None:
    """A name already used raises ``FileExistsError`` and leaves the saved run as it was."""
    path = write_run(run, tmp_path, name="dense-baseline")
    before = path.read_text()

    with pytest.raises(FileExistsError):
        write_run(run, tmp_path, name="dense-baseline")
    assert path.read_text() == before


@pytest.mark.parametrize("name", ["", "../outside", "a/b", "with space"])
def test_write_run_rejects_a_name_that_is_not_a_plain_file_name(
    run: EvalRun, tmp_path: Path, name: str
) -> None:
    """Names are letters, digits, dots, dashes, and underscores, so a run stays in its folder."""
    with pytest.raises(ValueError):
        write_run(run, tmp_path, name=name)


def test_run_eval_reranks_and_records_the_reranker(
    store: InMemoryStore, embedder: HashingEmbedder, caching_question: GoldenQuestion
) -> None:
    """With a reranker, the run uses it for every question and names it and its candidates."""
    run = run_eval(
        [caching_question],
        embedder=embedder,
        store=store,
        k=1,
        reranker=OverlapReranker(),
        candidates=3,
    )

    assert run.reranker == "test/overlap-reranker"
    assert run.candidates == 3
    assert run.questions[0].recall == 1.0


def test_run_eval_without_a_reranker_records_none(run: EvalRun) -> None:
    """A dense-only run says so in its saved settings."""
    assert run.reranker is None
    assert run.candidates is None


def test_run_eval_records_the_candidates_actually_reranked(
    store: InMemoryStore, embedder: HashingEmbedder, caching_question: GoldenQuestion
) -> None:
    """A store holding fewer chunks than requested records how many the reranker scored."""
    run = run_eval(
        [caching_question],
        embedder=embedder,
        store=store,
        k=1,
        reranker=OverlapReranker(),
        candidates=20,
    )

    assert run.candidates == 3
