"""Behavior of ``retrieve``, the dense retrieval entry point.

Each test runs against both stores through the ``store`` fixture, with ``HashingEmbedder`` standing
in for the model, so the whole path from query text to ranked chunks is exercised without one.
"""

import time
import uuid
from typing import Any

import pytest

from rag_core.config import Settings
from rag_core.rerank import build_reranker
from rag_core.retrieve import (
    RetrievalResult,
    RetrievedChunk,
    fuse,
    lexical_search,
    rerank,
    retrieve,
    search,
)
from rag_core.store import StoreProtocol
from rag_core.store.embedders import EmbedderInfo, EmbedderRegistryProtocol
from rag_core_testing import HASHING_EMBEDDER, HashingEmbedder, InMemoryStore

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
    distances: list[float] = []
    for chunk in result.chunks:
        # Dense results always carry a distance; only lexical-only chunks have none.
        assert chunk.distance is not None
        distances.append(chunk.distance)
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


class ScriptedReranker:
    """A reranker that scores each document from a prepared table and records each call."""

    def __init__(self, scores: dict[str, float], delay: float = 0.0) -> None:
        """Score a document by ``scores[document]``, 0 when absent, after ``delay`` seconds."""
        self.scores = scores
        self.delay = delay
        self.calls: list[tuple[str, list[str]]] = []

    @property
    def model_id(self) -> str:
        """The fake model's name."""
        return "test/scripted-reranker"

    def score(self, query: str, documents: list[str]) -> list[float]:
        """Record the call and return each document's prepared score."""
        self.calls.append((query, list(documents)))
        time.sleep(self.delay)
        return [self.scores.get(document, 0.0) for document in documents]


def test_without_a_reranker_relevance_is_the_cosine_similarity(
    hashing_store: StoreProtocol,
) -> None:
    """Dense results carry relevance 1 minus distance, and no reranking time."""
    result = retrieve("asan bazel", embedder=HashingEmbedder(), store=hashing_store, limit=3)

    for chunk in result.chunks:
        assert chunk.distance is not None
        assert chunk.relevance == pytest.approx(1.0 - chunk.distance)
    assert result.rerank_latency_ms == 0.0
    assert result.candidates is None


def test_a_reranker_rescores_the_candidates_and_keeps_the_top_limit(
    hashing_store: StoreProtocol,
) -> None:
    """Dense search fetches the candidates; the reranker's order and scores decide the result."""
    reranker = ScriptedReranker({DOCUMENTS[2]: 0.9, DOCUMENTS[1]: 0.6, DOCUMENTS[0]: 0.1})

    result = retrieve(
        "asan bazel",
        embedder=HashingEmbedder(),
        store=hashing_store,
        limit=2,
        reranker=reranker,
        candidates=3,
    )

    assert [chunk.content for chunk in result.chunks] == [DOCUMENTS[2], DOCUMENTS[1]]
    assert [chunk.relevance for chunk in result.chunks] == [0.9, 0.6]
    [(query, documents)] = reranker.calls
    assert query == "asan bazel"
    assert sorted(documents) == sorted(DOCUMENTS)


def test_reranking_time_is_measured_and_included_in_the_total(
    hashing_store: StoreProtocol,
) -> None:
    """The reranking step is timed on its own and counted in the total latency."""
    reranker = ScriptedReranker({}, delay=0.02)

    result = retrieve(
        "asan", embedder=HashingEmbedder(), store=hashing_store, limit=1, reranker=reranker
    )

    assert result.rerank_latency_ms >= 20.0
    assert result.latency_ms >= result.rerank_latency_ms


def test_fewer_candidates_than_results_are_widened_to_the_limit(
    hashing_store: StoreProtocol,
) -> None:
    """The reranker can only return chunks it was given, so candidates grow to cover the limit."""
    reranker = ScriptedReranker({})

    result = retrieve(
        "asan",
        embedder=HashingEmbedder(),
        store=hashing_store,
        limit=3,
        reranker=reranker,
        candidates=2,
    )

    assert len(result.chunks) == 3
    assert len(reranker.calls[0][1]) == 3
    assert result.candidates == 3


def test_search_and_rerank_are_separate_steps(hashing_store: StoreProtocol) -> None:
    """``search`` returns the dense ranking; ``rerank`` reorders any list of chunks it is given."""
    dense = search("asan bazel", embedder=HashingEmbedder(), store=hashing_store, limit=3)
    reranker = ScriptedReranker({DOCUMENTS[1]: 0.8})

    reranked = rerank("asan bazel", dense, reranker=reranker, limit=1)

    assert len(dense) == 3
    assert [chunk.content for chunk in reranked] == [DOCUMENTS[1]]
    original = {}
    for chunk in dense:
        original[chunk.content] = chunk.distance
    assert reranked[0].distance == original[DOCUMENTS[1]]


def test_build_reranker_follows_the_setting() -> None:
    """``RERANK_ENABLED`` decides whether retrieval gets a reranker at all."""
    assert build_reranker(Settings(rerank_enabled=False)) is None
    reranker = build_reranker(Settings(rerank_enabled=True))
    assert reranker is not None
    assert reranker.model_id == "jinaai/jina-reranker-v1-tiny-en"


def chunk_for(text: str, distance: float | None, relevance: float) -> RetrievedChunk:
    """A retrieved chunk for ``text`` with an id derived from it, so equal texts share an id."""
    return RetrievedChunk(
        id=uuid.uuid5(uuid.NAMESPACE_URL, text),
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, "doc"),
        content=text,
        metadata={"source": "notes.md"},
        distance=distance,
        relevance=relevance,
    )


