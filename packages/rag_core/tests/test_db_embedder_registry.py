"""Integration tests for what only the DB-backed ``EmbedderRegistry`` does: provisioning storage.

Registering a model adds that model's own ``vector(N)`` column and HNSW index to ``chunks`` (ADR
0008). The registry behavior every implementation shares lives in ``test_embedder_registry.py``.
"""

import pytest

from rag_core.store.connection import connect
from rag_core.store.embedders import EmbedderRegistry
from rag_core.store.schema import embedding_column

from support import EMBEDDER_A, EMBEDDER_B

pytestmark = pytest.mark.integration


def test_register_adds_a_vector_column_and_hnsw_index(
    db_embedder_registry: EmbedderRegistry,
) -> None:
    """Registering a model adds its own vector(N) column and HNSW index to chunks."""
    db_embedder_registry.register(EMBEDDER_A.model_id, EMBEDDER_A.dimension)
    column = embedding_column(EMBEDDER_A.model_id)

    with connect(db_embedder_registry.database_url) as conn:
        col = conn.execute(
            "SELECT format_type(a.atttypid, a.atttypmod) AS type FROM pg_attribute a "
            "WHERE a.attrelid = 'chunks'::regclass AND a.attname = %s AND NOT a.attisdropped",
            (column,),
        ).fetchone()
        indexes = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'chunks' AND indexdef LIKE %s",
            (f"%({column} vector_cosine_ops)%",),
        ).fetchall()
    assert col is not None
    assert col["type"] == f"vector({EMBEDDER_A.dimension})"
    assert len(indexes) == 1
    assert "USING hnsw" in indexes[0]["indexdef"]


def test_registered_embedders_are_independent_columns(
    db_embedder_registry: EmbedderRegistry,
) -> None:
    """Two registered models coexist as two columns, each keeping its own dimension."""
    for info in (EMBEDDER_A, EMBEDDER_B):
        db_embedder_registry.register(info.model_id, info.dimension)

    with connect(db_embedder_registry.database_url) as conn:
        rows = conn.execute(
            "SELECT attname, format_type(atttypid, atttypmod) AS type FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname LIKE 'embedding%%' "
            "AND NOT attisdropped"
        ).fetchall()
    assert {r["attname"]: r["type"] for r in rows} == {
        embedding_column(info.model_id): f"vector({info.dimension})"
        for info in (EMBEDDER_A, EMBEDDER_B)
    }
