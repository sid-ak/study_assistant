"""Shared behavior contract for the store seam.

Every test here takes `store: StoreProtocol` (a parametrized fixture) and
runs once against `InMemoryStore` and once against the real, DB-backed `Store` — labeled
`[memory]` / `[db]` in test output. This is deliberate: `add_document`, `add_chunks`, and the rest
of `StoreProtocol` must behave identically regardless of which implementation is behind it, and a
single shared assertion can't silently drift out of sync the way two hand-duplicated copies could.

Only `StoreProtocol` methods are used here — nothing peeks at implementation internals (no
`get_connection()`, no reaching into `InMemoryStore.chunks`). Behavior that genuinely can't be
expressed through the Protocol (raw vector round-tripping, schema DDL idempotency) stays in the
DB-only tests against the concrete `Store`.
"""

import uuid

import numpy as np
import pytest

from rag_core.config import settings
from rag_core.store import (
    EmbeddingDimensionError,
    MissingDocumentError,
    Store,
    StoreProtocol,
)
from rag_core.store.embedders import EmbedderRegistryProtocol
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
    """Omitting user_id falls back to settings.default_user_id, the single-user default."""
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
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk = make_chunk(doc_id, store.embedder.dimension, content="hello", metadata={"page": 1})
    store.add_chunks([chunk])

    chunks = store.get_chunks_by_document(doc_id)

    assert len(chunks) == 1
    assert chunks[0]["id"] == chunk["id"]
    assert chunks[0]["content"] == "hello"
    assert chunks[0]["metadata"] == {"page": 1}
    assert np.allclose(chunks[0]["embedding"], chunk["embedding"])


def test_delete_document_cascades_chunks(store: StoreProtocol) -> None:
    """Deleting a document removes it and cascades to its chunks."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    store.add_chunks([make_chunk(doc_id, store.embedder.dimension)])
    assert len(store.get_chunks_by_document(doc_id)) == 1

    store.delete_document(doc_id)

    assert store.get_document_by_hash("h") is None
    assert store.get_chunks_by_document(doc_id) == []


def test_add_chunks_rejects_unknown_document(store: StoreProtocol) -> None:
    """A chunk whose document_id has no document is refused, as the DB foreign key refuses it."""
    with pytest.raises(MissingDocumentError):
        store.add_chunks([make_chunk(uuid.uuid4(), store.embedder.dimension)])


def test_add_chunks_is_all_or_nothing(store: StoreProtocol) -> None:
    """One invalid chunk fails the whole batch, leaving none of its chunks stored."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    batch = [
        make_chunk(doc_id, store.embedder.dimension),
        make_chunk(uuid.uuid4(), store.embedder.dimension),
    ]

    with pytest.raises(MissingDocumentError):
        store.add_chunks(batch)

    assert store.get_chunks_by_document(doc_id) == []


