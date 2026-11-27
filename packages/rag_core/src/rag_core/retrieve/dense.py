"""Dense retrieval: embed the query, then rank chunks by cosine distance in the store."""

import time
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from rag_core.embed.binding import check_same_model
from rag_core.embed.protocol import EmbedderProtocol
from rag_core.rerank.protocol import RerankerProtocol
from rag_core.store.protocol import StoreProtocol

# Dense-search candidates the reranker rescores when no count is given.
DEFAULT_CANDIDATES = 20


@dataclass(frozen=True)
class RetrievedChunk:
    """One ranked chunk: the stored fields, its cosine distance to the query, and its relevance.

    ``relevance`` is what the ranking used: the cosine similarity (1 minus the distance) for dense
    retrieval, or the reranker's score, from 0 to 1, when the chunk was reranked.
    """

    id: UUID
    document_id: UUID
    content: str
    metadata: dict[str, Any]
    distance: float
    relevance: float


@dataclass(frozen=True)
class RetrievalResult:
    """The ranked chunks for one query, most relevant first, and how long retrieval took.

    ``latency_ms`` covers the whole call; ``rerank_latency_ms`` is the reranking step's share of
    it, 0 when there was no reranker, and ``candidates`` is how many chunks the reranker scored.
    """

    chunks: list[RetrievedChunk]
    latency_ms: float
    rerank_latency_ms: float = 0.0
    # How many dense candidates the reranker scored, after widening to the limit; None without one.
    candidates: int | None = None


def search(
    query: str,
    *,
    embedder: EmbedderProtocol,
    store: StoreProtocol,
    limit: int,
    ef_search: int | None = None,
) -> list[RetrievedChunk]:
    """The first step: embed ``query`` and return the ``limit`` nearest chunks, nearest first.

    Each chunk's relevance is its cosine similarity to the query, 1 minus its distance.
    """
    query_embedding = embedder.embed_query(query)
    rows = store.search_dense(query_embedding, limit=limit, ef_search=ef_search)
    chunks: list[RetrievedChunk] = []
    for row in rows:
        chunks.append(
            RetrievedChunk(
                id=row["id"],
                document_id=row["document_id"],
                content=row["content"],
                metadata=row["metadata"],
                distance=row["distance"],
                relevance=1.0 - row["distance"],
            )
        )
    return chunks


def rerank(
    query: str, chunks: list[RetrievedChunk], *, reranker: RerankerProtocol, limit: int
) -> list[RetrievedChunk]:
    """The second step: rescore ``chunks`` with ``reranker`` and keep the ``limit`` best.

    Each kept chunk's relevance is the reranker's score; its distance is still the dense one.
    Chunks with equal scores keep their order from ``chunks``.
    """
    scores = reranker.score(query, [chunk.content for chunk in chunks])
    scored: list[tuple[float, int, RetrievedChunk]] = []
    for position, (chunk, score) in enumerate(zip(chunks, scores, strict=True)):
        # The position breaks ties, so equal scores keep the dense order and the chunks
        # themselves are never compared.
        scored.append((-score, position, chunk))
    scored.sort()
    reranked: list[RetrievedChunk] = []
    for negative_score, _, chunk in scored[:limit]:
        reranked.append(replace(chunk, relevance=-negative_score))
    return reranked


def retrieve(
    query: str,
    *,
    embedder: EmbedderProtocol,
    store: StoreProtocol,
    limit: int = 5,
    ef_search: int | None = None,
    reranker: RerankerProtocol | None = None,
    candidates: int = DEFAULT_CANDIDATES,
) -> RetrievalResult:
    """Return the ``limit`` most relevant chunks for ``query``, most relevant first, with timings.

    Without a ``reranker``, this is dense search: the ``limit`` chunks nearest to the query. With
    one, dense search fetches ``candidates`` chunks, raised to ``limit`` when smaller, and the
    reranker's scores pick and order the ``limit`` returned.

    ``embedder`` and ``store`` must be bound to the same model, or the query vector would be
    compared with vectors from another model's space; a mismatch raises ``ValueError`` before
    anything is embedded. ``ef_search`` is passed to the store's approximate search. The latency
    covers embedding, searching, and reranking, measured with a monotonic clock.
    """
    check_same_model(embedder, store)
    # The reranker can only return chunks it was given, so fetch at least ``limit`` of them.
    candidates = max(candidates, limit)
    started = time.perf_counter()
    used_candidates = None
    if reranker is None:
        chunks = search(query, embedder=embedder, store=store, limit=limit, ef_search=ef_search)
        rerank_latency_ms = 0.0
    else:
        found = search(query, embedder=embedder, store=store, limit=candidates, ef_search=ef_search)
        rerank_started = time.perf_counter()
        chunks = rerank(query, found, reranker=reranker, limit=limit)
        rerank_latency_ms = (time.perf_counter() - rerank_started) * 1000.0
        used_candidates = candidates
    latency_ms = (time.perf_counter() - started) * 1000.0
    return RetrievalResult(
        chunks=chunks,
        latency_ms=latency_ms,
        rerank_latency_ms=rerank_latency_ms,
        candidates=used_candidates,
    )
