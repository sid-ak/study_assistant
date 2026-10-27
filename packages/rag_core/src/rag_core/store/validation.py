"""Checks every ``StoreProtocol`` implementation runs before writing chunks, so all fail alike."""

from collections.abc import Sequence
from typing import Any

from rag_core.store.embedders.protocol import EmbedderInfo
from rag_core.store.errors import EmbedderNotFoundError, EmbeddingDimensionError


def require_current(embedder: EmbedderInfo | None) -> EmbedderInfo:
    """Return ``embedder``, or raise ``EmbedderNotFoundError`` if no embedder is current."""
    if embedder is None:
        raise EmbedderNotFoundError("No current embedder; register one and set it current first.")
    return embedder


def check_dimensions(chunks: Sequence[dict[str, Any]], embedder: EmbedderInfo) -> None:
    """Raise ``EmbeddingDimensionError`` unless every embedding is ``embedder.dimension`` long."""
    for chunk in chunks:
        if len(chunk["embedding"]) != embedder.dimension:
            raise EmbeddingDimensionError(
                f"Chunk {chunk['id']} has a {len(chunk['embedding'])}-dimension embedding; "
                f"{embedder.model_id!r} expects {embedder.dimension}."
            )
