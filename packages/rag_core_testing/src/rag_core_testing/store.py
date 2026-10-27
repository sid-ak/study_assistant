"""In-memory fake of ``StoreProtocol`` for unit tests.

A lightweight fake so tests that only need storage semantics — not real pgvector — run without a
database. It mirrors the concrete ``Store``'s CRUD contract: hash-keyed idempotent document upsert,
the chunk -> document foreign key with cascade on delete, per-model embeddings with one model per
store instance, and the same ``user_id`` default. It does not model vector or full-text search;
those are exercised by the DB-backed integration tests against ``Store``.
"""

import copy
from typing import Any
from uuid import UUID

from rag_core.config import settings
from rag_core.store.embedders import EmbedderInfo
from rag_core.store.errors import MissingDocumentError
from rag_core.store.validation import check_dimensions


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
