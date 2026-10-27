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

ADR 0008 (per-model embedding columns) is implemented except for its migration tail: re-embedding
existing chunks into a new model's column and dropping the old column are not built yet. That work
is tracked in [issue #15](https://github.com/sid-ak/study_assistant/issues/15). Until it lands, a
newly registered embedder only has embeddings for chunks written after it became current.

## Store conventions

Not ADR-level, but load-bearing for anyone adding to `store/`:

- Callers depend on `StoreProtocol` (ADR 0006), not the concrete `Store` — type new consumers
  against the `Protocol` and inject the implementation. `InMemoryStore` is the fake for DB-free unit
  tests; the DB-backed `Store` is exercised by the `@pytest.mark.integration` tests. Keep both
  implementations and the `Protocol` in lockstep when you change a method signature — add a new
  method in three passes (tests, then the `Protocol` signature + `NotImplementedError` stubs on both
  implementations, then real logic), per the three-pass TDD rule in the root `AGENTS.md`.
- `get_connection()` is deliberately not on `StoreProtocol` — it returns a raw `psycopg` connection
  (the driver dependency ADR 0006 keeps out of retrieval logic). Only the concrete `Store` and the
  integration tests use it. `get_chunks_by_document` is the one read path chunks do have on the
  Protocol; if a new read need comes up, prefer extending the Protocol over reaching for
  `get_connection()` from outside `Store`.
- Test layout mirrors this split: `test_store.py` holds every behavior `StoreProtocol`
  guarantees, parametrized over the `store` fixture (`InMemoryStore` and `Store`, labeled
  `[memory]`/`[db]`) so the two implementations can't silently drift apart. `test_db_store.py` holds
  only what's genuinely Store-only and unexpressible through the Protocol (raw vector round-tripping,
  schema DDL idempotency), via the DB-only `db_store` fixture. A new `StoreProtocol` method's tests
  belong in `test_store.py` against `store`, not duplicated per-implementation.
- Embeddings never go in a fixed column. `register_embedder(model_id, dimension)` adds the model's
  own `vector(N)` column and HNSW index (named by `schema.embedding_column`), and `add_chunks` /
  `get_chunks_by_document` use whichever model is current. Pass a dimension explicitly when
  registering; there is no global dimension setting (ADR 0008).
- Raise the typed errors in `store/errors.py`, never a driver exception, from a `StoreProtocol`
  method, and put any check both stores need in `store/validation.py` so they fail identically.
  `InMemoryStore` must enforce every constraint the schema enforces (foreign key, dimension,
  all-or-nothing batches), and the contract suite pins each failure path for both stores.
- Every write method takes an optional `user_id: UUID | None`, defaulting to
  `settings.default_user_id` (the ADR 0003 seam). New methods should follow the same signature
  rather than hardcoding the default user or dropping the parameter.
- `get_connection()` calls `register_vector(conn)` so `vector` columns round-trip as numpy arrays.
  Any code that opens its own `psycopg.connect(...)` outside `Store` must call `register_vector`
  itself or vector columns won't (de)serialize.
- `add_chunks` bulk-inserts via the `COPY ... FORMAT BINARY` protocol, not per-row `INSERT` — keep
  new batch-write paths on `COPY` for the same throughput reason. It's currently all-or-nothing per
  batch (see the TODO in `client.py`); don't assume partial-failure handling exists.
