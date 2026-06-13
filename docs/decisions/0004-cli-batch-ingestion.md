# 4. Document ingestion: CLI batch

- Status: Accepted
- Date: 2026-06-13

## Context

Course materials (slides, papers, notes) need to get into the system: parsed, semantically
chunked, embedded, and stored in pgvector. How documents enter shapes early architecture. Two
primary approaches were considered:

1. **CLI batch** — a command points at a folder and runs the pipeline. Best fit for a personal
   corpus the user controls on disk; re-runnable and scriptable, and it needs no upload UI or job
   queue, keeping early phases lean.
2. **UI upload + async worker** — files are uploaded through the React app and processed by a
   background worker. Nicer UX, but it adds a job queue, a worker service, and upload/status
   endpoints up front — more moving parts before retrieval even works.

A third "both, CLI now / UI later" framing was also considered; in practice that reduces to "build
the CLI engine first," which is exactly option 1 with the UI route deferred to a later phase.

## Decision

Adopt **CLI batch** ingestion: a `study ingest <folder>` command parses, semantically chunks,
embeds, and upserts into pgvector. It is idempotent and re-runnable.

The CLI is its **own top-level package** (`cli/`, exposing the `study` console-script) that depends
on `rag_core` as a workspace dependency — it is a thin entry point over the library, kept separate
from it rather than bundled inside.

## Consequences

- **No upload UI, queue, or worker** is needed early; ingestion is a script over `rag_core`, so the
  first working phases stay lean and focused on retrieval.
- Ingestion is **idempotent and re-runnable**, which suits a corpus that grows as courses progress.
- Because all ingestion logic lives in `rag_core` (per
  [ADR 0001](0001-rag-retrieval-boundary.md)), a **UI upload route can be added in a later phase**
  that reuses the exact same pipeline — the CLI-first choice does not foreclose it.
- The CLI being a **separate package** keeps the library's surface clean and lets the ingestion
  entry point evolve (flags, batching, progress) without touching `rag_core`.
