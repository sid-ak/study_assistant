# 8. Per-Model Embedding Columns

- Status: Accepted
- Date: 2026-07-02

## Context

[ADR 0002](0002-local-embedding-and-reranking.md) pins `bge-m3` and notes that its output dimension
is baked into the pgvector `vector(N)` column and its index, so changing embedders means a re-embed
plus a schema migration — the "main lock-in." Today `chunks` has a single `embedding vector(1024)`
column with one HNSW index, and the dimension is read from the global `settings.embedding_dimension`
at import time inside `store/schema.py`.

Two problems follow from that shape:

- The dimension is a global config value, read at import to build the schema SQL, so the store and
  its schema are coupled to a global settings read rather than told the dimension explicitly.
- One shared column means switching embedders is a destructive, in-place `ALTER` of the single
  column that every row and every query depends on. Old and new embeddings cannot coexist, so the
  swap is all-or-nothing and blocking: the table is mid-migration until every chunk is re-embedded.

The [interface-first work](0006-interface-first-architecture.md) makes the embedder swappable in
code; this ADR addresses the schema side so a swap is not destructive in storage.

## Decision

Two changes, together making an embedder swap additive rather than in-place.

- Dimension as an explicit parameter. Move the embedding dimension off the global
  `settings.embedding_dimension` and pass it explicitly when an embedder is registered/initialized.
  This decouples the schema and store from a global settings read. It is a hygiene fix — on its own
  it does not remove the migration cost of switching embedders, it only removes the global coupling.
- Per-model embedding columns. Each active embedder gets its own `vector(N)` column and its own
  index, tagged by a model identifier — e.g. `embedding_bge_m3 vector(1024)` with a dedicated HNSW
  index — plus a recorded marker of which model is "current." Adding an embedder becomes an additive
  schema change (a new column and a new index), not an in-place `ALTER` of a shared column. Old and
  new embeddings coexist during a migration, and the old column is dropped only once the new one is
  fully backfilled and validated.

## Consequences

- Embedder swaps become additive and reversible instead of destructive and blocking: backfill the
  new column alongside the old, validate with the golden-set eval (ADR 0002), flip the "current"
  marker, then drop the old column. A failed or in-progress migration leaves the existing column
  intact and queryable.
- This does not eliminate the underlying constraint that pgvector — and every ANN index, HNSW
  included — requires a fixed dimension per column and per index at creation time. That is
  structural to vector indexes generally, not specific to this project. What changes is scope: the
  fixed- dimension constraint stops applying globally to the whole table and becomes local to one
  column, so a swap is an additive column rather than a table-wide rebuild.
- Cost while two embedders are active: extra columns and indexes, so more storage and more write
  work during a migration. Ingestion writes and retrieval reads must target the current model's
  column, selected by the "current" marker.
- This refines the "main lock-in" framing in ADR 0002 and ADR 0006: the dimension is still fixed per
  column, but it no longer gates the whole table. The future embedding-stack change contemplated in
  Future Scope (e.g. a hosted Voyage pairing on a cloud move) is a re-embed into a new column, not a
  blocking rebuild of the shared one.
