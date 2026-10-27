"""The pgvector-backed ``EmbedderRegistry``, the DB implementation of the registry protocol."""

import psycopg
from psycopg import sql

from rag_core.store.connection import connect, resolve_database_url
from rag_core.store.embedders.protocol import EmbedderInfo
from rag_core.store.errors import EmbedderConflictError, EmbedderNotFoundError
from rag_core.store.schema import embedding_column, embedding_index


class EmbedderRegistry:
    """Registry kept in the ``embedding_models`` table, with per-model ``chunks`` columns.

    Expects the schema that ``Store.initialize`` creates.
    """

    def __init__(self, database_url: str | None = None) -> None:
        """Bind to ``database_url`` (or ``settings.database_url``); does not open a connection."""
        self.database_url = resolve_database_url(database_url)

    def register(self, model_id: str, dimension: int) -> None:
        """Register a model and add its own ``vector(N)`` column and HNSW index to ``chunks``.

        Idempotent for the same ``(model_id, dimension)``. Raises ``EmbedderConflictError`` if the
        model is registered with another dimension, or another model already maps to its column.
        """
        column = embedding_column(model_id)
        with connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT dimension FROM embedding_models WHERE model_id = %s", (model_id,)
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

    def set_current(self, model_id: str) -> None:
        """Make ``model_id`` current; raises ``EmbedderNotFoundError`` if it is not registered."""
        with connect(self.database_url) as conn:
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

    def get_current(self) -> EmbedderInfo | None:
        """Return the current embedder, or ``None`` if none has been set."""
        with connect(self.database_url) as conn:
            row = conn.execute(
                "SELECT model_id, dimension FROM embedding_models WHERE is_current"
            ).fetchone()
        return None if row is None else EmbedderInfo(row["model_id"], row["dimension"])
