"""Integration tests for behavior that only exists on the concrete, DB-backed ``Store``.

Shared CRUD behavior common to every ``StoreProtocol`` implementation lives in
`test_store.py` instead, parametrized against both `Store` and `InMemoryStore`. What stays
here is genuinely Store-only: raw vector round-tripping through pgvector and idempotent schema DDL.
Neither is expressible through `StoreProtocol` (`get_connection()` is deliberately absent from it
— see `rag_core/AGENTS.md`).
"""

import uuid

import numpy as np
import pytest
from psycopg import sql

from rag_core.store import Store
from rag_core.store.embedders import EmbedderRegistry
from rag_core.store.schema import embedding_column

from support import EMBEDDER_A, make_chunk

pytestmark = pytest.mark.integration


def test_initialize_is_idempotent_against_an_existing_schema(db_store: Store) -> None:
    """initialize runs again over the schema the fixture already created without erroring."""
    db_store.initialize()


def test_document_and_chunks_round_trip_vector(
    db_store: Store, db_embedder_registry: EmbedderRegistry
) -> None:
    """A chunk's embedding lands in its model's column and reads back as a numpy array."""
    embedder = EMBEDDER_A
    db_embedder_registry.register(embedder.model_id, embedder.dimension)
    db_embedder_registry.set_current(embedder.model_id)
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
