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
# Reciprocal Rank Fusion's constant: a rank-1 result scores 1/61 and rank 10 scores 1/70, so one
# list's top results cannot outweigh agreement between lists. 60 is the value its authors proposed.
RRF_K = 60


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
    # None for a chunk only lexical search found, which has no dense distance.
    distance: float | None
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
    # How many chunks the reranker scored; None without one.
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


def lexical_search(query: str, *, store: StoreProtocol, limit: int) -> list[RetrievedChunk]:
    """The ``limit`` chunks best matching ``query``'s words, with the store's score as relevance.

    These chunks have no dense distance: lexical search compares words, not vectors.
    """
    chunks: list[RetrievedChunk] = []
    for row in store.search_lexical(query, limit=limit):
        chunks.append(
            RetrievedChunk(
                id=row["id"],
                document_id=row["document_id"],
                content=row["content"],
                metadata=row["metadata"],
                distance=None,
                relevance=row["score"],
            )
        )
    return chunks


def fuse(rankings: list[list[RetrievedChunk]], *, limit: int) -> list[RetrievedChunk]:
    """Merge ranked lists by Reciprocal Rank Fusion and keep the ``limit`` best.

    Each chunk scores ``1 / (RRF_K + rank)`` in every list it appears in, with ranks counted from 1,
    and the sums are its fused relevance. Only positions are used, so lists scored on different
    scales, such as cosine distances and ``ts_rank``, never need to be compared. A chunk keeps the
    first dense distance it was found with. Equal sums keep the order of first appearance.
    """
    fused_score: dict[UUID, float] = {}
    first_seen: dict[UUID, int] = {}
    chunk_by_id: dict[UUID, RetrievedChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            fused_score[chunk.id] = fused_score.get(chunk.id, 0.0) + 1.0 / (RRF_K + rank)
            if chunk.id not in first_seen:
                first_seen[chunk.id] = len(first_seen)
            known = chunk_by_id.get(chunk.id)
            if known is None or (known.distance is None and chunk.distance is not None):
                chunk_by_id[chunk.id] = chunk
    ordered: list[tuple[float, int, UUID]] = []
    for chunk_id, score in fused_score.items():
        # Negated so an ascending sort puts the highest score first; first_seen breaks ties.
        ordered.append((-score, first_seen[chunk_id], chunk_id))
    ordered.sort()
    fused: list[RetrievedChunk] = []
    for negative_score, _, chunk_id in ordered[:limit]:
        fused.append(replace(chunk_by_id[chunk_id], relevance=-negative_score))
    return fused


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
    hybrid: bool = False,
) -> RetrievalResult:
    """Return the ``limit`` most relevant chunks for ``query``, most relevant first, with timings.

    Three steps, each optional after the first:

    1. Dense search fetches a pool of chunks: ``limit`` of them, or ``candidates`` (raised to
       ``limit`` when smaller) when there is a reranker to choose among them.
    2. With ``hybrid``, lexical search fetches a pool of the same size, and the two are merged by
       Reciprocal Rank Fusion.
    3. With a ``reranker``, its scores pick and order the ``limit`` returned.

    ``embedder`` and ``store`` must be bound to the same model, or the query vector would be
    compared with vectors from another model's space; a mismatch raises ``ValueError`` before
    anything is embedded. ``ef_search`` is passed to the store's approximate search. The latency
    covers every step, measured with a monotonic clock.
    """
    check_same_model(embedder, store)
    # The reranker can only return chunks it was given, so fetch at least ``limit`` of them.
    candidates = max(candidates, limit)
    pool = limit
    if reranker is not None:
        pool = candidates
    started = time.perf_counter()
    found = search(query, embedder=embedder, store=store, limit=pool, ef_search=ef_search)
    if hybrid:
        lexical = lexical_search(query, store=store, limit=pool)
        found = fuse([found, lexical], limit=pool)
    used_candidates = None
    rerank_latency_ms = 0.0
    if reranker is None:
        chunks = found[:limit]
    else:
        rerank_started = time.perf_counter()
        chunks = rerank(query, found, reranker=reranker, limit=limit)
        rerank_latency_ms = (time.perf_counter() - rerank_started) * 1000.0
        # What the reranker was given, which is fewer than requested when the store holds fewer.
        used_candidates = len(found)
    latency_ms = (time.perf_counter() - started) * 1000.0
    return RetrievalResult(
        chunks=chunks,
        latency_ms=latency_ms,
        rerank_latency_ms=rerank_latency_ms,
        candidates=used_candidates,
    )
