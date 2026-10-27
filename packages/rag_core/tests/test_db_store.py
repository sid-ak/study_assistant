"""Integration tests for behavior that only exists on the concrete, DB-backed ``Store``.

Shared CRUD behavior common to every ``StoreProtocol`` implementation lives in
`test_store.py` instead, parametrized against both `Store` and `InMemoryStore`. What stays
here is genuinely Store-only: raw vector round-tripping through pgvector, idempotent schema DDL,
and the per-model columns and indexes that ``register_embedder`` adds. None of these is expressible
through `StoreProtocol` (`get_connection()` is deliberately absent from it — see
`rag_core/AGENTS.md`).
"""

import uuid

import numpy as np
import pytest
from psycopg import sql
from support import EMBEDDER_A, EMBEDDER_B, make_chunk

from rag_core.store import Store
from rag_core.store.schema import embedding_column

pytestmark = pytest.mark.integration


def test_initialize_schema(db_store: Store) -> None:
    """initialize_schema is idempotent — a second run against an existing schema must not error."""
    db_store.initialize_schema()


def test_document_and_chunks_round_trip_vector(db_store: Store) -> None:
    """A chunk's embedding lands in its model's column and reads back as a numpy array."""
    embedder = EMBEDDER_A
    db_store.register_embedder(embedder.model_id, embedder.dimension)
    db_store.set_current_embedder(embedder.model_id)
    doc_id = uuid.uuid4()
    file_hash = "test-hash-" + str(uuid.uuid4())

    stored_id = db_store.add_document(id=doc_id, filename="test.md", file_hash=file_hash)
    assert stored_id == doc_id

    embedding = np.random.rand(embedder.dimension).tolist()
    chunk = make_chunk(doc_id, embedder.dimension, embedding=embedding)
    db_store.add_chunks([chunk])

    column = sql.Identifier(embedding_column(embedder.model_id))
    with db_store.get_connection() as conn:
        query = sql.SQL("SELECT {} AS embedding FROM chunks WHERE id = %s").format(column)
        row = conn.execute(query, (chunk["id"],)).fetchone()
    assert row is not None
    assert row["embedding"].shape == (embedder.dimension,)
    assert np.allclose(row["embedding"], embedding)


def test_register_embedder_adds_a_vector_column_and_hnsw_index(db_store: Store) -> None:
    """Registering a model adds its own vector(N) column and HNSW index to chunks."""
    db_store.register_embedder(EMBEDDER_A.model_id, EMBEDDER_A.dimension)
    column = embedding_column(EMBEDDER_A.model_id)

    with db_store.get_connection() as conn:
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


def test_registered_embedders_are_independent_columns(db_store: Store) -> None:
    """Two registered models coexist as two columns, each keeping its own dimension."""
    for info in (EMBEDDER_A, EMBEDDER_B):
        db_store.register_embedder(info.model_id, info.dimension)

    with db_store.get_connection() as conn:
        rows = conn.execute(
            "SELECT attname, format_type(atttypid, atttypmod) AS type FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname LIKE 'embedding%%' "
            "AND NOT attisdropped"
        ).fetchall()
    assert {r["attname"]: r["type"] for r in rows} == {
        embedding_column(info.model_id): f"vector({info.dimension})"
        for info in (EMBEDDER_A, EMBEDDER_B)
    }
