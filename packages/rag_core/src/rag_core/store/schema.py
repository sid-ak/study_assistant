"""SQL schema for documents and chunks with pgvector support.

Schema evolution is handled by ``Store.initialize_schema`` running this idempotent
``CREATE ... IF NOT EXISTS`` bootstrap. A versioned migration mechanism is deferred until the
first breaking change actually needs one — most likely the re-embed / ``vector(N)`` dimension
change tracked by issue #15. Until then there is no existing data to migrate.
"""

from rag_core.config import settings

# Extension and Tables
SCHEMA_SQL = f"""
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

-- Chunks table: Stores semantic segments and embeddings
CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{{}}',
    embedding vector({settings.embedding_dimension}) NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for vector similarity search (cosine distance)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks 
USING hnsw (embedding vector_cosine_ops);

-- GIN index for full-text search (BM25)
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING gin(tsv);

-- Index on document_id for fast cleanup/retrieval
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
"""
