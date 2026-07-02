-- Runs once on first initialization of an empty Postgres data volume.
-- Phase 0 only makes the pgvector extension available; tables and the vector(N)
-- columns are added in Phase 1 (rag_core/store).
CREATE EXTENSION IF NOT EXISTS vector;

-- Second database on the same instance, used only by integration tests so their table-wide
-- teardown never touches real ingested data. POSTGRES_DB auto-creates only one database, so the
-- test database must be created explicitly here. Keep this name in sync with POSTGRES_TEST_DB /
-- TEST_DATABASE_URL in .env. The pgvector extension is created inside it by
-- Store.initialize_schema() when the tests first connect.
CREATE DATABASE study_assistant_test;
