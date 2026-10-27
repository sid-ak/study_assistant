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

import numpy as np
import pytest

from rag_core.config import settings
from rag_core.store import (
    EmbedderNotFoundError,
    EmbeddingDimensionError,
    MissingDocumentError,
    Store,
    StoreProtocol,
)
from rag_core.store.embedders import EmbedderInfo, EmbedderRegistryProtocol
from rag_core_testing import EMBEDDER_A, EMBEDDER_B, InMemoryStore, make_chunk


def test_initialize_can_run_repeatedly(store: StoreProtocol) -> None:
    """initialize is safe to call more than once and leaves the store usable."""
    store.initialize()
    store.initialize()
    assert store.get_document_by_hash("nope") is None


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


def test_add_chunks_are_retrievable_by_document(
    store: StoreProtocol, embedder: EmbedderInfo
) -> None:
    """Chunks written by add_chunks come back via get_chunks_by_document, fields intact."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk = make_chunk(doc_id, embedder.dimension, content="hello", metadata={"page": 1})
    store.add_chunks([chunk])

    chunks = store.get_chunks_by_document(doc_id)

    assert len(chunks) == 1
    assert chunks[0]["id"] == chunk["id"]
    assert chunks[0]["content"] == "hello"
    assert chunks[0]["metadata"] == {"page": 1}
    assert np.allclose(chunks[0]["embedding"], chunk["embedding"])


def test_delete_document_cascades_chunks(store: StoreProtocol, embedder: EmbedderInfo) -> None:
    """Deleting a document removes it and cascades to its chunks."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    store.add_chunks([make_chunk(doc_id, embedder.dimension)])
    assert len(store.get_chunks_by_document(doc_id)) == 1

    store.delete_document(doc_id)

    assert store.get_document_by_hash("h") is None
    assert store.get_chunks_by_document(doc_id) == []


def test_add_chunks_rejects_unknown_document(store: StoreProtocol, embedder: EmbedderInfo) -> None:
    """A chunk whose document_id has no document is refused, as the DB foreign key refuses it."""
    with pytest.raises(MissingDocumentError):
        store.add_chunks([make_chunk(uuid.uuid4(), embedder.dimension)])


def test_add_chunks_is_all_or_nothing(store: StoreProtocol, embedder: EmbedderInfo) -> None:
    """One invalid chunk fails the whole batch, leaving none of its chunks stored."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    batch = [make_chunk(doc_id, embedder.dimension), make_chunk(uuid.uuid4(), embedder.dimension)]

    with pytest.raises(MissingDocumentError):
        store.add_chunks(batch)

    assert store.get_chunks_by_document(doc_id) == []


def test_add_chunks_requires_a_current_embedder(store: StoreProtocol) -> None:
    """Without a current embedder there is no column to write embeddings into."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    with pytest.raises(EmbedderNotFoundError):
        store.add_chunks([make_chunk(doc_id, EMBEDDER_A.dimension)])


def test_add_chunks_rejects_wrong_dimension(store: StoreProtocol, embedder: EmbedderInfo) -> None:
    """An embedding whose length differs from the current embedder's dimension is refused."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    with pytest.raises(EmbeddingDimensionError):
        store.add_chunks([make_chunk(doc_id, embedder.dimension + 1)])
    assert store.get_chunks_by_document(doc_id) == []


def test_embedder_swap_keeps_existing_embeddings(
    store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol, embedder: EmbedderInfo
) -> None:
    """Adding a second embedder is additive: the first model's embeddings survive the swap."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk = make_chunk(doc_id, embedder.dimension)
    store.add_chunks([chunk])

    embedder_registry.register(EMBEDDER_B.model_id, EMBEDDER_B.dimension)
    embedder_registry.set_current(EMBEDDER_B.model_id)
    # Not yet backfilled under the new model.
    assert store.get_chunks_by_document(doc_id)[0]["embedding"] is None

    embedder_registry.set_current(embedder.model_id)
    assert np.allclose(store.get_chunks_by_document(doc_id)[0]["embedding"], chunk["embedding"])


def test_both_implementations_conform_to_protocol() -> None:
    """Both Store and InMemoryStore satisfy StoreProtocol, structurally and at runtime."""
    # mypy --strict checks these assignments; the concrete Store constructs without connecting.
    fake: StoreProtocol = InMemoryStore()
    real: StoreProtocol = Store(database_url="postgresql://placeholder")
    assert isinstance(fake, StoreProtocol)
    assert isinstance(real, StoreProtocol)