def test_fuse_adds_reciprocal_ranks_across_lists() -> None:
    """Each chunk scores 1 / (60 + rank) in every list it is in; the sums decide the order."""
    a = chunk_for("a", 0.1, 0.9)
    b = chunk_for("b", 0.2, 0.8)
    c = chunk_for("c", 0.3, 0.7)
    c_lexical = chunk_for("c", None, 2.0)
    a_lexical = chunk_for("a", None, 1.0)

    fused = fuse([[a, b, c], [c_lexical, a_lexical]], limit=3)

    assert [chunk.content for chunk in fused] == ["a", "c", "b"]
    assert fused[0].relevance == pytest.approx(1 / 61 + 1 / 62)
    assert fused[1].relevance == pytest.approx(1 / 63 + 1 / 61)
    assert fused[2].relevance == pytest.approx(1 / 62)


def test_fuse_keeps_the_dense_distance_when_a_chunk_has_one() -> None:
    """A chunk found by both searches keeps its distance; one found only by words has none."""
    dense = [chunk_for("a", 0.1, 0.9)]
    lexical = [chunk_for("a", None, 1.0), chunk_for("z", None, 0.5)]

    fused = fuse([dense, lexical], limit=2)

    distances = {}
    for chunk in fused:
        distances[chunk.content] = chunk.distance
    assert distances == {"a": 0.1, "z": None}


def test_fuse_breaks_ties_by_first_appearance() -> None:
    """Equal fused scores keep the order of the lists, then the ranks, they first appeared in."""
    fused = fuse([[chunk_for("x", 0.1, 0.9)], [chunk_for("z", None, 1.0)]], limit=2)

    assert [chunk.content for chunk in fused] == ["x", "z"]


class LexicalStubStore(InMemoryStore):
    """An in-memory store whose lexical search returns prepared rows, whatever the query."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """Answer every lexical search with ``rows``."""
        super().__init__(embedder=HASHING_EMBEDDER)
        self.rows = rows
        self.lexical_queries: list[str] = []

    def search_lexical(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Record the query and return the prepared rows, at most ``limit``."""
        self.lexical_queries.append(query)
        return self.rows[:limit]


@pytest.fixture
def hybrid_store() -> LexicalStubStore:
    """Three stored chunks; lexical search always returns only the third, the release note."""
    store = LexicalStubStore([])
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="notes.md", file_hash="notes")
    vectors = HashingEmbedder().embed_documents(DOCUMENTS)
    rows = []
    for index, (text, vector) in enumerate(zip(DOCUMENTS, vectors, strict=True)):
        rows.append(
            {
                "id": uuid.uuid4(),
                "document_id": doc_id,
                "content": text,
                "metadata": {"source": "notes.md", "chunk_index": index},
                "embedding": vector,
            }
        )
    store.add_chunks(rows)
    release = rows[2]
    store.rows = [
        {
            "id": release["id"],
            "document_id": doc_id,
            "content": release["content"],
            "metadata": release["metadata"],
            "score": 0.5,
        }
    ]
    return store


def test_hybrid_retrieval_adds_what_only_lexical_search_found(
    hybrid_store: LexicalStubStore,
) -> None:
    """With hybrid on, a chunk dense search ranked out of the list is fused back in."""
    dense_only = retrieve(
        "bazel asan cmake", embedder=HashingEmbedder(), store=hybrid_store, limit=2
    )
    hybrid = retrieve(
        "bazel asan cmake", embedder=HashingEmbedder(), store=hybrid_store, limit=2, hybrid=True
    )

    assert DOCUMENTS[2] not in [chunk.content for chunk in dense_only.chunks]
    assert DOCUMENTS[2] in [chunk.content for chunk in hybrid.chunks]
    assert hybrid_store.lexical_queries == ["bazel asan cmake"]


def test_hybrid_retrieval_hands_the_fused_list_to_the_reranker(
    hybrid_store: LexicalStubStore,
) -> None:
    """Fusion sits between search and reranking: the reranker scores the fused candidates."""
    reranker = ScriptedReranker({DOCUMENTS[2]: 0.95})

    result = retrieve(
        "bazel asan cmake",
        embedder=HashingEmbedder(),
        store=hybrid_store,
        limit=1,
        reranker=reranker,
        candidates=2,
        hybrid=True,
    )

    assert DOCUMENTS[2] in reranker.calls[0][1]
    assert [chunk.content for chunk in result.chunks] == [DOCUMENTS[2]]
    assert result.chunks[0].relevance == 0.95


def test_lexical_search_returns_retrieved_chunks_without_a_distance(
    hybrid_store: LexicalStubStore,
) -> None:
    """The lexical step's chunks carry the store's score as relevance and no dense distance."""
    [chunk] = lexical_search("anything", store=hybrid_store, limit=5)

    assert chunk.content == DOCUMENTS[2]
    assert chunk.distance is None
    assert chunk.relevance == 0.5


def test_candidates_counts_the_chunks_actually_reranked(hashing_store: StoreProtocol) -> None:
    """A store holding fewer chunks than requested reports how many the reranker really scored."""
    result = retrieve(
        "asan",
        embedder=HashingEmbedder(),
        store=hashing_store,
        limit=1,
        reranker=ScriptedReranker({}),
        candidates=20,
    )

    assert result.candidates == len(DOCUMENTS)
