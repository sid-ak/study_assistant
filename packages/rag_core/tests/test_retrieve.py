"""Behavior of ``retrieve``, the dense retrieval entry point.

Each test runs against both stores through the ``store`` fixture, with ``HashingEmbedder`` standing
in for the model, so the whole path from query text to ranked chunks is exercised without one.
"""

import time
import uuid

import pytest

from rag_core.retrieve import RetrievalResult, RetrievedChunk, retrieve
from rag_core.store import StoreProtocol
from rag_core.store.embedders import EmbedderInfo, EmbedderRegistryProtocol
from rag_core_testing import HASHING_EMBEDDER, HashingEmbedder

DOCUMENTS = [
    "Bazel: pass --config=asan to build and test with AddressSanitizer.",
    "CMake: set CMAKE_BUILD_TYPE to Release for an optimized build.",
    "Release 4.2 notes: the ingest command skips unchanged files.",
]


class RecordingEmbedder(HashingEmbedder):
    """Hashing embedder that records each query it embeds and takes ``delay`` seconds to do so."""

    def __init__(self, delay: float = 0.0) -> None:
        """Start with no recorded queries."""
        super().__init__()
        self.delay = delay
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        """Record ``text``, wait ``delay`` seconds, then embed it as the hashing fake does."""
        self.queries.append(text)
        time.sleep(self.delay)
        return super().embed_query(text)


@pytest.fixture
def hashing_store(
    store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol
) -> StoreProtocol:
    """A store bound to the hashing embedder's model, holding one chunk per ``DOCUMENTS`` entry."""
    embedder_registry.register(HASHING_EMBEDDER.model_id, HASHING_EMBEDDER.dimension)
    bound = store.with_embedder(HASHING_EMBEDDER)
    doc_id = uuid.uuid4()
    bound.add_document(id=doc_id, filename="notes.md", file_hash="notes")
    vectors = HashingEmbedder().embed_documents(DOCUMENTS)
    chunks = []
    for index, (text, vector) in enumerate(zip(DOCUMENTS, vectors, strict=True)):
        chunks.append(
            {
                "id": uuid.uuid4(),
                "document_id": doc_id,
                "content": text,
                "metadata": {"source": "notes.md", "chunk_index": index},
                "embedding": vector,
            }
        )
    bound.add_chunks(chunks)
    return bound


def test_the_chunk_about_the_query_ranks_first(hashing_store: StoreProtocol) -> None:
    """The chunk sharing the query's topic comes back first."""
    result = retrieve(
        "Which Bazel flag turns on AddressSanitizer?",
        embedder=HashingEmbedder(),
        store=hashing_store,
    )
    assert result.chunks[0].content == DOCUMENTS[0]


def test_results_carry_the_chunk_and_its_distance(hashing_store: StoreProtocol) -> None:
    """Each result is a ``RetrievedChunk`` with the stored fields and a cosine distance."""
    result = retrieve("CMake release build", embedder=HashingEmbedder(), store=hashing_store)
    top = result.chunks[0]
    assert isinstance(result, RetrievalResult)
    assert isinstance(top, RetrievedChunk)
    assert top.content == DOCUMENTS[1]
    assert top.metadata == {"source": "notes.md", "chunk_index": 1}
    assert isinstance(top.id, uuid.UUID)
    assert isinstance(top.document_id, uuid.UUID)
    distances = [chunk.distance for chunk in result.chunks]
    assert distances == sorted(distances)
    assert 0.0 <= distances[0] <= 2.0


def test_limit_caps_the_results(hashing_store: StoreProtocol) -> None:
    """At most ``limit`` chunks are returned, and the default is five."""
    limited = retrieve("build", embedder=HashingEmbedder(), store=hashing_store, limit=2)
    default = retrieve("build", embedder=HashingEmbedder(), store=hashing_store)
    assert len(limited.chunks) == 2
    assert len(default.chunks) == len(DOCUMENTS)


def test_ef_search_is_passed_to_the_store(hashing_store: StoreProtocol) -> None:
    """``ef_search`` reaches the store, which refuses one smaller than the limit."""
    accepted = retrieve(
        "build", embedder=HashingEmbedder(), store=hashing_store, limit=2, ef_search=40
    )
    assert len(accepted.chunks) == 2
    with pytest.raises(ValueError, match="ef_search"):
        retrieve("build", embedder=HashingEmbedder(), store=hashing_store, limit=2, ef_search=1)


def test_the_query_is_embedded_as_a_query(hashing_store: StoreProtocol) -> None:
    """The query text goes through ``embed_query``, once, unchanged."""
    embedder = RecordingEmbedder()
    retrieve("remote cache", embedder=embedder, store=hashing_store)
    assert embedder.queries == ["remote cache"]


def test_latency_covers_embedding_and_search(hashing_store: StoreProtocol) -> None:
    """``latency_ms`` includes the time spent embedding the query."""
    result = retrieve("build", embedder=RecordingEmbedder(delay=0.05), store=hashing_store)
    assert result.latency_ms >= 50.0


def test_an_embedder_for_another_model_is_refused(hashing_store: StoreProtocol) -> None:
    """Retrieval refuses an embedder whose model differs from the store's, before embedding."""
    other = HashingEmbedder(EmbedderInfo(model_id="test/other-model", dimension=64))
    with pytest.raises(ValueError, match="test/other-model"):
        retrieve("build", embedder=other, store=hashing_store)
