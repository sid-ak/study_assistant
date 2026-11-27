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
    DuplicateIdError,
    EmbeddingDimensionError,
    MissingChunkError,
    MissingDocumentError,
    Store,
    StoreProtocol,
    ZeroEmbeddingError,
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


def test_add_chunks_rejects_an_id_already_stored(store: StoreProtocol) -> None:
    """A batch reusing a stored chunk's id is refused whole, and the stored chunk is unchanged."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    original = make_chunk(doc_id, store.embedder.dimension, content="original")
    store.add_chunks([original])
    reused = make_chunk(doc_id, store.embedder.dimension, id=original["id"], content="replaced")
    fresh = make_chunk(doc_id, store.embedder.dimension)

    with pytest.raises(DuplicateIdError):
        store.add_chunks([fresh, reused])

    stored = store.get_chunks_by_document(doc_id)
    assert [chunk["id"] for chunk in stored] == [original["id"]]
    assert stored[0]["content"] == "original"


def test_add_chunks_rejects_an_id_repeated_in_one_batch(store: StoreProtocol) -> None:
    """A batch that holds the same chunk id twice is refused whole."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk = make_chunk(doc_id, store.embedder.dimension)
    repeat = make_chunk(doc_id, store.embedder.dimension, id=chunk["id"])

    with pytest.raises(DuplicateIdError):
        store.add_chunks([chunk, repeat])

    assert store.get_chunks_by_document(doc_id) == []


def test_add_document_rejects_an_id_used_by_another_file(store: StoreProtocol) -> None:
    """Reusing a document's id for a different file_hash is refused, leaving the document as is."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="a.md", file_hash="hash-a")

    with pytest.raises(DuplicateIdError):
        store.add_document(id=doc_id, filename="b.md", file_hash="hash-b")

    stored = store.get_document_by_hash("hash-a")
    assert stored is not None
    assert stored["id"] == doc_id
    assert stored["filename"] == "a.md"
    assert store.get_document_by_hash("hash-b") is None


def test_add_document_accepts_the_same_id_and_hash_again(store: StoreProtocol) -> None:
    """Re-adding a document with its own id and file_hash is an idempotent re-ingest."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="a.md", file_hash="hash-a")
    assert store.add_document(id=doc_id, filename="a2.md", file_hash="hash-a") == doc_id


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


def unit_vector(values: list[float], dimension: int) -> list[float]:
    """``values`` scaled to length 1 and padded with zeros to ``dimension``."""
    length = 0.0
    for value in values:
        length += value * value
    length = length**0.5
    vector = [value / length for value in values]
    return vector + [0.0] * (dimension - len(vector))


def add_chunks_with_embeddings(
    store: StoreProtocol, embeddings: list[list[float]]
) -> list[uuid.UUID]:
    """Store one document with one chunk per embedding; return the chunk ids in that order."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash=str(doc_id))
    chunks = []
    for embedding in embeddings:
        chunks.append(make_chunk(doc_id, store.embedder.dimension, embedding=embedding))
    store.add_chunks(chunks)
    return [chunk["id"] for chunk in chunks]


def test_search_dense_ranks_nearest_first_with_cosine_distance(store: StoreProtocol) -> None:
    """Results come back by ascending cosine distance, each with its distance."""
    dimension = store.embedder.dimension
    far, near, middle = add_chunks_with_embeddings(
        store,
        [
            unit_vector([0.0, 1.0], dimension),
            unit_vector([1.0, 0.0], dimension),
            unit_vector([0.8, 0.6], dimension),
        ],
    )
    results = store.search_dense(unit_vector([1.0, 0.0], dimension), limit=3)

    assert [result["id"] for result in results] == [near, middle, far]
    assert [result["distance"] for result in results] == pytest.approx([0.0, 0.2, 1.0], abs=1e-5)


def test_search_dense_returns_at_most_limit_results(store: StoreProtocol) -> None:
    """Only the ``limit`` nearest chunks are returned."""
    dimension = store.embedder.dimension
    ids = add_chunks_with_embeddings(
        store,
        [
            unit_vector([1.0, 0.0], dimension),
            unit_vector([0.8, 0.6], dimension),
            unit_vector([0.0, 1.0], dimension),
        ],
    )
    results = store.search_dense(unit_vector([1.0, 0.0], dimension), limit=2)
    assert [result["id"] for result in results] == ids[:2]


def test_search_dense_returns_the_chunk_fields(store: StoreProtocol) -> None:
    """Each result carries the chunk's id, document id, content, and metadata."""
    dimension = store.embedder.dimension
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    chunk = make_chunk(
        doc_id,
        dimension,
        content="Link with -pthread.",
        metadata={"source": "ci.md", "section": "Fix"},
        embedding=unit_vector([1.0], dimension),
    )
    store.add_chunks([chunk])

    (result,) = store.search_dense(unit_vector([1.0], dimension), limit=1)
    assert result["id"] == chunk["id"]
    assert result["document_id"] == doc_id
    assert result["content"] == "Link with -pthread."
    assert result["metadata"] == {"source": "ci.md", "section": "Fix"}


