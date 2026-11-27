"""Contract tests for ``RerankerProtocol``, run against the word-overlap fake and the real model.

The fastembed tests load ``jina-reranker-v1-tiny-en`` (about 130 MB on first use), so they are
marked ``integration``.
"""

from pathlib import Path

import pytest

from rag_core.config import Settings
from rag_core.rerank import FastembedReranker, RerankerProtocol
from rag_core_testing import OverlapReranker

QUERY = "Which Bazel flag runs every test under AddressSanitizer?"
RELEVANT = "Bazel: bazel test --config=asan runs every test under AddressSanitizer."
UNRELATED = "Paris is the capital of France."


@pytest.fixture(
    params=[
        pytest.param("overlap", id="overlap"),
        pytest.param("fastembed", id="fastembed", marks=pytest.mark.integration),
    ]
)
def reranker(request: pytest.FixtureRequest) -> RerankerProtocol:
    """Each reranker implementation, once per test."""
    if request.param == "overlap":
        return OverlapReranker()
    return FastembedReranker("jinaai/jina-reranker-v1-tiny-en")


def test_scores_come_back_in_document_order(reranker: RerankerProtocol) -> None:
    """One score per document, in the order the documents were given, whichever way round."""
    forward = reranker.score(QUERY, [UNRELATED, RELEVANT, UNRELATED])
    backward = reranker.score(QUERY, [RELEVANT, UNRELATED])

    assert len(forward) == 3
    assert forward[0] == pytest.approx(forward[2])
    assert forward[1] > forward[0]
    assert backward[0] > backward[1]


def test_scores_are_relevance_from_zero_to_one(reranker: RerankerProtocol) -> None:
    """Every score lies in 0 to 1, so one threshold works whatever the model."""
    for score in reranker.score(QUERY, [RELEVANT, UNRELATED]):
        assert 0.0 <= score <= 1.0


def test_a_relevant_document_outscores_an_unrelated_one(reranker: RerankerProtocol) -> None:
    """The passage that answers the question scores higher than one about something else."""
    relevant, unrelated = reranker.score(QUERY, [RELEVANT, UNRELATED])

    assert relevant > unrelated


def test_no_documents_gives_no_scores(reranker: RerankerProtocol) -> None:
    """An empty candidate list is scored without loading anything or failing."""
    assert reranker.score(QUERY, []) == []


def test_both_rerankers_satisfy_the_protocol() -> None:
    """The model-backed reranker and the fake fit ``RerankerProtocol``."""
    real: RerankerProtocol = FastembedReranker("jinaai/jina-reranker-v1-tiny-en")
    fake: RerankerProtocol = OverlapReranker()
    assert isinstance(real, RerankerProtocol)
    assert isinstance(fake, RerankerProtocol)


def test_building_the_reranker_loads_nothing() -> None:
    """Building the reranker downloads and loads nothing."""
    reranker = FastembedReranker("jinaai/jina-reranker-v1-tiny-en")

    assert reranker.is_loaded is False


@pytest.mark.integration
def test_the_first_score_loads_the_model() -> None:
    """Scoring loads the model, and the reranker keeps it for later calls."""
    reranker = FastembedReranker("jinaai/jina-reranker-v1-tiny-en")

    reranker.score(QUERY, [RELEVANT])

    assert reranker.is_loaded is True


def test_an_unknown_model_is_refused_when_built() -> None:
    """A model fastembed cannot run is a configuration error found before any download."""
    with pytest.raises(ValueError, match="not-a-reranker"):
        FastembedReranker("not-a-reranker")


def test_settings_choose_the_reranker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reranking is on by default, with the tiny jina model rescoring 20 candidates."""
    monkeypatch.chdir(tmp_path)
    for name in ["RERANK_ENABLED", "RERANKER_MODEL", "RERANK_CANDIDATES", "HYBRID_ENABLED"]:
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.hybrid_enabled is False

    assert settings.rerank_enabled is True
    assert settings.reranker_model == "jinaai/jina-reranker-v1-tiny-en"
    assert settings.rerank_candidates == 20
    assert FastembedReranker.from_settings(settings).model_id == settings.reranker_model
