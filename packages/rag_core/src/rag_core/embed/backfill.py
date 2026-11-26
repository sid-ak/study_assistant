"""Embedding stored chunks with a model registered after they were ingested."""

from typing import Any

from rag_core.embed.binding import check_same_model
from rag_core.embed.protocol import EmbedderProtocol
from rag_core.store.protocol import StoreProtocol

# Chunks embedded per call to the model, matching the batch size ingestion embeds with.
DEFAULT_BATCH_SIZE = 32


def embed_missing(
    store: StoreProtocol, embedder: EmbedderProtocol, *, batch_size: int = DEFAULT_BATCH_SIZE
) -> int:
    """Embed every stored chunk that ``store``'s model has no vector for, and return how many.

    ``embedder`` must be the model ``store`` is bound to, or ``ValueError`` is raised before
    anything is read. Chunks are embedded ``batch_size`` at a time, from their stored content, so
    the new vectors encode the same text the ingesting model's do. Raises ``ValueError`` if
    ``batch_size`` is below one.
    """
    check_same_model(embedder, store)
    if batch_size < 1:
        raise ValueError(f"batch_size must be at least 1, not {batch_size}.")
    embedded = 0
    while True:
        # Each pass asks again for chunks still missing a vector, so the loop ends once the
        # previous pass's vectors are stored and nothing is left.
        rows = store.get_unembedded_chunks(limit=batch_size)
        if not rows:
            return embedded
        texts = [row["content"] for row in rows]
        vectors = embedder.embed_documents(texts)
        updates: list[dict[str, Any]] = []
        for row, vector in zip(rows, vectors, strict=True):
            updates.append({"id": row["id"], "embedding": vector})
        store.set_embeddings(updates)
        embedded += len(updates)
