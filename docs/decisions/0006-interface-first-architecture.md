# 6. Interface-First Architecture

- Status: Accepted
- Date: 2026-07-02

## Context

Several components in the system must be replaceable: the embedder and reranker (open-weight models
that will change as the field moves), the generation backend (which must carry no vendor tie-in —
see [ADR 0007](0007-generation-backend.md)), and pgvector-backed store access. The system also has
to be testable without standing up multi-GB models or a live database on every run — CI and fast
unit tests need substitutes for the heavy, external pieces.

[ADR 0001](0001-rag-retrieval-boundary.md) already decided where retrieval physically lives (a
shared `rag_core` library) and noted, per component, that the embedder and reranker sit behind "a
small interface." This ADR promotes that from a per-component remark to an explicit, project-wide
principle, so new components inherit the shape by default rather than by coincidence.

The alternative — wiring concrete classes (a specific embedder, a specific model client, direct
driver calls) straight into their callers — is quicker to write first but couples the whole system
to those choices: swapping a model means editing every call site, and testing means loading the real
model or hitting the real database.

## Decision

Build every swappable component as a small interface with concrete implementations behind it. This
is the general theme of the architecture, not a one-off for any single lane.

- Interfaces are Python `Protocol`s — structural typing, so an implementation conforms by shape with
  no base class to inherit.
- Callers depend on the `Protocol`, never a concrete type.
- The concrete implementation is selected by config and injected.

It applies across the codebase:

- Embedder and reranker — behind interfaces so the concrete `bge` models are swappable (see
  [ADR 0002](0002-local-embedding-and-reranking.md)).
- Generator — behind a `Generator` interface with a vendor-neutral adapter (see
  [ADR 0007](0007-generation-backend.md)).
- Store — pgvector access behind an interface, so retrieval logic does not depend on raw SQL or
  driver calls.

## Consequences

- Swappability: an implementation changes by config, not by editing call sites — the point of the
  exercise, and what lets models and backends move as the field does.
- Testability: tests substitute lightweight fakes for a `Protocol`, so unit tests run without
  loading multi-GB models or a live database, while integration tests exercise the real
  implementations.
- `Protocol`/structural typing keeps this lightweight — no inheritance hierarchy — and `mypy`
  (strict) checks conformance at the boundary.
- The one hard lock-in that no interface can hide is the pgvector `vector(N)` embedding dimension,
  baked into the schema (see [ADR 0002](0002-local-embedding-and-reranking.md)); everything else
  stays behind an abstraction.
- A small indirection cost, and the standing discipline that callers depend on the `Protocol` rather
  than reaching around it to a concrete class. This is carried as a convention in `AGENTS.md`.
