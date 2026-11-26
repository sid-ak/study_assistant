"""Behavior of ``embed_missing``: embedding stored chunks with a newly registered model.

Each test runs against both stores through the ``store`` fixture. The corpus is ingested with one
hashing embedder, then a second hashing embedder of another dimension stands in for the new model.
"""

from pathlib import Path

import pytest

from rag_core.embed import embed_missing
from rag_core.ingest import ingest_folder
from rag_core.retrieve import retrieve
from rag_core.store import StoreProtocol
from rag_core.store.embedders import EmbedderInfo, EmbedderRegistryProtocol
from rag_core_testing import HASHING_EMBEDDER, HashingEmbedder

# The model registered after ingestion, with its own dimension so its column is separate.
SECOND_MODEL = EmbedderInfo(model_id="test/hashing-embedder-second", dimension=32)


@pytest.fixture
def first_store(
    store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol, tmp_path: Path
) -> StoreProtocol:
    """A store holding a three-file corpus embedded by the first hashing model only."""
    embedder_registry.register(HASHING_EMBEDDER.model_id, HASHING_EMBEDDER.dimension)
    embedder_registry.register(SECOND_MODEL.model_id, SECOND_MODEL.dimension)
    (tmp_path / "build.md").write_text("# Build\n\nRun cmake with the release preset.\n")
    (tmp_path / "cache.md").write_text("# Cache\n\nccache stores compiled objects.\n")
    (tmp_path / "ci.md").write_text("# Failure\n\nlibpthread was not linked.\n")
    bound = store.with_embedder(HASHING_EMBEDDER)
    ingest_folder(tmp_path, store=bound, embedder=HashingEmbedder())
    return bound


def test_embed_missing_embeds_every_chunk_for_the_new_model(first_store: StoreProtocol) -> None:
    """Every stored chunk gets the new model's vector, so the new model can search them all."""
    second_store = first_store.with_embedder(SECOND_MODEL)
    second_embedder = HashingEmbedder(SECOND_MODEL)

    embedded = embed_missing(second_store, second_embedder, batch_size=2)

    assert embedded == 3
    assert second_store.get_unembedded_chunks(limit=10) == []
    result = retrieve(
        "ccache compiled objects", embedder=second_embedder, store=second_store, limit=1
    )
    assert result.chunks[0].metadata["source"] == "cache.md"


def test_embed_missing_writes_the_new_models_own_vectors(first_store: StoreProtocol) -> None:
    """Each chunk's new vector is the new model's embedding of that chunk's stored content."""
    second_store = first_store.with_embedder(SECOND_MODEL)
    second_embedder = HashingEmbedder(SECOND_MODEL)
    before = second_store.get_unembedded_chunks(limit=10)

    embed_missing(second_store, second_embedder)

    for row in before:
        expected = second_embedder.embed_documents([row["content"]])[0]
        nearest = second_store.search_dense(expected, limit=1)
        assert nearest[0]["id"] == row["id"]
        assert nearest[0]["distance"] == pytest.approx(0.0, abs=1e-6)


def test_embed_missing_does_nothing_once_every_chunk_is_embedded(
    first_store: StoreProtocol,
) -> None:
    """A second run finds nothing to embed, and the ingesting model has nothing missing at all."""
    second_store = first_store.with_embedder(SECOND_MODEL)
    embed_missing(second_store, HashingEmbedder(SECOND_MODEL))

    assert embed_missing(second_store, HashingEmbedder(SECOND_MODEL)) == 0
    assert embed_missing(first_store, HashingEmbedder()) == 0


def test_embed_missing_refuses_an_embedder_for_another_model(first_store: StoreProtocol) -> None:
    """The embedder must be the store's model, or vectors would land in the wrong column."""
    second_store = first_store.with_embedder(SECOND_MODEL)

    with pytest.raises(ValueError):
        embed_missing(second_store, HashingEmbedder())
    assert len(second_store.get_unembedded_chunks(limit=10)) == 3


@pytest.mark.parametrize("batch_size", [0, -1])
def test_embed_missing_rejects_a_batch_size_below_one(
    first_store: StoreProtocol, batch_size: int
) -> None:
    """A batch must hold at least one chunk."""
    with pytest.raises(ValueError):
        embed_missing(first_store, HashingEmbedder(), batch_size=batch_size)