def test_add_chunks_rejects_wrong_dimension(store: StoreProtocol) -> None:
    """An embedding whose length differs from the store's embedder dimension is refused."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    with pytest.raises(EmbeddingDimensionError):
        store.add_chunks([make_chunk(doc_id, store.embedder.dimension + 1)])
    assert store.get_chunks_by_document(doc_id) == []


def test_store_reports_the_embedder_it_is_bound_to(store: StoreProtocol) -> None:
    """A store exposes the model whose column it writes and reads."""
    assert store.embedder == EMBEDDER_A


def test_with_embedder_binds_another_model_over_the_same_data(
    store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol
) -> None:
    """with_embedder returns a store over the same documents and chunks, bound to another model."""
    embedder_registry.register(EMBEDDER_B.model_id, EMBEDDER_B.dimension)
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk = make_chunk(doc_id, EMBEDDER_A.dimension)
    store.add_chunks([chunk])

    other = store.with_embedder(EMBEDDER_B)

    assert other.embedder == EMBEDDER_B
    assert store.embedder == EMBEDDER_A
    doc = other.get_document_by_hash("h")
    assert doc is not None and doc["id"] == doc_id
    # The chunk is shared, but model B has not embedded it yet.
    [shared] = other.get_chunks_by_document(doc_id)
    assert shared["id"] == chunk["id"]
    assert shared["embedding"] is None


def test_stores_bound_to_different_models_keep_separate_embeddings(
    store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol
) -> None:
    """Writes through one model's store never change another model's embeddings (side-by-side)."""
    embedder_registry.register(EMBEDDER_B.model_id, EMBEDDER_B.dimension)
    other = store.with_embedder(EMBEDDER_B)
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk_a = make_chunk(doc_id, EMBEDDER_A.dimension)
    chunk_b = make_chunk(doc_id, EMBEDDER_B.dimension)

    store.add_chunks([chunk_a])
    other.add_chunks([chunk_b])

    by_id_a = {c["id"]: c["embedding"] for c in store.get_chunks_by_document(doc_id)}
    by_id_b = {c["id"]: c["embedding"] for c in other.get_chunks_by_document(doc_id)}
    assert np.allclose(by_id_a[chunk_a["id"]], chunk_a["embedding"])
    assert by_id_a[chunk_b["id"]] is None
    assert np.allclose(by_id_b[chunk_b["id"]], chunk_b["embedding"])
    assert by_id_b[chunk_a["id"]] is None


def test_with_embedder_store_enforces_its_own_dimension(
    store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol
) -> None:
    """A rebound store validates embeddings against its new model's dimension, not the old one."""
    embedder_registry.register(EMBEDDER_B.model_id, EMBEDDER_B.dimension)
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    with pytest.raises(EmbeddingDimensionError):
        store.with_embedder(EMBEDDER_B).add_chunks([make_chunk(doc_id, EMBEDDER_A.dimension)])


def test_returned_chunks_are_copies(store: StoreProtocol) -> None:
    """Mutating a chunk returned by get_chunks_by_document does not change what the store holds."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk = make_chunk(doc_id, store.embedder.dimension, metadata={"page": 1})
    store.add_chunks([chunk])

    [returned] = store.get_chunks_by_document(doc_id)
    returned["metadata"]["page"] = 99
    returned["embedding"][0] = 99.0

    [again] = store.get_chunks_by_document(doc_id)
    assert again["metadata"] == {"page": 1}
    assert np.allclose(again["embedding"], chunk["embedding"])


def test_stored_chunks_do_not_alias_the_input(store: StoreProtocol) -> None:
    """Mutating a chunk dict after add_chunks does not change what the store holds."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk = make_chunk(doc_id, store.embedder.dimension, metadata={"page": 1})
    original_embedding = list(chunk["embedding"])
    store.add_chunks([chunk])

    chunk["metadata"]["page"] = 99
    chunk["embedding"][0] = 99.0

    [stored] = store.get_chunks_by_document(doc_id)
    assert stored["metadata"] == {"page": 1}
    assert np.allclose(stored["embedding"], original_embedding)


def test_returned_document_is_a_copy(store: StoreProtocol) -> None:
    """Mutating a document returned by get_document_by_hash does not change the stored document."""
    store.add_document(id=uuid.uuid4(), filename="d.md", file_hash="h")
    doc = store.get_document_by_hash("h")
    assert doc is not None
    doc["filename"] = "changed.md"

    again = store.get_document_by_hash("h")
    assert again is not None
    assert again["filename"] == "d.md"


def test_chunks_come_back_in_insertion_order(store: StoreProtocol) -> None:
    """get_chunks_by_document returns chunks in the order they were added, across batches."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    # Descending ids, so insertion order differs from id order.
    ids = [uuid.UUID(int=n) for n in (50, 40, 30, 20, 10)]
    dimension = store.embedder.dimension
    store.add_chunks([make_chunk(doc_id, dimension, id=i) for i in ids[:3]])
    store.add_chunks([make_chunk(doc_id, dimension, id=i) for i in ids[3:]])

    assert [c["id"] for c in store.get_chunks_by_document(doc_id)] == ids


def test_both_implementations_conform_to_protocol() -> None:
    """Both Store and InMemoryStore satisfy StoreProtocol, structurally and at runtime."""
    # mypy --strict checks these assignments; the concrete Store constructs without connecting.
    fake: StoreProtocol = InMemoryStore(embedder=EMBEDDER_A)
    real: StoreProtocol = Store(database_url="postgresql://placeholder", embedder=EMBEDDER_A)
    assert isinstance(fake, StoreProtocol)
    assert isinstance(real, StoreProtocol)
