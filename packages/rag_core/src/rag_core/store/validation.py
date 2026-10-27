"""Checks every ``StoreProtocol`` implementation runs before writing chunks, so all fail alike."""

from collections.abc import Sequence
from typing import Any

from rag_core.store.embedders.protocol import EmbedderInfo
from rag_core.store.errors import EmbeddingDimensionError


def check_dimensions(chunks: Sequence[dict[str, Any]], embedder: EmbedderInfo) -> None:
    """Raise ``EmbeddingDimensionError`` unless every embedding is ``embedder.dimension`` long."""
    for chunk in chunks:
        if len(chunk["embedding"]) != embedder.dimension:
            raise EmbeddingDimensionError(
                f"Chunk {chunk['id']} has a {len(chunk['embedding'])}-dimension embedding; "
                f"{embedder.model_id!r} expects {embedder.dimension}."
            )
