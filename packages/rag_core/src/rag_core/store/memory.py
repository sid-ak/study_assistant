"""In-memory ``StoreProtocol`` implementation for unit tests.

A lightweight fake so tests that only need storage semantics — not real pgvector — run without a
database. It mirrors the concrete ``Store``'s CRUD contract: hash-keyed idempotent document upsert,
FK-style cascade on delete, and the same ``user_id`` default. It does not model vector or full-text
search; those are exercised by the DB-backed integration tests against ``Store``.
"""

from typing import Any
from uuid import UUID

from rag_core.config import settings


class InMemoryStore:
    """Dict-backed fake conforming to ``StoreProtocol``."""

    def __init__(self) -> None:
        """Start empty, keyed by document / chunk id (document rows mirror Store's SELECT shape)."""
        self.documents: dict[UUID, dict[str, Any]] = {}
        self.chunks: dict[UUID, dict[str, Any]] = {}

    def initialize_schema(self) -> None:
        """No-op: an in-memory store has no schema to create."""

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
        # Cascade: drop chunks belonging to the document.
        self.chunks = {
            cid: chunk for cid, chunk in self.chunks.items() if chunk["document_id"] != id
        }

    def get_document_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        """Return a copy of the document with this file_hash, or None if absent."""
        for doc in self.documents.values():
            if doc["file_hash"] == file_hash:
                return dict(doc)
        return None

    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_id: UUID | None = None,
    ) -> None:
        """Store each chunk by id: ``{id, document_id, content, metadata, embedding}``."""
        uid = user_id or settings.default_user_id
        for chunk in chunks:
            self.chunks[chunk["id"]] = {
                "id": chunk["id"],
                "document_id": chunk["document_id"],
                "content": chunk["content"],
                "metadata": chunk["metadata"],
                "embedding": chunk["embedding"],
                "user_id": uid,
            }

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return copies of every chunk belonging to ``document_id``, or ``[]`` if none."""
        return [dict(c) for c in self.chunks.values() if c["document_id"] == document_id]
