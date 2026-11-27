"""Checks every store and registry implementation runs before writing or searching.

Both stores call these, so they fail alike.
"""

from collections.abc import Sequence
from typing import Any

from rag_core.store.embedders.protocol import EmbedderInfo
from rag_core.store.errors import (
    DuplicateIdError,
    EmbeddingDimensionError,
    UnsupportedDimensionError,
    ZeroEmbeddingError,
)

# The largest vector dimension the store can index for similarity search.
MAX_EMBEDDING_DIMENSION = 2000
# The largest candidate-list size an approximate search accepts.
MAX_EF_SEARCH = 1000


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


def check_search(
    query_embedding: Sequence[float],
    limit: int,
    embedder: EmbedderInfo,
    ef_search: int | None = None,
) -> None:
    """Raise unless the search arguments are valid for ``embedder``.

    ``limit`` must be at least one and ``query_embedding`` must fit ``embedder``. ``ef_search``, if
    given, must be 1 to ``MAX_EF_SEARCH`` and at least ``limit``, because an approximate search
    returns no more results than the candidates it keeps.
    """
    check_limit(limit)
    if ef_search is not None:
        if ef_search < 1 or ef_search > MAX_EF_SEARCH:
            raise ValueError(f"ef_search must be 1 to {MAX_EF_SEARCH}, not {ef_search}.")
        if ef_search < limit:
            raise ValueError(
                f"ef_search ({ef_search}) must be at least limit ({limit}), "
                "or the search returns fewer results than asked for."
            )
    check_embedding(query_embedding, embedder, "The query")


def check_limit(limit: int) -> None:
    """Raise ``ValueError`` unless ``limit``, a most-rows-to-return count, is at least one."""
    if limit < 1:
        raise ValueError(f"limit must be at least 1, not {limit}.")


def check_unique_ids(rows: Sequence[dict[str, Any]]) -> None:
    """Raise ``DuplicateIdError`` if two of ``rows`` share an ``id``."""
    seen: set[Any] = set()
    for row in rows:
        if row["id"] in seen:
            raise DuplicateIdError(f"Id {row['id']} appears more than once in the batch.")
        seen.add(row["id"])


def check_embedder_dimension(model_id: str, dimension: int) -> None:
    """Raise ``UnsupportedDimensionError`` unless ``dimension`` is 1 to MAX_EMBEDDING_DIMENSION."""
    if dimension < 1 or dimension > MAX_EMBEDDING_DIMENSION:
        raise UnsupportedDimensionError(
            f"{model_id!r} has dimension {dimension}; "
            f"supported dimensions are 1 to {MAX_EMBEDDING_DIMENSION}."
        )
