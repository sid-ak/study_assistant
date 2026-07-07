"""Shared behavior contract for the store seam.

Every test here takes `store: StoreProtocol` (the parametrized fixture in `conftest.py`) and
runs once against `InMemoryStore` and once against the real, DB-backed `Store` — labeled
`[memory]` / `[db]` in test output. This is deliberate: `add_document`, `add_chunks`, and the rest
of `StoreProtocol` must behave identically regardless of which implementation is behind it, and a
single shared assertion can't silently drift out of sync the way two hand-duplicated copies could.

Only `StoreProtocol` methods are used here — nothing peeks at implementation internals (no
`get_connection()`, no reaching into `InMemoryStore.chunks`). Behavior that genuinely can't be
expressed through the Protocol (raw vector round-tripping, schema DDL idempotency) stays in
`test_db_store.py` against the concrete `Store`.
"""

import uuid

from rag_core.config import settings
from rag_core.store import InMemoryStore, Store, StoreProtocol


def test_add_document_returns_stored_id(store: StoreProtocol) -> None:
    """A fresh insert returns the id it was given."""
    doc_id = uuid.uuid4()
    stored_id = store.add_document(id=doc_id, filename="a.md", file_hash="h1")
    assert stored_id == doc_id


def test_add_document_is_idempotent_by_hash(store: StoreProtocol) -> None:
    """Re-adding the same file_hash keeps the original id and refreshes the filename."""
    first = store.add_document(id=uuid.uuid4(), filename="a.md", file_hash="dup")
    second = store.add_document(id=uuid.uuid4(), filename="b.md", file_hash="dup")
    assert second == first

    doc = store.get_document_by_hash("dup")
    assert doc is not None
    assert doc["id"] == first
    assert doc["filename"] == "b.md"


def test_get_document_by_hash_missing_returns_none(store: StoreProtocol) -> None:
    """An unknown hash yields None, not an error."""
    assert store.get_document_by_hash("nope") is None


def test_update_document_changes_filename(store: StoreProtocol) -> None:
    """update_document overwrites the stored filename."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="old.md", file_hash="h")
    store.update_document(id=doc_id, filename="new.md")
    doc = store.get_document_by_hash("h")
    assert doc is not None
    assert doc["filename"] == "new.md"


def test_user_id_defaults_to_settings_default(store: StoreProtocol) -> None:
    """Omitting user_id falls back to settings.default_user_id (the ADR 0003 seam)."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="a.md", file_hash="h")
    doc = store.get_document_by_hash("h")
    assert doc is not None
    assert doc["user_id"] == settings.default_user_id


def test_user_id_override_is_honored(store: StoreProtocol) -> None:
    """An explicit user_id is stored instead of the default."""
    doc_id = uuid.uuid4()
    uid = uuid.uuid4()
    store.add_document(id=doc_id, filename="a.md", file_hash="h", user_id=uid)
    doc = store.get_document_by_hash("h")
    assert doc is not None
    assert doc["user_id"] == uid


def test_add_chunks_are_retrievable_by_document(store: StoreProtocol) -> None:
    """Chunks written by add_chunks come back via get_chunks_by_document, fields intact."""
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    store.add_chunks(
        [
            {
                "id": chunk_id,
                "document_id": doc_id,
                "content": "hello",
                "metadata": {"page": 1},
                "embedding": [0.0] * settings.embedding_dimension,
            }
        ]
    )

    chunks = store.get_chunks_by_document(doc_id)

    assert len(chunks) == 1
    assert chunks[0]["id"] == chunk_id
    assert chunks[0]["content"] == "hello"
    assert chunks[0]["metadata"] == {"page": 1}


def test_delete_document_cascades_chunks(store: StoreProtocol) -> None:
    """Deleting a document removes it and cascades to its chunks."""
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    store.add_chunks(
        [
            {
                "id": chunk_id,
                "document_id": doc_id,
                "content": "chunk",
                "metadata": {},
                "embedding": [0.0] * settings.embedding_dimension,
            }
        ]
    )
    assert len(store.get_chunks_by_document(doc_id)) == 1

    store.delete_document(doc_id)

    assert store.get_document_by_hash("h") is None
    assert store.get_chunks_by_document(doc_id) == []


def test_both_implementations_conform_to_protocol() -> None:
    """Both Store and InMemoryStore satisfy StoreProtocol, structurally and at runtime."""
    # mypy --strict checks these assignments; the concrete Store constructs without connecting.
    fake: StoreProtocol = InMemoryStore()
    real: StoreProtocol = Store(database_url="postgresql://placeholder")
    assert isinstance(fake, StoreProtocol)
    assert isinstance(real, StoreProtocol)
