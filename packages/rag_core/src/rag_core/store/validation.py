"""Checks every store and registry implementation runs before writing or searching.

Both stores call these, so they fail alike.
"""

from collections.abc import Sequence
from typing import Any

from rag_core.store.embedders.protocol import EmbedderInfo
from rag_core.store.errors import (
    EmbeddingDimensionError,
    UnsupportedDimensionError,
    ZeroEmbeddingError,
)

# The largest vector dimension the store can index for similarity search.
MAX_EMBEDDING_DIMENSION = 2000


def check_embedding(embedding: Sequence[float], embedder: EmbedderInfo, label: str) -> None:
    """Raise unless ``embedding`` is ``embedder.dimension`` long and not all zeros.

    ``label`` names the embedding in the error message, such as ``"Chunk <id>"`` or ``"The query"``.
    Raises ``EmbeddingDimensionError`` for a wrong length and ``ZeroEmbeddingError`` for all zeros.
    """
    if len(embedding) != embedder.dimension:
        raise EmbeddingDimensionError(
            f"{label} has a {len(embedding)}-dimension embedding; "
            f"{embedder.model_id!r} expects {embedder.dimension}."
        )
    for value in embedding:
        if value != 0.0:
            return
    raise ZeroEmbeddingError(f"{label} has an all-zero embedding, which has no direction.")


def check_dimensions(chunks: Sequence[dict[str, Any]], embedder: EmbedderInfo) -> None:
    """Raise unless every chunk's embedding is ``embedder.dimension`` long and not all zeros."""
    for chunk in chunks:
        check_embedding(chunk["embedding"], embedder, f"Chunk {chunk['id']}")


def check_search(query_embedding: Sequence[float], limit: int, embedder: EmbedderInfo) -> None:
    """Raise unless ``limit`` is at least one and ``query_embedding`` fits ``embedder``."""
    if limit < 1:
        raise ValueError(f"limit must be at least 1, not {limit}.")
    check_embedding(query_embedding, embedder, "The query")


def check_embedder_dimension(model_id: str, dimension: int) -> None:
    """Raise ``UnsupportedDimensionError`` unless ``dimension`` is 1 to MAX_EMBEDDING_DIMENSION."""
    if dimension < 1 or dimension > MAX_EMBEDDING_DIMENSION:
        raise UnsupportedDimensionError(
            f"{model_id!r} has dimension {dimension}; "
            f"supported dimensions are 1 to {MAX_EMBEDDING_DIMENSION}."
        )
