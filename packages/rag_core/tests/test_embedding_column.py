"""Unit tests for ``embedding_column``, which names each embedder's vector column (ADR 0008)."""

import pytest

from rag_core.store.schema import embedding_column


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("bge-m3", "embedding_bge_m3"),
        ("BAAI/bge-m3", "embedding_baai_bge_m3"),
        ("voyage-3.5  lite", "embedding_voyage_3_5_lite"),
    ],
)
def test_embedding_column_is_a_safe_identifier(model_id: str, expected: str) -> None:
    """Model ids map to lowercase, underscore-separated column names under an embedding_ prefix."""
    assert embedding_column(model_id) == expected


@pytest.mark.parametrize("model_id", ["", "///", "x" * 60])
def test_embedding_column_rejects_unusable_ids(model_id: str) -> None:
    """An id with no usable characters, or one past Postgres's 63-byte name limit, is refused."""
    with pytest.raises(ValueError):
        embedding_column(model_id)
