"""In-memory fake of ``StoreProtocol`` for unit tests.

A lightweight fake so tests that only need storage semantics — not real pgvector — run without a
database. It mirrors the concrete ``Store``'s CRUD contract: hash-keyed idempotent document upsert,
unique document and chunk ids, the chunk -> document foreign key with cascade on delete, per-model
embeddings with one model per store instance, and the same ``user_id`` default. Dense search is
exact: it compares the query with every chunk, where the database uses an approximate index. It
does not model full-text search.
"""

import copy
import math
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from rag_core.config import settings
from rag_core.store.embedders import EmbedderInfo
from rag_core.store.errors import DuplicateIdError, MissingDocumentError
from rag_core.store.validation import check_dimensions, check_search


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """``1 - cosine similarity`` of two non-zero vectors of the same length."""
    dot = 0.0
    a_squares = 0.0
    b_squares = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        a_squares += x * x
        b_squares += y * y
    return 1.0 - dot / math.sqrt(a_squares * b_squares)


class InMemoryStore:
    """Dict-backed fake conforming to ``StoreProtocol``."""

    def __init__(self, embedder: EmbedderInfo) -> None:
        """Start empty and bound to ``embedder``; document rows mirror Store's SELECT shape."""
        self.embedder = embedder
        self.documents: dict[UUID, dict[str, Any]] = {}
        # Each chunk keeps an ``embeddings`` map of model id -> vector, the per-model columns.
        self.chunks: dict[UUID, dict[str, Any]] = {}

    def with_embedder(self, embedder: EmbedderInfo) -> "InMemoryStore":
        """Return a store sharing this one's documents and chunks, bound to ``embedder``."""
        other = InMemoryStore(embedder)
        other.documents = self.documents
        other.chunks = self.chunks
        return other

    def initialize(self) -> None:
        """No-op: an in-memory store has nothing to prepare."""

    def add_document(
        self,
        id: UUID,
        filename: str,
        file_hash: str,
        user_id: UUID | None = None,
    ) -> UUID:
        """Insert document metadata idempotently by file_hash, returning the stored id."""
        uid = user_id or settings.default_user_id
        # Idempotent by file_hash: keep the original row/id, refresh the filename.
        for doc in self.documents.values():
            if doc["file_hash"] == file_hash:
                doc["filename"] = filename
                stored_id: UUID = doc["id"]
                return stored_id
        # Mirrors the documents primary key: no stored document has this file_hash, so an
        # existing document with this id belongs to another file.
        if id in self.documents:
            raise DuplicateIdError(f"Document id {id} already belongs to another file.")
        self.documents[id] = {
            "id": id,
            "filename": filename,
            "file_hash": file_hash,
            "user_id": uid,
        }
        return id

    def update_document(self, id: UUID, filename: str) -> None:
        """Update the stored filename; a no-op if the document is unknown."""
        doc = self.documents.get(id)
        if doc is not None:
            doc["filename"] = filename

    def delete_document(self, id: UUID) -> None:
        """Delete a document and cascade-drop its chunks."""
        self.documents.pop(id, None)
        # Cascade in place: stores from with_embedder share this dict, so it is never replaced.
        for cid in [cid for cid, chunk in self.chunks.items() if chunk["document_id"] == id]:
            del self.chunks[cid]

    def get_document_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        """Return a copy of the document with this file_hash, or None if absent."""
        for doc in self.documents.values():
            if doc["file_hash"] == file_hash:
                return copy.deepcopy(doc)
        return None

    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_id: UUID | None = None,
    ) -> None:
        """Store each chunk by id, all-or-nothing, with its embedding under this store's model."""
        uid = user_id or settings.default_user_id
        check_dimensions(chunks, self.embedder)
        # Mirrors the chunks.document_id foreign key; checked before any write so a bad batch
        # leaves nothing behind, as the DB's single COPY transaction does.
        for chunk in chunks:
            if chunk["document_id"] not in self.documents:
                raise MissingDocumentError(
                    f"Chunk {chunk['id']} references unknown document {chunk['document_id']}."
                )
        # Mirrors the chunks primary key, also before any write: an id already stored, or one
        # that repeats within this batch, fails the whole batch instead of overwriting.
        batch_ids: set[UUID] = set()
        for chunk in chunks:
            if chunk["id"] in self.chunks or chunk["id"] in batch_ids:
                raise DuplicateIdError(f"Chunk id {chunk['id']} is already in use.")
            batch_ids.add(chunk["id"])
        for chunk in chunks:
            self.chunks[chunk["id"]] = {
                "id": chunk["id"],
                "document_id": chunk["document_id"],
                "content": chunk["content"],
                "metadata": copy.deepcopy(chunk["metadata"]),
                "embeddings": {self.embedder.model_id: list(chunk["embedding"])},
                "user_id": uid,
            }

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return copies of every chunk belonging to ``document_id``, in insertion order, or ``[]``.

        ``embedding`` is this store's model's vector, or ``None`` if it has not embedded the chunk.
        """
        return [
            {
                "id": c["id"],
                "document_id": c["document_id"],
                "content": c["content"],
                "metadata": copy.deepcopy(c["metadata"]),
                "embedding": copy.deepcopy(c["embeddings"].get(self.embedder.model_id)),
                "user_id": c["user_id"],
            }
            for c in self.chunks.values()
            if c["document_id"] == document_id
        ]

    def search_dense(
        self, query_embedding: Sequence[float], limit: int, ef_search: int | None = None
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` chunks nearest to ``query_embedding`` by cosine distance.

        Compares the query with every chunk, so it is exact where the database's index search is
        approximate, and ``ef_search`` is checked but has nothing to tune. Equal distances keep
        insertion order.
        """
        check_search(query_embedding, limit, self.embedder, ef_search)
        # Each entry is (distance, insertion position, chunk). Sorting the tuples orders by
        # distance first and breaks ties by position, so the chunk dicts are never compared.
        scored: list[tuple[float, int, dict[str, Any]]] = []
        position = 0
        for chunk in self.chunks.values():
            embedding = chunk["embeddings"].get(self.embedder.model_id)
            if embedding is not None:
                distance = cosine_distance(query_embedding, embedding)
                scored.append((distance, position, chunk))
            position += 1
        scored.sort()
        results: list[dict[str, Any]] = []
        for distance, _, chunk in scored[:limit]:
            results.append(
                {
                    "id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "content": chunk["content"],
                    "metadata": copy.deepcopy(chunk["metadata"]),
                    "distance": distance,
                }
            )
        return results
