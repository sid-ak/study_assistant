-- Runs once on first initialization of an empty Postgres data volume.
-- Phase 0 only makes the pgvector extension available; tables and the vector(N)
-- columns are added in Phase 1 (rag_core/store).
CREATE EXTENSION IF NOT EXISTS vector;
