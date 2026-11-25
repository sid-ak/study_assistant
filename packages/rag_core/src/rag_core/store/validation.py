"""Checks every store and registry implementation runs before writing, so all fail alike."""

from collections.abc import Sequence
from typing import Any

from rag_core.store.embedders.protocol import EmbedderInfo
from rag_core.store.errors import EmbeddingDimensionError, UnsupportedDimensionError

# The largest vector dimension the store can index for similarity search.
MAX_EMBEDDING_DIMENSION = 2000


def check_dimensions(chunks: Sequence[dict[str, Any]], embedder: EmbedderInfo) -> None:
    """Raise ``EmbeddingDimensionError`` unless every embedding is ``embedder.dimension`` long."""
    for chunk in chunks:
        if len(chunk["embedding"]) != embedder.dimension:
            raise EmbeddingDimensionError(
                f"Chunk {chunk['id']} has a {len(chunk['embedding'])}-dimension embedding; "
                f"{embedder.model_id!r} expects {embedder.dimension}."
            )


def check_embedder_dimension(model_id: str, dimension: int) -> None:
    """Raise ``UnsupportedDimensionError`` unless ``dimension`` is 1 to MAX_EMBEDDING_DIMENSION."""
    if dimension < 1 or dimension > MAX_EMBEDDING_DIMENSION:
        raise UnsupportedDimensionError(
            f"{model_id!r} has dimension {dimension}; "
            f"supported dimensions are 1 to {MAX_EMBEDDING_DIMENSION}."
        )
