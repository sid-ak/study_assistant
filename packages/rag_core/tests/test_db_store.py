"""Integration tests for behavior that only exists on the concrete, DB-backed ``Store``.

Shared CRUD behavior common to every ``StoreProtocol`` implementation lives in the store contract
suite instead, parametrized against both `Store` and `InMemoryStore`. What stays here is genuinely
Store-only: raw vector round-tripping through pgvector and idempotent schema DDL. Neither is
expressible through `StoreProtocol`, which deliberately leaves out `get_connection()`.
"""

import uuid

import numpy as np
import pytest
from psycopg import sql

from rag_core.store import EmbedderNotFoundError, Store
from rag_core.store.embedders import EmbedderInfo
from rag_core.store.schema import embedding_column
from rag_core_testing import make_chunk

pytestmark = pytest.mark.integration


def test_initialize_is_idempotent_against_an_existing_schema(db_store: Store) -> None:
    """initialize runs again over the schema the fixture already created without erroring."""
    db_store.initialize()


def test_document_and_chunks_round_trip_vector(db_store: Store) -> None:
    """A chunk's embedding lands in its model's column and reads back as a numpy array."""
    embedder = db_store.embedder
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


def test_store_bound_to_an_unregistered_model_is_refused(db_store: Store) -> None:
    """A model with no registered column can be neither written nor read, and the error is typed."""
    unregistered = db_store.with_embedder(EmbedderInfo(model_id="never-registered", dimension=4))
    doc_id = uuid.uuid4()
    unregistered.add_document(id=doc_id, filename="d.md", file_hash="h")
    with pytest.raises(EmbedderNotFoundError):
        unregistered.add_chunks([make_chunk(doc_id, 4)])
    with pytest.raises(EmbedderNotFoundError):
        unregistered.get_chunks_by_document(doc_id)


def test_chunk_order_does_not_depend_on_physical_row_order(db_store: Store) -> None:
    """Chunks keep insertion order even after the table is physically re-sorted by id."""
    doc_id = uuid.uuid4()
    db_store.add_document(id=doc_id, filename="d.md", file_hash="h")
    ids = [uuid.UUID(int=n) for n in (50, 40, 30, 20, 10)]
    db_store.add_chunks([make_chunk(doc_id, db_store.embedder.dimension, id=i) for i in ids])

    # CLUSTER rewrites the table in primary-key order, the reverse of insertion order here, so a
    # query without an explicit ORDER BY would return the chunks sorted by id.
    with db_store.get_connection() as conn:
        conn.execute("CLUSTER chunks USING chunks_pkey")

    assert [c["id"] for c in db_store.get_chunks_by_document(doc_id)] == ids
