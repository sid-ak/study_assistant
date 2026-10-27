"""SQL schema for documents, chunks, and the embedding-model registry, with pgvector support.

Schema evolution has two parts:

- ``Store.initialize_schema`` runs the idempotent ``CREATE ... IF NOT EXISTS`` bootstrap below.
- Embedding storage grows additively (ADR 0008). ``Store.register_embedder`` records each model in
  ``embedding_models`` and adds that model's own ``vector(N)`` column and HNSW index to ``chunks``,
  so a new embedder sits beside the old one instead of altering a shared column.

Re-embedding into a new model's column and dropping the old one is tracked by issue #15.
"""

import re

# Postgres truncates identifiers longer than 63 bytes. Column names stop short of that so the
# index name, which appends INDEX_SUFFIX, still fits.
INDEX_SUFFIX = "_hnsw"
MAX_COLUMN_LENGTH = 63 - len(INDEX_SUFFIX)
COLUMN_PREFIX = "embedding_"

SCHEMA_SQL = """
-- Ensure vector extension exists
CREATE EXTENSION IF NOT EXISTS vector;

-- Documents table: Tracks source files
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    -- UNIQUE makes re-ingesting the same file idempotent (upsert target below) and
    -- doubles as the lookup index for get_document_by_hash. Single-user scope keys on
    -- file_hash alone; multi-user would migrate this to (user_id, file_hash).
    file_hash TEXT NOT NULL UNIQUE,
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Chunks table: Stores semantic segments. Embeddings live in per-model columns that
-- register_embedder adds (ADR 0008), so none is declared here.
CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Embedding-model registry: one row per model, naming its chunks column and fixed dimension.
CREATE TABLE IF NOT EXISTS embedding_models (
    model_id TEXT PRIMARY KEY,
    column_name TEXT NOT NULL UNIQUE,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- At most one model is current: writes and reads target its column.
CREATE UNIQUE INDEX IF NOT EXISTS idx_embedding_models_current
ON embedding_models (is_current) WHERE is_current;

-- GIN index for full-text search (BM25)
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING gin(tsv);

-- Index on document_id for fast cleanup/retrieval
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
"""


def embedding_column(model_id: str) -> str:
    """Name the ``chunks`` column that holds ``model_id``'s embeddings (ADR 0008).

    Raises ``ValueError`` if the id has no usable characters or the name would exceed Postgres's
    63-byte identifier limit once the index suffix is added.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", model_id.lower()).strip("_")
    if not slug:
        raise ValueError(f"Embedder id {model_id!r} has no letters or digits to name a column.")
    column = COLUMN_PREFIX + slug
    if len(column) > MAX_COLUMN_LENGTH:
        raise ValueError(
            f"Embedder id {model_id!r} gives column {column!r}, longer than {MAX_COLUMN_LENGTH}."
        )
    return column


def embedding_index(column: str) -> str:
    """Name the HNSW index on an embedding column."""
    return column + INDEX_SUFFIX
