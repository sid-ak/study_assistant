import uuid

import numpy as np
import pytest

from rag_core.config import settings
from rag_core.store import Store

pytestmark = pytest.mark.integration


def test_initialize_schema(store: Store) -> None:
    # Idempotent: running again must not error.
    store.initialize_schema()


def test_document_and_chunks(store: Store) -> None:
    doc_id = uuid.uuid4()
    file_hash = "test-hash-" + str(uuid.uuid4())

    stored_id = store.add_document(id=doc_id, filename="test.md", file_hash=file_hash)
    assert stored_id == doc_id

    doc = store.get_document_by_hash(file_hash)
    assert doc is not None
    assert doc["id"] == doc_id

    chunk_id = uuid.uuid4()
    embedding = np.random.rand(settings.embedding_dimension).tolist()
    store.add_chunks(
        [
            {
                "id": chunk_id,
                "document_id": doc_id,
                "content": "This is a test chunk.",
                "metadata": {"page": 1},
                "embedding": embedding,
            }
        ]
    )

    with store.get_connection() as conn:
        cur = conn.execute("SELECT content, embedding FROM chunks WHERE id = %s", (chunk_id,))
        row = cur.fetchone()
    assert row is not None
    assert row["content"] == "This is a test chunk."
    # Vector column round-trips: register_vector returns a numpy array.
    assert row["embedding"].shape == (settings.embedding_dimension,)
    assert np.allclose(row["embedding"], embedding)


def test_add_document_is_idempotent(store: Store) -> None:
    file_hash = "test-hash-" + str(uuid.uuid4())

    first = store.add_document(id=uuid.uuid4(), filename="a.md", file_hash=file_hash)
    # Same hash, different id + filename: the original row is kept, id is returned.
    second = store.add_document(id=uuid.uuid4(), filename="b.md", file_hash=file_hash)
    assert second == first

    doc = store.get_document_by_hash(file_hash)
    assert doc is not None
    assert doc["id"] == first
    assert doc["filename"] == "b.md"


def test_delete_document_cascades_chunks(store: Store) -> None:
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="test-hash-" + str(uuid.uuid4()))
    store.add_chunks(
        [
            {
                "id": chunk_id,
                "document_id": doc_id,
                "content": "chunk",
                "metadata": {},
                "embedding": np.random.rand(settings.embedding_dimension).tolist(),
            }
        ]
    )

    store.delete_document(doc_id)

    with store.get_connection() as conn:
        assert conn.execute("SELECT 1 FROM documents WHERE id = %s", (doc_id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM chunks WHERE id = %s", (chunk_id,)).fetchone() is None
