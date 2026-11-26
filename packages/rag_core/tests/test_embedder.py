"""Behavior of text embedders.

The contract tests take ``embedder: EmbedderProtocol`` and run against the hashing fake and the real
``FastembedEmbedder``. The fastembed run is marked ``integration`` because it downloads and loads
the model on first use. The tests after the contract pin what only ``FastembedEmbedder`` does.
"""

import math
from collections.abc import Iterator
from pathlib import Path

import pytest

from rag_core.config import Settings
from rag_core.embed import EmbedderProtocol, FastembedEmbedder
from rag_core.store.embedders import EmbedderInfo
from rag_core_testing import HashingEmbedder

BGE_SMALL = "BAAI/bge-small-en-v1.5"
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@pytest.fixture(scope="module")
def bge_small() -> Iterator[FastembedEmbedder]:
    """One ``bge-small-en-v1.5`` embedder for the module, so the model loads once."""
    yield FastembedEmbedder(model_id=BGE_SMALL, dimension=384, query_prefix=BGE_QUERY_PREFIX)


@pytest.fixture(
    params=[
        "hashing",
        pytest.param("fastembed", marks=pytest.mark.integration),
    ]
)
def embedder(request: pytest.FixtureRequest) -> EmbedderProtocol:
    """Every ``EmbedderProtocol`` implementation, once each."""
    if request.param == "hashing":
        return HashingEmbedder()
    real: FastembedEmbedder = request.getfixturevalue("bge_small")
    return real


def norm(vector: list[float]) -> float:
    """Euclidean length of ``vector``."""
    total = 0.0
    for value in vector:
        total += value * value
    return math.sqrt(total)


def dot(a: list[float], b: list[float]) -> float:
    """Dot product of two vectors of the same length."""
    total = 0.0
    for x, y in zip(a, b, strict=True):
        total += x * y
    return total


def test_conforms_to_the_protocol(embedder: EmbedderProtocol) -> None:
    """Each implementation satisfies ``EmbedderProtocol`` at run time."""
    assert isinstance(embedder, EmbedderProtocol)


def test_documents_get_one_vector_each_in_order(embedder: EmbedderProtocol) -> None:
    """``embed_documents`` returns one vector per text, each ``info.dimension`` long."""
    texts = ["cmake build", "bazel test", "release notes"]
    vectors = embedder.embed_documents(texts)
    assert len(vectors) == len(texts)
    for vector in vectors:
        assert len(vector) == embedder.info.dimension
    assert vectors[1] == embedder.embed_documents(["bazel test"])[0]


def test_no_documents_give_no_vectors(embedder: EmbedderProtocol) -> None:
    """An empty batch embeds to an empty list without loading anything it does not need."""
    assert embedder.embed_documents([]) == []


def test_query_vector_has_the_model_dimension(embedder: EmbedderProtocol) -> None:
    """``embed_query`` returns one vector of ``info.dimension`` floats."""
    vector = embedder.embed_query("how do I enable AddressSanitizer?")
    assert len(vector) == embedder.info.dimension
    for value in vector:
        assert isinstance(value, float)


def test_vectors_are_unit_length(embedder: EmbedderProtocol) -> None:
    """Every vector has length 1, so the dot product equals cosine similarity."""
    vectors = embedder.embed_documents(["link with -pthread", "set CMAKE_BUILD_TYPE"])
    vectors.append(embedder.embed_query("pthread linker error"))
    for vector in vectors:
        assert norm(vector) == pytest.approx(1.0, abs=1e-5)


def test_embedding_is_deterministic(embedder: EmbedderProtocol) -> None:
    """The same text always embeds to the same vector."""
    first = embedder.embed_documents(["remote cache endpoint"])[0]
    second = embedder.embed_documents(["remote cache endpoint"])[0]
    assert first == second


