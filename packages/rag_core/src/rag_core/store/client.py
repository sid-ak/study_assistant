"""The concrete pgvector-backed ``Store`` — the DB implementation of ``StoreProtocol``."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from pgvector import Vector
from psycopg import sql
from psycopg.types.json import Jsonb

from rag_core.config import settings
from rag_core.store.connection import connect, resolve_database_url
from rag_core.store.embedders import EmbedderInfo
from rag_core.store.errors import (
    DuplicateIdError,
    EmbedderNotFoundError,
    MissingChunkError,
    MissingDocumentError,
)
from rag_core.store.schema import SCHEMA_SQL, embedding_column
from rag_core.store.validation import (
    check_dimensions,
    check_limit,
    check_search,
    check_unique_ids,
)


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
        Raises ``DuplicateIdError`` if ``id`` belongs to a document with another file hash.
        """
        uid = user_id or settings.default_user_id
        with self.get_connection() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO documents (id, filename, file_hash, user_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (file_hash) DO UPDATE SET filename = EXCLUDED.filename
                    RETURNING id
                    """,
                    (id, filename, file_hash, uid),
                )
            # ON CONFLICT handles a clash on file_hash, so the only unique violation left is
            # the primary key: ``id`` is already taken by a document with another file hash.
            except psycopg.errors.UniqueViolation as e:
                raise DuplicateIdError(str(e)) from e
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
            # The primary key is the only unique constraint on chunks, so this is a chunk id
            # that is already stored or repeats within the batch.
            except psycopg.errors.UniqueViolation as e:
                raise DuplicateIdError(str(e)) from e

    def get_chunks_by_document(self, document_id: UUID) -> list[dict[str, Any]]:
        """Return every chunk row belonging to ``document_id``, or ``[]`` if none exist.

        ``embedding`` is this store's embedder's vector, or ``None`` if it has not embedded the
        chunk.
        """
        with self.get_connection() as conn, self._embedder_column() as column:
            query = sql.SQL(
                "SELECT id, document_id, content, metadata, {} AS embedding, user_id "
                "FROM chunks WHERE document_id = %s ORDER BY seq"
            ).format(column)
            return conn.execute(query, (document_id,)).fetchall()

    def get_unembedded_chunks(self, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` chunks whose column for this store's embedder is still NULL.

        Rows are ``{id, content}`` ordered by ``seq``, the order the chunks were added.
        """
        check_limit(limit)
        with self.get_connection() as conn, self._embedder_column() as column:
            query = sql.SQL(
                "SELECT id, content FROM chunks WHERE {} IS NULL ORDER BY seq LIMIT %s"
            ).format(column)
            return conn.execute(query, (limit,)).fetchall()

    def set_embeddings(self, embeddings: list[dict[str, Any]]) -> None:
        """Write each ``{id, embedding}`` into this store's embedder's column, in one transaction.

        Each row is one ``UPDATE``; a row that updates nothing names no chunk, and raising inside
        the connection's ``with`` block rolls back the rows already updated.
        """
        check_dimensions(embeddings, self.embedder)
        check_unique_ids(embeddings)
        with self.get_connection() as conn, self._embedder_column() as column:
            update = sql.SQL("UPDATE chunks SET {} = %s WHERE id = %s").format(column)
            for row in embeddings:
                # Vector binds as pgvector's own type, as in search_dense.
                cursor = conn.execute(update, (Vector(list(row["embedding"])), row["id"]))
                if cursor.rowcount == 0:
                    raise MissingChunkError(f"No stored chunk has id {row['id']}.")

    def search_lexical(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` chunks containing words of ``query``, best ``ts_rank`` first.

        ``plainto_tsquery`` stems the query and drops stop words, joining the rest with AND, which a
        full question rarely satisfies. Replacing each ``&`` with ``|`` makes it match any of the
        words; ``ts_rank`` then scores chunks that contain more of them, more often, higher. The
        ``tsv`` column and its GIN index hold each chunk's stemmed words.
        """
        check_limit(limit)
        query_sql = (
            "SELECT id, document_id, content, metadata, ts_rank(tsv, q) AS score "
            "FROM chunks, "
            "CAST(replace(plainto_tsquery('english', %(query)s)::text, ' & ', ' | ') AS tsquery) q "
            "WHERE tsv @@ q ORDER BY score DESC LIMIT %(limit)s"
        )
        with self.get_connection() as conn:
            return conn.execute(query_sql, {"query": query, "limit": limit}).fetchall()

    def search_dense(
        self, query_embedding: Sequence[float], limit: int, ef_search: int | None = None
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` chunks nearest to ``query_embedding`` by cosine distance.

        ``ORDER BY <column> <=> query LIMIT n`` is the shape the column's HNSW index serves, so the
        search is approximate once the planner uses the index. No tie-breaking column is added to
        the ``ORDER BY``: a second sort key stops Postgres from using the index.

        ``ef_search`` is set with ``set_config(..., true)``, which lasts only until the end of this
        connection's transaction, so it never leaks into another search.
        """
        check_search(query_embedding, limit, self.embedder, ef_search)
        with self.get_connection() as conn, self._embedder_column() as column:
            if ef_search is not None:
                # SET cannot take a bind parameter; set_config can. The third argument, true,
                # makes the setting local to the current transaction.
                conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(ef_search),))
            query = sql.SQL(
                "SELECT id, document_id, content, metadata, {column} <=> %(query)s AS distance "
                "FROM chunks WHERE {column} IS NOT NULL "
                "ORDER BY {column} <=> %(query)s LIMIT %(limit)s"
            ).format(column=column)
            # A plain list binds as double precision[], which has no <=> operator; Vector binds as
            # pgvector's own type.
            parameters = {"query": Vector(list(query_embedding)), "limit": limit}
            return conn.execute(query, parameters).fetchall()
