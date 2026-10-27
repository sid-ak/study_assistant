"""The concrete pgvector-backed ``Store`` — the DB implementation of ``StoreProtocol``."""

from typing import Any
from uuid import UUID

import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from rag_core.config import settings
from rag_core.store.errors import (
    EmbedderConflictError,
    EmbedderNotFoundError,
    MissingDocumentError,
)
from rag_core.store.protocol import EmbedderInfo
from rag_core.store.schema import SCHEMA_SQL, embedding_column, embedding_index
from rag_core.store.validation import check_dimensions, require_current


class Store:
    """Store client for pgvector-backed RAG storage."""

    def __init__(self, database_url: str | None = None) -> None:
        """Bind to ``database_url`` (or ``settings.database_url``); does not open a connection."""
        url = database_url or settings.database_url
        if url is None:
            raise RuntimeError(
                "No database URL configured. Pass Store(database_url=...) or set DATABASE_URL "
                "in the environment / .env (see .env.example)."
            )
        self.database_url = url

    def initialize(self) -> None:
        """Idempotently create the pgvector extension, tables, and indexes."""
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            conn.execute(SCHEMA_SQL)

    def get_connection(self) -> psycopg.Connection[Any]:
        """Returns a connection with vector support registered."""
        conn = psycopg.connect(self.database_url, row_factory=dict_row)
        register_vector(conn)
        return conn

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

    def register_embedder(self, model_id: str, dimension: int) -> None:
        """Register a model and add its own ``vector(N)`` column and HNSW index to ``chunks``.

        Idempotent for the same ``(model_id, dimension)``. Raises ``EmbedderConflictError`` if the
        model is registered with another dimension, or another model already maps to its column.
        """
        column = embedding_column(model_id)
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT dimension, column_name FROM embedding_models WHERE model_id = %s",
                (model_id,),
            ).fetchone()
            if row is not None and row["dimension"] != dimension:
                raise EmbedderConflictError(
                    f"{model_id!r} is registered with dimension {row['dimension']}, "
                    f"not {dimension}."
                )
            if row is None:
                try:
                    conn.execute(
                        "INSERT INTO embedding_models (model_id, column_name, dimension) "
                        "VALUES (%s, %s, %s)",
                        (model_id, column, dimension),
                    )
                except psycopg.errors.UniqueViolation as e:
                    raise EmbedderConflictError(
                        f"Column {column!r} for {model_id!r} already belongs to another embedder."
                    ) from e
            # The dimension is DDL, not a bind parameter; it is an int, so Literal is safe.
            conn.execute(
                sql.SQL("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS {} vector({})").format(
                    sql.Identifier(column), sql.Literal(dimension)
                )
            )
            conn.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {} ON chunks USING hnsw ({} vector_cosine_ops)"
                ).format(sql.Identifier(embedding_index(column)), sql.Identifier(column))
            )

    def set_current_embedder(self, model_id: str) -> None:
        """Make ``model_id`` current; raises ``EmbedderNotFoundError`` if it is not registered."""
        with self.get_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM embedding_models WHERE model_id = %s", (model_id,)
            ).fetchone()
            if exists is None:
                raise EmbedderNotFoundError(f"Embedder {model_id!r} is not registered.")
            # Two statements, not one: the partial unique index on is_current is checked per row,
            # so flipping the old and new rows in one UPDATE can briefly hold two current rows.
            conn.execute("UPDATE embedding_models SET is_current = FALSE WHERE is_current")
            conn.execute(
                "UPDATE embedding_models SET is_current = TRUE WHERE model_id = %s", (model_id,)
            )

    def get_current_embedder(self) -> EmbedderInfo | None:
        """Return the current embedder, or ``None`` if none has been set."""
        with self.get_connection() as conn:
            return self._current_embedder(conn)

    @staticmethod
    def _current_embedder(conn: psycopg.Connection[Any]) -> EmbedderInfo | None:
        """Read the current embedder on an open connection."""
        row = conn.execute(
            "SELECT model_id, dimension FROM embedding_models WHERE is_current"
        ).fetchone()
        return None if row is None else EmbedderInfo(row["model_id"], row["dimension"])

    # TODO: Consider handling partial success in batch inserts.
    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_id: UUID | None = None,
    ) -> None:
        """Batch insert chunks, writing each embedding into the current embedder's column.

        Expected chunk dict: {id, document_id, content, metadata, embedding}
        """
        uid = user_id or settings.default_user_id
        with self.get_connection() as conn:
            embedder = require_current(self._current_embedder(conn))
            check_dimensions(chunks, embedder)
            copy_sql = sql.SQL(
                "COPY chunks (id, document_id, content, metadata, {}, user_id) "
                "FROM STDIN WITH (FORMAT BINARY)"
            ).format(sql.Identifier(embedding_column(embedder.model_id)))
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

        ``embedding`` is the current embedder's vector, or ``None`` if it has not embedded the chunk
        or no embedder is current.
        """
        with self.get_connection() as conn:
            embedder = self._current_embedder(conn)
            embedding = (
                sql.SQL("NULL")
                if embedder is None
                else sql.Identifier(embedding_column(embedder.model_id))
            )
            query = sql.SQL(
                "SELECT id, document_id, content, metadata, {} AS embedding, user_id "
                "FROM chunks WHERE document_id = %s"
            ).format(embedding)
            return conn.execute(query, (document_id,)).fetchall()