def test_a_related_document_scores_above_an_unrelated_one(embedder: EmbedderProtocol) -> None:
    """A query is more similar to a document about its topic than to one that is not."""
    related, unrelated = embedder.embed_documents(
        [
            "Bazel: pass --config=asan to build and test with AddressSanitizer.",
            "Release 4.2 notes: the ingest command now skips unchanged files.",
        ]
    )
    query = embedder.embed_query("Which Bazel flag enables AddressSanitizer?")
    assert dot(query, related) > dot(query, unrelated)


def test_info_names_the_configured_model() -> None:
    """``info`` is the model id and dimension the embedder was built with."""
    embedder = FastembedEmbedder(model_id=BGE_SMALL, dimension=384)
    assert embedder.info == EmbedderInfo(model_id=BGE_SMALL, dimension=384)


def test_building_the_embedder_does_not_load_the_model() -> None:
    """The model is loaded on first use, not when the embedder is built."""
    embedder = FastembedEmbedder(model_id=BGE_SMALL, dimension=384)
    assert embedder.is_loaded is False


def test_an_unsupported_model_is_refused_when_built() -> None:
    """A model id fastembed does not provide fails at once, before any download."""
    with pytest.raises(ValueError, match="not/a-model"):
        FastembedEmbedder(model_id="not/a-model", dimension=384)


def test_a_wrong_dimension_is_refused_when_built() -> None:
    """A dimension that differs from the model's own fails at once, naming both numbers."""
    with pytest.raises(ValueError, match="768.*384|384.*768"):
        FastembedEmbedder(model_id=BGE_SMALL, dimension=768)


@pytest.mark.integration
def test_first_use_loads_the_model(bge_small: FastembedEmbedder) -> None:
    """Embedding something loads the model, and it stays loaded."""
    bge_small.embed_query("warm up")
    assert bge_small.is_loaded is True


@pytest.mark.integration
def test_query_prefix_is_prepended_to_queries_only(bge_small: FastembedEmbedder) -> None:
    """A query is embedded as ``query_prefix`` plus the text; documents are embedded as given."""
    text = "Which flag enables AddressSanitizer?"
    query = bge_small.embed_query(text)
    as_document = bge_small.embed_documents([BGE_QUERY_PREFIX + text])[0]
    plain = bge_small.embed_documents([text])[0]
    assert query == pytest.approx(as_document, abs=1e-5)
    assert query != pytest.approx(plain, abs=1e-5)


@pytest.fixture
def no_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run from an empty folder with no embedding variables set, so only defaults apply."""
    monkeypatch.chdir(tmp_path)
    for name in ("EMBEDDING_MODEL", "EMBEDDING_DIMENSION", "EMBEDDING_QUERY_PREFIX"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("no_env_overrides")
def test_settings_default_to_bge_small_with_its_query_instruction() -> None:
    """Without overrides, the configured embedder is ``bge-small-en-v1.5`` at 384 dimensions."""
    defaults = Settings()
    assert defaults.embedding_model == BGE_SMALL
    assert defaults.embedding_dimension == 384
    assert defaults.embedding_query_prefix == BGE_QUERY_PREFIX


@pytest.mark.usefixtures("no_env_overrides")
def test_settings_read_the_embedder_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second embedder is selected by environment variables, with no code change."""
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "")
    configured = Settings()
    assert configured.embedding_model == "BAAI/bge-base-en-v1.5"
    assert configured.embedding_dimension == 768
    assert configured.embedding_query_prefix == ""


def test_embedder_from_settings_uses_the_configured_model() -> None:
    """``FastembedEmbedder.from_settings`` builds the embedder the settings name."""
    configured = Settings(
        embedding_model="BAAI/bge-base-en-v1.5",
        embedding_dimension=768,
        embedding_query_prefix="q: ",
    )
    embedder = FastembedEmbedder.from_settings(configured)
    assert embedder.info == EmbedderInfo(model_id="BAAI/bge-base-en-v1.5", dimension=768)
    assert embedder.query_prefix == "q: "