def test_search_dense_results_are_copies(store: StoreProtocol) -> None:
    """Mutating a result's metadata does not change the stored chunk."""
    dimension = store.embedder.dimension
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    store.add_chunks(
        [
            make_chunk(
                doc_id, dimension, metadata={"k": "v"}, embedding=unit_vector([1.0], dimension)
            )
        ]
    )
    (result,) = store.search_dense(unit_vector([1.0], dimension), limit=1)
    result["metadata"]["k"] = "changed"

    assert store.get_chunks_by_document(doc_id)[0]["metadata"] == {"k": "v"}


def test_search_dense_on_an_empty_store_returns_nothing(store: StoreProtocol) -> None:
    """With no chunks stored, a search returns an empty list."""
    assert store.search_dense(unit_vector([1.0], store.embedder.dimension), limit=5) == []


def test_search_dense_only_sees_chunks_embedded_by_its_model(
    store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol
) -> None:
    """A store searches only the vectors of the model it is bound to."""
    embedder_registry.register(EMBEDDER_B.model_id, EMBEDDER_B.dimension)
    store_b = store.with_embedder(EMBEDDER_B)
    ids_a = add_chunks_with_embeddings(store, [unit_vector([1.0], EMBEDDER_A.dimension)])
    ids_b = add_chunks_with_embeddings(store_b, [unit_vector([1.0], EMBEDDER_B.dimension)])

    results_a = store.search_dense(unit_vector([1.0], EMBEDDER_A.dimension), limit=5)
    results_b = store_b.search_dense(unit_vector([1.0], EMBEDDER_B.dimension), limit=5)
    assert [result["id"] for result in results_a] == ids_a
    assert [result["id"] for result in results_b] == ids_b


def test_search_dense_rejects_a_query_of_the_wrong_dimension(store: StoreProtocol) -> None:
    """A query vector whose length differs from the store's model raises."""
    with pytest.raises(EmbeddingDimensionError):
        store.search_dense(unit_vector([1.0], store.embedder.dimension + 1), limit=1)


@pytest.mark.parametrize("limit", [0, -1])
def test_search_dense_rejects_a_limit_below_one(store: StoreProtocol, limit: int) -> None:
    """A limit below one is refused."""
    with pytest.raises(ValueError):
        store.search_dense(unit_vector([1.0], store.embedder.dimension), limit=limit)


def test_search_dense_rejects_a_zero_query_vector(store: StoreProtocol) -> None:
    """A query with no direction has no cosine distance to anything, so it is refused."""
    with pytest.raises(ZeroEmbeddingError):
        store.search_dense([0.0] * store.embedder.dimension, limit=1)


def test_search_dense_accepts_an_ef_search(store: StoreProtocol) -> None:
    """A search with ``ef_search`` set returns the nearest chunks, nearest first."""
    dimension = store.embedder.dimension
    far, near = add_chunks_with_embeddings(
        store, [unit_vector([0.0, 1.0], dimension), unit_vector([1.0, 0.0], dimension)]
    )
    results = store.search_dense(unit_vector([1.0, 0.0], dimension), limit=2, ef_search=100)
    assert [result["id"] for result in results] == [near, far]


@pytest.mark.parametrize("ef_search", [0, 1001])
def test_search_dense_rejects_an_ef_search_out_of_range(
    store: StoreProtocol, ef_search: int
) -> None:
    """``ef_search`` must be between 1 and 1000, the range the index accepts."""
    with pytest.raises(ValueError, match="ef_search"):
        store.search_dense(
            unit_vector([1.0], store.embedder.dimension), limit=1, ef_search=ef_search
        )


def test_search_dense_rejects_an_ef_search_below_the_limit(store: StoreProtocol) -> None:
    """An ``ef_search`` smaller than ``limit`` is refused, since it would cap the results."""
    with pytest.raises(ValueError, match="ef_search"):
        store.search_dense(unit_vector([1.0], store.embedder.dimension), limit=5, ef_search=4)


def test_add_chunks_rejects_a_zero_embedding(store: StoreProtocol) -> None:
    """An all-zero embedding has no direction to search by, so the whole batch is refused."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash="h")
    dimension = store.embedder.dimension
    good = make_chunk(doc_id, dimension)
    zero = make_chunk(doc_id, dimension, embedding=[0.0] * dimension)
    with pytest.raises(ZeroEmbeddingError):
        store.add_chunks([good, zero])
    assert store.get_chunks_by_document(doc_id) == []


def store_contents(store: StoreProtocol, contents: list[str]) -> list[uuid.UUID]:
    """Store one document with a chunk per text, embedded by ``store``'s model; return the ids."""
    doc_id = uuid.uuid4()
    store.add_document(id=doc_id, filename="d.md", file_hash=str(doc_id))
    chunks = []
    for content in contents:
        chunks.append(make_chunk(doc_id, store.embedder.dimension, content=content))
    store.add_chunks(chunks)
    return [chunk["id"] for chunk in chunks]


