"""In-memory fake of ``StoreProtocol`` for unit tests.

A lightweight fake so tests that only need storage semantics — not real pgvector — run without a
database. It mirrors the concrete ``Store``'s CRUD contract: hash-keyed idempotent document upsert,
the chunk -> document foreign key with cascade on delete, per-model embeddings read through an
embedder registry, and the same ``user_id`` default. It does not model vector or full-text search;
those are exercised by the DB-backed integration tests against ``Store``.
"""

from typing import Any
from uuid import UUID

from rag_core.config import settings
from rag_core.store.embedders import EmbedderRegistryProtocol
from rag_core.store.errors import MissingDocumentError
from rag_core.store.validation import check_dimensions, require_current
from rag_core_testing.embedders import InMemoryEmbedderRegistry


class InMemoryStore:
    """Dict-backed fake conforming to ``StoreProtocol``."""

    def __init__(self, embedders: EmbedderRegistryProtocol | None = None) -> None:
        """Start empty, keyed by document / chunk id (document rows mirror Store's SELECT shape).

        ``embedders`` supplies the current embedder; it defaults to an in-memory registry.
        """
        self.embedders = embedders or InMemoryEmbedderRegistry()
        self.documents: dict[UUID, dict[str, Any]] = {}
        # Each chunk keeps an ``embeddings`` map of model id -> vector, the per-model columns.
        self.chunks: dict[UUID, dict[str, Any]] = {}

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
        """Store each chunk by id, all-or-nothing, with its embedding under the current model."""
        uid = user_id or settings.default_user_id
        embedder = require_current(self.embedders.get_current())
        check_dimensions(chunks, embedder)
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
                "metadata": chunk["metadata"],
                "embeddings": {embedder.model_id: list(chunk["embedding"])},
                "user_id": uid,
            }

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return copies of every chunk belonging to ``document_id``, or ``[]`` if none.

        ``embedding`` is the current model's vector, or ``None`` if it has not embedded the chunk.
        """
        current = self.embedders.get_current()
        model_id = None if current is None else current.model_id
        return [
            {
                "id": c["id"],
                "document_id": c["document_id"],
                "content": c["content"],
                "metadata": c["metadata"],
                "embedding": c["embeddings"].get(model_id),
                "user_id": c["user_id"],
            }
            for c in self.chunks.values()
            if c["document_id"] == document_id
        ]
