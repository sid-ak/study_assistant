# rag_core — Agent Context

`rag_core` is the shared retrieval library. See the root [`AGENTS.md`](../../AGENTS.md) for
project-wide context and [`docs/architecture.md`](../../docs/architecture.md) for where this package
sits and its module layout.

Its rules are binding decisions recorded as ADRs, not restated here: read the relevant record in
[`docs/decisions/`](../../docs/decisions/) before changing what it governs. The ones that bind
`rag_core` are the retrieval boundary (0001), the embedding/reranking stack and `vector(N)`
dimension (0002), the single-user `user_id` seam (0003), interface-first `Protocol`s (0006), and
per-model embedding columns (0008).

## Known drift from ADRs

Two accepted ADRs are ahead of the code — don't assume the shape below already matches the ADR just
because it's "Accepted":

- **ADR 0006 (interface-first):** `store/__init__.py` exports the concrete `Store` class directly;
  there is no `Protocol` in front of it yet. Store access is still concrete everywhere it's called.
  Introducing the `Protocol` (plus a fake for unit tests) is open work, not done.
- **ADR 0008 (per-model embedding columns):** `config.py` still reads a single global
  `settings.embedding_dimension`, and `schema.py` still builds one shared `embedding vector(N)`
  column — the pre-0008 shape ADR 0008 exists to replace. Explicit per-call dimensions and
  per-model columns aren't implemented; tracked in
  [issue #15](https://github.com/sid-ak/study_assistant/issues/15), which is still open.

## Store conventions

Not ADR-level, but load-bearing for anyone adding to `store/`:

- Every write method takes an optional `user_id: UUID | None`, defaulting to
  `settings.default_user_id` (the ADR 0003 seam). New methods should follow the same signature
  rather than hardcoding the default user or dropping the parameter.
- `get_connection()` calls `register_vector(conn)` so `vector` columns round-trip as numpy arrays.
  Any code that opens its own `psycopg.connect(...)` outside `Store` must call `register_vector`
  itself or vector columns won't (de)serialize.
- `add_chunks` bulk-inserts via the `COPY ... FORMAT BINARY` protocol, not per-row `INSERT` — keep
  new batch-write paths on `COPY` for the same throughput reason. It's currently all-or-nothing per
  batch (see the TODO in `client.py`); don't assume partial-failure handling exists.
