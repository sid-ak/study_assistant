"""The concrete pgvector-backed ``Store`` — the DB implementation of ``StoreProtocol``."""

from typing import Any
from uuid import UUID

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from rag_core.config import settings
from rag_core.store.schema import SCHEMA_SQL


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

    def initialize_schema(self) -> None:
        """Idempotently creates extension and tables."""
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

    # TODO: Consider handling partial success in batch inserts.
    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        user_id: UUID | None = None,
    ) -> None:
        """Batch insert chunks.

        Expected chunk dict: {id, document_id, content, metadata, embedding}
        """
        uid = user_id or settings.default_user_id
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                copy_sql = (
                    "COPY chunks (id, document_id, content, metadata, embedding, user_id) "
                    "FROM STDIN WITH (FORMAT BINARY)"
                )
                with cur.copy(copy_sql) as copy:
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

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return every chunk row belonging to ``document_id``, or ``[]`` if none exist."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT id, document_id, content, metadata, embedding, user_id "
                "FROM chunks WHERE document_id = %s",
                (document_id,),
            )
            return cur.fetchall()
