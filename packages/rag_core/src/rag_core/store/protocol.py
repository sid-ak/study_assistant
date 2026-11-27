"""The store interface.

``StoreProtocol`` is the structural contract retrieval and ingestion code depends on, so callers
never bind to a concrete implementation or its storage backend. Implementations conform by shape;
the ones that exist are exported from ``rag_core.store``.

The contract describes behavior only. Backend handles such as connections are deliberately not
part of it, so code typed against the protocol cannot reach past it into a particular backend.
"""

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from rag_core.store.embedders.protocol import EmbedderInfo


@runtime_checkable
class StoreProtocol(Protocol):
    """Structural interface for document and chunk storage, independent of any backend."""

    @property
    def embedder(self) -> EmbedderInfo:
        """The embedding model this store writes and reads vectors for."""
        ...

    def with_embedder(self, embedder: EmbedderInfo) -> "StoreProtocol":
        """Return a store over the same documents and chunks, bound to ``embedder``.

        The original store is unchanged, so stores for several models can be used side by side.
        ``embedder`` must already be registered with the embedder registry.
        """
        ...

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
        """Insert document metadata idempotently, returning the stored document id.

        Re-adding a ``file_hash`` that is already stored keeps that document's id and refreshes
        its filename. Raises ``DuplicateIdError`` if ``id`` belongs to a document with another
        ``file_hash``; the stored document is left unchanged.
        """
        ...

    def update_document(self, id: UUID, filename: str) -> None:
        """Update mutable document metadata (currently just the filename)."""
        ...

    def delete_document(self, id: UUID) -> None:
        """Delete a document and every chunk that belongs to it."""
        ...

    def get_document_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        """Find a document by its file hash, or ``None`` if absent.

        The result is a copy; mutating it does not change the stored document.
        """
        ...

    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_id: UUID | None = None,
    ) -> None:
        """Batch insert chunks: ``{id, document_id, content, metadata, embedding}``.

        The embedding is stored under this store's ``embedder``. The batch is all-or-nothing and
        raises ``EmbedderNotFoundError`` (the embedder is not registered),
        ``EmbeddingDimensionError`` (wrong length), ``MissingDocumentError`` (unknown
        ``document_id``), or ``DuplicateIdError`` (a chunk id that is already stored or repeats
        within the batch). Stored chunks are never overwritten.
        """
        ...

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return every chunk belonging to ``document_id``, or ``[]`` if none exist.

        Chunks come back in the order they were added, across batches. Each is a copy; mutating it
        does not change the stored chunk, and the store keeps its own copy of what ``add_chunks``
        was given.

        Each chunk's ``embedding`` is this store's ``embedder``'s vector, or ``None`` if that model
        has not embedded the chunk yet. Raises ``EmbedderNotFoundError`` if the embedder is not
        registered.
        """
        ...

    def get_unembedded_chunks(self, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` chunks this store's ``embedder`` has not embedded yet.

        Each is ``{id, content}``, in the order the chunks were added. These are the chunks a
        newly registered model needs vectors for. Raises ``ValueError`` if ``limit`` is below one
        and ``EmbedderNotFoundError`` if the embedder is not registered.
        """
        ...

    def set_embeddings(self, embeddings: list[dict[str, Any]]) -> None:
        """Store each ``{id, embedding}`` as this store's ``embedder``'s vector for that chunk.

        A vector the embedder already stored for the chunk is replaced. Other models' vectors and
        the chunk's other fields are unchanged. The batch is all-or-nothing and raises
        ``EmbedderNotFoundError`` (the embedder is not registered), ``EmbeddingDimensionError``
        (wrong length), ``ZeroEmbeddingError`` (all zeros), ``MissingChunkError`` (an id with no
        stored chunk), or ``DuplicateIdError`` (an id repeated within the batch).
        """
        ...

    def search_lexical(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` chunks containing words of ``query``, best match first.

        Matching is by words, not meaning: a chunk is a match when it contains at least one of the
        query's words, after both are reduced to their stems and common words such as "the" are
        dropped. Each result holds the chunk's ``id``, ``document_id``, ``content``, and a copy of
        its ``metadata``, plus a positive ``score`` that orders the matches. It reads no embedding,
        so any store finds the same chunks whatever model it is bound to. A query with no usable
        word returns ``[]``. Raises ``ValueError`` if ``limit`` is below one.
        """
        ...

    def search_dense(
        self, query_embedding: Sequence[float], limit: int, ef_search: int | None = None
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` chunks nearest to ``query_embedding``, nearest first.

        Nearness is cosine distance, ``1 - cosine similarity``, from 0 (same direction) to 2
        (opposite). Each result holds the chunk's ``id``, ``document_id``, ``content``, and a copy
        of its ``metadata``, plus its ``distance``. Only chunks this store's ``embedder`` has
        embedded are searched. Equally distant chunks come back in no defined order.

        The search may be approximate: it can miss a chunk an exhaustive comparison would rank in
        the top ``limit``. ``ef_search``, when given, sets how many candidates an approximate
        search keeps while it runs, from 1 to 1000 and at least ``limit``; larger values find
        more of the true nearest chunks and take longer. ``None`` keeps the backend's default.

        Raises ``EmbeddingDimensionError`` if the query's length is not the embedder's dimension,
        ``ZeroEmbeddingError`` if the query is all zeros, ``ValueError`` if ``limit`` is below one
        or ``ef_search`` is out of range, and ``EmbedderNotFoundError`` if the embedder is not
        registered.
        """
        ...
