"""The concrete pgvector-backed ``Store`` — the DB implementation of ``StoreProtocol``."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from rag_core.config import settings
from rag_core.store.connection import connect, resolve_database_url
from rag_core.store.embedders import EmbedderInfo
from rag_core.store.errors import EmbedderNotFoundError, MissingDocumentError
from rag_core.store.schema import SCHEMA_SQL, embedding_column
from rag_core.store.validation import check_dimensions


class Store:
    """Store client for pgvector-backed RAG storage."""

    def __init__(self, database_url: str | None = None, *, embedder: EmbedderInfo) -> None:
        """Bind to ``database_url`` (or ``settings.database_url``) and to ``embedder``.

        Does not open a connection.
        """
        self.database_url = resolve_database_url(database_url)
        self.embedder = embedder

    def with_embedder(self, embedder: EmbedderInfo) -> "Store":
        """Return a store on the same database, bound to ``embedder``."""
        return Store(self.database_url, embedder=embedder)

    @contextmanager
    def _embedder_column(self) -> Iterator[sql.Identifier]:
        """Yield this store's embedding column, translating a missing column into a typed error."""
        try:
            yield sql.Identifier(embedding_column(self.embedder.model_id))
        except psycopg.errors.UndefinedColumn as e:
            raise EmbedderNotFoundError(
                f"Embedder {self.embedder.model_id!r} is not registered; register it first."
            ) from e

    def initialize(self) -> None:
        """Idempotently create the pgvector extension, tables, and indexes."""
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            conn.execute(SCHEMA_SQL)

    def get_connection(self) -> psycopg.Connection[Any]:
        """Returns a connection with vector support registered."""
        return connect(self.database_url)

    def add_document(
        self,
        id: UUID,
        filename: str,
        file_hash: str,
        user_id: UUID | None = None,
    ) -> UUID:
        """Insert document metadata idempotently, returning the stored document id.

        On re-ingest of the same ``file_hash`` the existing row is kept (its id is
        returned and the filename refreshed), so callers can re-run ingestion safely.
        """
        uid = user_id or settings.default_user_id
        with self.get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO documents (id, filename, file_hash, user_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (file_hash) DO UPDATE SET filename = EXCLUDED.filename
                RETURNING id
                """,
                (id, filename, file_hash, uid),
            )
            row = cur.fetchone()
            assert row is not None  # RETURNING on upsert always yields a row
            stored_id: UUID = row["id"]
            return stored_id

    def update_document(self, id: UUID, filename: str) -> None:
        """Update mutable document metadata (currently just the filename)."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE documents SET filename = %s WHERE id = %s",
                (filename, id),
            )

    def delete_document(self, id: UUID) -> None:
        """Delete a document and its chunks (chunks cascade on the FK)."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM documents WHERE id = %s", (id,))

    def get_document_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        """Find a document by its file hash."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT id, filename, file_hash, user_id FROM documents WHERE file_hash = %s",
                (file_hash,),
            )
            return cur.fetchone()

    # TODO: Consider handling partial success in batch inserts.
    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_id: UUID | None = None,
    ) -> None:
        """Batch insert chunks, writing each embedding into this store's embedder's column.

        Expected chunk dict: {id, document_id, content, metadata, embedding}
        """
        uid = user_id or settings.default_user_id
        check_dimensions(chunks, self.embedder)
        with self.get_connection() as conn, self._embedder_column() as column:
            copy_sql = sql.SQL(
                "COPY chunks (id, document_id, content, metadata, {}, user_id) "
                "FROM STDIN WITH (FORMAT BINARY)"
            ).format(column)
            try:
                with conn.cursor() as cur, cur.copy(copy_sql) as copy:
                    copy.set_types(["uuid", "uuid", "text", "jsonb", "vector", "uuid"])
                    for chunk in chunks:
                        copy.write_row(
                            (
                                chunk["id"],
                                chunk["document_id"],
                                chunk["content"],
                                Jsonb(chunk["metadata"]),
                                chunk["embedding"],
                                uid,
                            )
                        )
            except psycopg.errors.ForeignKeyViolation as e:
                raise MissingDocumentError(str(e)) from e

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return every chunk row belonging to ``document_id``, or ``[]`` if none exist.

        ``embedding`` is this store's embedder's vector, or ``None`` if it has not embedded the
        chunk.
        """
        with self.get_connection() as conn, self._embedder_column() as column:
            query = sql.SQL(
                "SELECT id, document_id, content, metadata, {} AS embedding, user_id "
                "FROM chunks WHERE document_id = %s"
            ).format(column)
            return conn.execute(query, (document_id,)).fetchall()
