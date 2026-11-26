"""Dense retrieval: embed the query, then rank chunks by cosine distance in the store."""

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rag_core.embed.protocol import EmbedderProtocol
from rag_core.store.protocol import StoreProtocol


@dataclass(frozen=True)
class RetrievedChunk:
    """One ranked chunk: the stored fields and its cosine distance to the query."""

    id: UUID
    document_id: UUID
    content: str
    metadata: dict[str, Any]
    distance: float


@dataclass(frozen=True)
class RetrievalResult:
    """The ranked chunks for one query, nearest first, and how long retrieval took."""

    chunks: list[RetrievedChunk]
    latency_ms: float


def retrieve(
    query: str,
    *,
    embedder: EmbedderProtocol,
    store: StoreProtocol,
    limit: int = 5,
    ef_search: int | None = None,
) -> RetrievalResult:
    """Return the ``limit`` chunks nearest to ``query``, nearest first, with the time taken.

    ``embedder`` and ``store`` must be bound to the same model, or the query vector would be
    compared with vectors from another model's space; a mismatch raises ``ValueError`` before
    anything is embedded. ``ef_search`` is passed to the store's approximate search. The latency
    covers embedding the query and searching the store, measured with a monotonic clock.
    """
    if embedder.info != store.embedder:
        raise ValueError(
            f"The embedder is {embedder.info.model_id!r} but the store holds vectors for "
            f"{store.embedder.model_id!r}; bind the store with store.with_embedder(embedder.info)."
        )
    started = time.perf_counter()
    query_embedding = embedder.embed_query(query)
    rows = store.search_dense(query_embedding, limit=limit, ef_search=ef_search)
    latency_ms = (time.perf_counter() - started) * 1000.0
    chunks: list[RetrievedChunk] = []
    for row in rows:
        chunks.append(
            RetrievedChunk(
                id=row["id"],
                document_id=row["document_id"],
                content=row["content"],
                metadata=row["metadata"],
                distance=row["distance"],
            )
        )
    return RetrievalResult(chunks=chunks, latency_ms=latency_ms)
