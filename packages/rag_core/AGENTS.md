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

ADR 0008 (per-model embedding columns) is implemented except for the last step of a model switch:
dropping the old model's column. Filling a newly registered model's column for chunks that already
exist is built (`embed_missing`, run by `study embed`). Dropping a column is still tracked in
[issue #15](https://github.com/sid-ak/study_assistant/issues/15).

## Store conventions

Not ADR-level, but load-bearing for anyone adding to `store/`:

- Callers depend on `StoreProtocol` (ADR 0006), not the concrete `Store` — type new consumers
  against the `Protocol` and inject the implementation. `src/` holds only what the application
  runs. Test fakes and test data live in the dev-only
  [`rag_core_testing`](../rag_core_testing/AGENTS.md) package (`InMemoryStore`,
  `InMemoryEmbedderRegistry`, `make_chunk`), which back the DB-free unit tests. The DB-backed
  `Store` is exercised by the `@pytest.mark.integration` tests. Keep both
  implementations and the `Protocol` in lockstep when you change a method signature — add a new
  method in three passes (tests, then the `Protocol` signature + `NotImplementedError` stubs on both
  implementations, then real logic), per the three-pass TDD rule in the root `AGENTS.md`.
- `get_connection()` is deliberately not on `StoreProtocol` — it returns a raw `psycopg` connection
  (the driver dependency ADR 0006 keeps out of retrieval logic). Only the concrete `Store` and the
  integration tests use it. Chunks have two read paths on the Protocol, `get_chunks_by_document`
  and `search_dense`; if a new read need comes up, prefer extending the Protocol over reaching for
  `get_connection()` from outside `Store`.
- Test layout mirrors this split: `test_store.py` holds every behavior `StoreProtocol`
  guarantees, parametrized over the `store` fixture (`InMemoryStore` and `Store`, labeled
  `[memory]`/`[db]`) so the two implementations can't silently drift apart. `test_db_store.py` holds
  only what's genuinely Store-only and unexpressible through the Protocol (raw vector round-tripping,
  schema DDL idempotency), via the DB-only `db_store` fixture. A new `StoreProtocol` method's tests
  belong in `test_store.py` against `store`, not duplicated per-implementation.
- Embeddings never go in a fixed column, and a store never manages embedding models:
  - Each store instance is bound to one `EmbedderInfo` (model id and dimension), passed to its
    constructor. `add_chunks` writes that model's column and `get_chunks_by_document` reads it, so
    vectors always land in the column of the model the caller embedded them with.
  - `store.with_embedder(other)` returns a store over the same documents and chunks bound to
    another model, leaving the original untouched. That is how to switch models at runtime, run
    models side by side for benchmarks, or backfill a new model's column (issue #15).
  - The embedder registry in `store/embedders/` (`EmbedderRegistryProtocol` and
    `EmbedderRegistry`, with the `InMemoryEmbedderRegistry` fake in `rag_core_testing`) is separate.
    `register(model_id, dimension)` records a model, and the DB registry adds its `vector(N)` column
    and HNSW index (named by `schema.embedding_column`). Pass the dimension explicitly; there is no
    global dimension setting (ADR 0008). A model must be registered before a store bound to it can
    write or read, or the DB store raises `EmbedderNotFoundError`.
  - `set_current` / `get_current` record the default model. Stores never read it; the code that
    assembles the application reads it once at startup to choose the `EmbedderInfo` to bind.
  - Registry tests mirror the store layout: `test_embedder_registry.py` is the contract suite over
    the `embedder_registry` fixture, and `test_db_embedder_registry.py` covers the columns and
    indexes only the DB registry adds. `store` and `embedder_registry` follow one `backend`
    parameter, so a test that registers a model can bind it with `store.with_embedder`.
- Schema changes need a fresh DB: `Store.initialize()` is `CREATE ... IF NOT EXISTS` and will not
  retrofit constraints, so run `docker compose down -v && docker compose up -d` after editing
  `store/schema.py`.
- Every DB-backed class opens connections through `store/connection.py` (`connect`,
  `resolve_database_url`), so URL resolution and `register_vector` live in one place.
- Raise the typed errors in `store/errors.py`, never a driver exception, from a `StoreProtocol`
  method, and put any check both stores need in `store/validation.py` so they fail identically.
  `InMemoryStore` and `InMemoryEmbedderRegistry` must enforce every constraint the schema
  enforces, and the contract suites pin each failure path for both implementations:
  - Unique document and chunk ids, raising `DuplicateIdError`. A batch that reuses a stored id
    or repeats one is refused whole.
  - The chunk foreign key to its document, raising `MissingDocumentError`.
  - Embedding length matching the store's embedder, raising `EmbeddingDimensionError`.
  - No all-zero embedding, stored or queried, raising `ZeroEmbeddingError`. Cosine distance to a
    zero vector is NaN in pgvector, so neither store accepts one.
  - An embedder dimension of 1 to `MAX_EMBEDDING_DIMENSION` (2000, the HNSW index limit),
    raising `UnsupportedDimensionError` before anything is registered.
  - All-or-nothing batches.