def unembedded_pairs(store: StoreProtocol, limit: int = 100) -> list[tuple[uuid.UUID, str]]:
    """The ``(id, content)`` of each chunk ``store``'s model has not embedded, in listed order."""
    pairs = []
    for row in store.get_unembedded_chunks(limit=limit):
        pairs.append((row["id"], row["content"]))
    return pairs


@pytest.fixture
def store_b(store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol) -> StoreProtocol:
    """A store over the same data as ``store``, bound to a second registered model."""
    embedder_registry.register(EMBEDDER_B.model_id, EMBEDDER_B.dimension)
    return store.with_embedder(EMBEDDER_B)


def test_get_unembedded_chunks_lists_what_the_model_has_not_embedded(
    store: StoreProtocol, store_b: StoreProtocol
) -> None:
    """Chunks another model embedded are listed for this one, as id and content, in added order."""
    ids = store_contents(store, ["first", "second", "third"])

    assert unembedded_pairs(store_b) == [(ids[0], "first"), (ids[1], "second"), (ids[2], "third")]
    assert unembedded_pairs(store) == []


def test_get_unembedded_chunks_returns_at_most_limit(
    store: StoreProtocol, store_b: StoreProtocol
) -> None:
    """``limit`` caps the list, taking the earliest-added chunks first."""
    ids = store_contents(store, ["first", "second", "third"])

    assert unembedded_pairs(store_b, limit=2) == [(ids[0], "first"), (ids[1], "second")]


@pytest.mark.parametrize("limit", [0, -1])
def test_get_unembedded_chunks_rejects_a_limit_below_one(store: StoreProtocol, limit: int) -> None:
    """A limit below one is an error, not an empty list."""
    with pytest.raises(ValueError):
        store.get_unembedded_chunks(limit=limit)


def test_set_embeddings_fills_only_the_bound_models_column(
    store: StoreProtocol, store_b: StoreProtocol
) -> None:
    """Vectors set through one model's store go to that model; the other model's are unchanged."""
    ids = store_contents(store, ["first", "second"])
    before_a = store.search_dense(unit_vector([1.0], EMBEDDER_A.dimension), limit=2)
    vectors = [
        unit_vector([1.0, 0.0], EMBEDDER_B.dimension),
        unit_vector([0.0, 1.0], EMBEDDER_B.dimension),
    ]

    store_b.set_embeddings(
        [{"id": ids[0], "embedding": vectors[0]}, {"id": ids[1], "embedding": vectors[1]}]
    )

    assert unembedded_pairs(store_b) == []
    nearest = store_b.search_dense(unit_vector([0.0, 1.0], EMBEDDER_B.dimension), limit=1)
    assert nearest[0]["id"] == ids[1]
    assert nearest[0]["distance"] == pytest.approx(0.0, abs=1e-6)
    after_a = store.search_dense(unit_vector([1.0], EMBEDDER_A.dimension), limit=2)
    assert after_a == before_a


def test_set_embeddings_replaces_a_vector_already_stored(store: StoreProtocol) -> None:
    """Setting a chunk's vector again overwrites the old one for that model."""
    [chunk_id] = store_contents(store, ["only"])
    replacement = unit_vector([0.0, 0.0, 1.0], EMBEDDER_A.dimension)

    store.set_embeddings([{"id": chunk_id, "embedding": replacement}])

    nearest = store.search_dense(replacement, limit=1)
    assert nearest[0]["id"] == chunk_id
    assert nearest[0]["distance"] == pytest.approx(0.0, abs=1e-6)


def test_set_embeddings_with_nothing_to_set_does_nothing(store_b: StoreProtocol) -> None:
    """An empty batch is accepted and changes nothing."""
    store_b.set_embeddings([])
    assert unembedded_pairs(store_b) == []


