"""Integration tests for behavior that only exists on the concrete, DB-backed ``Store``.

Shared CRUD behavior common to every ``StoreProtocol`` implementation lives in
`test_store.py` instead, parametrized against both `Store` and `InMemoryStore`. What stays
here is genuinely Store-only: raw vector round-tripping through pgvector and idempotent schema DDL,
neither of which is expressible through `StoreProtocol` (`get_connection()` is deliberately absent
from it — see `rag_core/AGENTS.md`).
"""

import uuid

import numpy as np
import pytest

from rag_core.config import settings
from rag_core.store import Store

pytestmark = pytest.mark.integration


def test_initialize_schema(db_store: Store) -> None:
    """initialize_schema is idempotent — a second run against an existing schema must not error."""
    db_store.initialize_schema()


def test_document_and_chunks_round_trip_vector(db_store: Store) -> None:
    """A chunk's embedding round-trips through pgvector and reads back as a numpy array."""
    doc_id = uuid.uuid4()
    file_hash = "test-hash-" + str(uuid.uuid4())
    content = "This is a test chunk."

    stored_id = db_store.add_document(id=doc_id, filename="test.md", file_hash=file_hash)
    assert stored_id == doc_id

    doc = db_store.get_document_by_hash(file_hash)
    assert doc is not None
    assert doc["id"] == doc_id

    chunk_id = uuid.uuid4()
    embedding = np.random.rand(settings.embedding_dimension).tolist()
    db_store.add_chunks(
        [
            {
                "id": chunk_id,
                "document_id": doc_id,
                "content": content,
                "metadata": {"page": 1},
                "embedding": embedding,
            }
        ]
    )

    with db_store.get_connection() as conn:
        cur = conn.execute("SELECT content, embedding FROM chunks WHERE id = %s", (chunk_id,))
        row = cur.fetchone()
    assert row is not None
    assert row["content"] == content
    assert row["embedding"].shape == (settings.embedding_dimension,)
    assert np.allclose(row["embedding"], embedding)