- Every write method takes an optional `user_id: UUID | None`, defaulting to
  `settings.default_user_id` (the ADR 0003 seam). New methods should follow the same signature
  rather than hardcoding the default user or dropping the parameter.
- `connection.connect` calls `register_vector(conn)` so `vector` columns round-trip as numpy
  arrays. Any code that opens its own `psycopg.connect(...)` instead must call `register_vector`
  itself or vector columns won't (de)serialize.
- `add_chunks` bulk-inserts via the `COPY ... FORMAT BINARY` protocol, not per-row `INSERT` — keep
  new batch-write paths on `COPY` for the same throughput reason. Each batch is all-or-nothing,
  pinned for both stores by `test_add_chunks_is_all_or_nothing`, so a failed batch writes nothing.

## Embedder conventions

- Callers depend on `EmbedderProtocol` (`rag_core.embed`), never on `FastembedEmbedder`. An
  embedder's `info` is the `EmbedderInfo` a store is bound to, so bind stores with
  `store.with_embedder(embedder.info)` and the vectors always land in that model's column.
- Vectors are unit length, so cosine similarity equals the dot product. `HashingEmbedder` in
  `rag_core_testing` keeps that property, and the contract suite in `test_embedder.py` pins it.
- `FastembedEmbedder` loads lazily: building one checks the model id and dimension against
  fastembed's built-in model list (no network) and loads nothing. The first embed call downloads
  the files, if needed, and loads the model. fastembed's own `lazy_load=True` still downloads at
  construction, so the deferral lives in `FastembedEmbedder.load`.
- `embed_query` prepends `query_prefix`, and `embed_documents` embeds text as given. fastembed's
  `query_embed` adds no instruction for the bge models, so the prefix is applied here.
- The configured model comes from `Settings` (`EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`,
  `EMBEDDING_QUERY_PREFIX`), read through `FastembedEmbedder.from_settings`.

## Dense search

- `search_dense` ranks this store's model's vectors by cosine distance (pgvector's `<=>`). The SQL
  is `ORDER BY <column> <=> query LIMIT n` with no second sort key, because a tie-breaking column
  stops Postgres from using the HNSW index (checked with `EXPLAIN`). Equal distances therefore
  have no defined order, and contract tests avoid ties.
- `ef_search` is the only HNSW parameter retrieval varies. `m` and `ef_construction` are build-time
  index options and stay at pgvector's defaults. The store sets `ef_search` with
  `set_config('hnsw.ef_search', ..., true)`, local to the search's transaction. Postgres accepts
  any value for that setting before pgvector is loaded in the session, so `check_search` enforces
  the 1 to 1000 range and `ef_search >= limit` (HNSW returns at most `ef_search` rows).
- Bind a query vector as `pgvector.Vector` or a numpy array. A plain Python list binds as
  `double precision[]`, which has no `<=>` operator.
- The DB search is approximate once the planner uses the index; `InMemoryStore` compares against
  every chunk and is exact. Contract tests use corpora small enough that both return the same
  ranking.

## Reranker conventions

- `RerankerProtocol.score(query, documents)` returns relevance from 0 to 1, one per document in
  order. `FastembedReranker` applies a sigmoid to the cross-encoder's logit, so a threshold means
  the same for any reranker, and the fake (`OverlapReranker`) returns the share of query words a
  document contains.
- The reranker loads its model on first `score`, like the embedder; building one only checks the
  model id against fastembed's list.
- `RERANK_ENABLED` (default on), `RERANKER_MODEL`, and `RERANK_CANDIDATES` (default 20) configure
  it; `build_reranker(settings)` returns the reranker or `None`, and every caller of `retrieve`
  builds it this way.
- `retrieve` is two separate steps, `search` then `rerank`, so another step (such as hybrid fusion)
  can sit between them. With a reranker it searches `candidates` chunks and keeps the `limit` best.
  Each `RetrievedChunk.relevance` is the reranker's score, or the cosine similarity without one, and
  `RetrievalResult.rerank_latency_ms` times the reranking step alone.

## Lexical search conventions

- `StoreProtocol.search_lexical(query, limit)` matches chunks by words, not meaning. The database
  store reads the generated `tsv` column (`to_tsvector('english', content)`, GIN-indexed) and turns
  the query into an OR of its stemmed words, since `plainto_tsquery` alone ANDs every word and a
  full question rarely matches. Results are ordered by `ts_rank`.
- `ts_rank` approximates BM25: it weighs how often query words occur in a chunk, but uses no inverse
  document frequency (rare words count no more than common ones) and, by default, ignores chunk
  length. Postgres has no built-in BM25.
- The fake counts shared words after dropping a list of stop words, without stemming. Contract tests
  compare which chunks come back, not their order, because the two scorers rank differently.
- Lexical search reads no embedding, so it works the same for a store bound to any model.