@pytest.mark.parametrize(
    ("bad_row", "error"),
    [
        ("unknown id", MissingChunkError),
        ("wrong dimension", EmbeddingDimensionError),
        ("zero vector", ZeroEmbeddingError),
        ("repeated id", DuplicateIdError),
    ],
)
def test_set_embeddings_is_all_or_nothing(
    store: StoreProtocol, store_b: StoreProtocol, bad_row: str, error: type[Exception]
) -> None:
    """One bad row fails the whole batch, and no vector in it is written."""
    ids = store_contents(store, ["first", "second"])
    good = {"id": ids[0], "embedding": unit_vector([1.0], EMBEDDER_B.dimension)}
    bad_rows = {
        "unknown id": {"id": uuid.uuid4(), "embedding": unit_vector([1.0], EMBEDDER_B.dimension)},
        "wrong dimension": {"id": ids[1], "embedding": unit_vector([1.0], EMBEDDER_A.dimension)},
        "zero vector": {"id": ids[1], "embedding": [0.0] * EMBEDDER_B.dimension},
        "repeated id": {"id": ids[0], "embedding": unit_vector([0.0, 1.0], EMBEDDER_B.dimension)},
    }

    with pytest.raises(error):
        store_b.set_embeddings([good, bad_rows[bad_row]])

    assert unembedded_pairs(store_b) == [(ids[0], "first"), (ids[1], "second")]


LEXICAL_TEXTS = [
    "Orbit 5.0 rejects requests over the in-flight limit with error E1050.",
    "Bazel: bazel test --config=asan runs every test under AddressSanitizer.",
    "CMake presets name a complete configuration for every developer.",
]


def lexical_contents(store: StoreProtocol, query: str, limit: int = 10) -> set[str]:
    """The content of every chunk ``search_lexical`` returns for ``query``, as a set.

    The fake's scorer and the database's ``ts_rank`` order matches differently, so the contract
    is which chunks come back, not their order.
    """
    contents = set()
    for row in store.search_lexical(query, limit=limit):
        contents.add(row["content"])
    return contents


def test_search_lexical_finds_chunks_sharing_the_query_words(store: StoreProtocol) -> None:
    """A chunk containing a query word is returned; a chunk containing none is not."""
    store_contents(store, LEXICAL_TEXTS)

    assert lexical_contents(store, "What does error E1050 mean?") == {LEXICAL_TEXTS[0]}


def test_search_lexical_matches_an_exact_identifier(store: StoreProtocol) -> None:
    """A code or flag the embedding model blurs is matched exactly, whatever its case."""
    store_contents(store, LEXICAL_TEXTS)

    assert lexical_contents(store, "e1050") == {LEXICAL_TEXTS[0]}
    assert lexical_contents(store, "asan") == {LEXICAL_TEXTS[1]}


def test_search_lexical_matches_any_query_word(store: StoreProtocol) -> None:
    """A long question matches chunks that contain only some of its words."""
    store_contents(store, LEXICAL_TEXTS)

    found = lexical_contents(store, "Which bazel flag enables cmake presets?")

    assert found == {LEXICAL_TEXTS[1], LEXICAL_TEXTS[2]}


def test_search_lexical_returns_the_chunk_fields_and_a_score(store: StoreProtocol) -> None:
    """Each result carries the chunk's id, document, content, metadata, and a positive score."""
    [chunk_id] = store_contents(store, LEXICAL_TEXTS[:1])

    [row] = store.search_lexical("E1050", limit=5)

    assert row["id"] == chunk_id
    assert row["content"] == LEXICAL_TEXTS[0]
    assert "document_id" in row
    assert "metadata" in row
    assert row["score"] > 0


def test_search_lexical_returns_at_most_limit(store: StoreProtocol) -> None:
    """``limit`` caps the number of results."""
    store_contents(store, LEXICAL_TEXTS)

    assert len(store.search_lexical("orbit bazel cmake", limit=2)) == 2


@pytest.mark.parametrize("query", ["zebra quantum", "the of and", "   "])
def test_search_lexical_returns_nothing_without_a_usable_word(
    store: StoreProtocol, query: str
) -> None:
    """No match, a query of only common stop words, or a blank query returns no chunks."""
    store_contents(store, LEXICAL_TEXTS)

    assert store.search_lexical(query, limit=5) == []


def test_search_lexical_needs_no_embedding(store: StoreProtocol, store_b: StoreProtocol) -> None:
    """Lexical search reads the text, so a store bound to another model finds the same chunks."""
    store_contents(store, LEXICAL_TEXTS)

    assert lexical_contents(store_b, "E1050") == {LEXICAL_TEXTS[0]}


@pytest.mark.parametrize("limit", [0, -1])
def test_search_lexical_rejects_a_limit_below_one(store: StoreProtocol, limit: int) -> None:
    """A limit below one is an error, not an empty list."""
    with pytest.raises(ValueError):
        store.search_lexical("E1050", limit=limit)


def test_both_implementations_conform_to_protocol() -> None:
    """Both Store and InMemoryStore satisfy StoreProtocol, structurally and at runtime."""
    # mypy --strict checks these assignments; the concrete Store constructs without connecting.
    fake: StoreProtocol = InMemoryStore(embedder=EMBEDDER_A)
    real: StoreProtocol = Store(database_url="postgresql://placeholder", embedder=EMBEDDER_A)
    assert isinstance(fake, StoreProtocol)
    assert isinstance(real, StoreProtocol)
