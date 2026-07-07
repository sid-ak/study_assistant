"""The store interface.

``StoreProtocol`` is the structural contract retrieval and ingestion code depends on, so callers
never bind to the concrete ``Store`` (pgvector) or to raw driver calls. ``Store`` conforms by shape,
and ``InMemoryStore`` is a lightweight fake satisfying the same contract for unit tests with no live
database.

``get_connection`` is intentionally absent: it returns a raw ``psycopg`` connection, a driver
dependency retrieval logic should stay clear of. Integration tests use it on the concrete ``Store``
directly.
"""

from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class StoreProtocol(Protocol):
    """Structural interface for pgvector-backed document/chunk storage."""

    def initialize_schema(self) -> None:
        """Idempotently create the extension and tables."""
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
        """Delete a document and its chunks (chunks cascade)."""
        ...

    def get_document_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        """Find a document by its file hash, or ``None`` if absent."""
        ...

    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_id: UUID | None = None,
    ) -> None:
        """Batch insert chunks: ``{id, document_id, content, metadata, embedding}``."""
        ...

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return every chunk belonging to ``document_id``, or ``[]`` if none exist."""
        ...
