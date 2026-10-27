"""The store interface.

``StoreProtocol`` is the structural contract retrieval and ingestion code depends on, so callers
never bind to a concrete implementation or its storage backend. Implementations conform by shape;
the ones that exist are exported from ``rag_core.store``.

The contract describes behavior only. Backend handles such as connections are deliberately not
part of it, so code typed against the protocol cannot reach past it into a particular backend.
"""

from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class StoreProtocol(Protocol):
    """Structural interface for document and chunk storage, independent of any backend."""

    def initialize(self) -> None:
        """Idempotently prepare the backing storage for use; safe to call more than once."""
        ...

    def add_document(
        self,
        id: UUID,
        filename: str,
        file_hash: str,
        user_id: UUID | None = None,
    ) -> UUID:
        """Insert document metadata idempotently, returning the stored document id."""
        ...

    def update_document(self, id: UUID, filename: str) -> None:
        """Update mutable document metadata (currently just the filename)."""
        ...

    def delete_document(self, id: UUID) -> None:
        """Delete a document and every chunk that belongs to it."""
        ...

    def get_document_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        """Find a document by its file hash, or ``None`` if absent."""
        ...

    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_id: UUID | None = None,
    ) -> None:
        """Batch insert chunks: ``{id, document_id, content, metadata, embedding}``.

        The embedding is stored under the current embedder of the registry the store was built
        with (``rag_core.store.embedders``). The batch is all-or-nothing and raises
        ``EmbedderNotFoundError`` (no current embedder), ``EmbeddingDimensionError`` (wrong
        length), or ``MissingDocumentError`` (unknown ``document_id``).
        """
        ...

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return every chunk belonging to ``document_id``, or ``[]`` if none exist.

        Each chunk's ``embedding`` is the current embedder's vector, or ``None`` if that model has
        not embedded the chunk yet.
        """
        ...
