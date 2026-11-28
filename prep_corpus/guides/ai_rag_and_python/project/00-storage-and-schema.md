# 00. Storage and Schema

> Part of the [Project](README.md) section of [AI, RAG & Python](../README.md). Built in
> [study_assistant#2](https://github.com/sid-ak/study_assistant/issues/2) (Phase 1).

Phase 1 built the storage layer that every later stage reads from and writes to. A RAG pipeline
needs somewhere to keep three things: the source documents, the chunks cut from them, and one
embedding vector per chunk for similarity search. study_assistant keeps all three in PostgreSQL with
the pgvector extension, behind a small Python interface that has two implementations: one backed by
the database and one held in memory for fast tests. No retrieval, embedding, or ingestion logic
exists yet at this stage. Phase 1 defines where that logic will put its results and what it is
allowed to assume about them.

| Piece | What it is | Why it is built this way |
| ----- | ---------- | ------------------------ |
| pgvector `vector(N)` columns | A Postgres column type holding a fixed-length list of floats | Documents, chunks, and vectors live in one database, so one transaction covers all three |
| HNSW index per column | An approximate nearest-neighbor index over one embedding column | Similarity search stays fast as the corpus grows, without scanning every row |
| Per-model embedding columns | One `vector(N)` column and index per embedding model | Adding a model adds a column instead of rewriting a shared one |
| Embedder registry | A table recording each model, its dimension, and which model is current | The dimension is passed in explicitly instead of read from a global setting |
| `StoreProtocol` | A structural interface for document and chunk storage | Callers depend on behavior, never on SQL or a database driver |
| In-memory fakes | Full implementations of the protocols, held in dictionaries | Unit tests run without a database, and they reject the same bad input the database rejects |
| Contract tests | One test suite run against every implementation of a protocol | The fake and the real store cannot drift apart unnoticed |

The concepts this page builds on are in [RAG Overview](../concepts/01-rag-overview.md), for where
storage sits in the pipeline, and [Vector Space and Similarity](../concepts/02-vector-space-and-similarity.md),
for what the stored vectors are and how two of them are compared.

## Where storage sits in the pipeline

Why it matters: the store is the one component every other stage touches, so its interface decides
what the rest of the system is allowed to assume. Getting it wrong is expensive later, which is why
it was built first and built behind an interface.

A RAG pipeline has three lanes. Ingestion turns documents into embedded chunks, retrieval finds the
chunks most similar to a question, and generation writes an answer from those chunks. The store is
the one component all three lanes share:

- Ingestion writes documents and chunks into it.
- Retrieval reads chunks back out by vector similarity.
- Generation never touches it directly. It receives chunks from retrieval, which in study_assistant
  is reached only through a tool server.

All retrieval logic lives in one shared library, `rag_core`, which the command-line tool, the tool
server, and the backend all import
([ADR 0001](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0001-rag-retrieval-boundary.md)).
The store is the first module in that library.

## pgvector and the `vector(N)` type

Why it matters: this is the decision to keep vectors in the same database as the text rather than
in a separate vector store. It is the choice an interviewer is most likely to question, and the
answer is about transactions rather than about search quality.

pgvector is a Postgres extension that adds a column type for vectors and operators that compute the
distance between two of them.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE chunks ADD COLUMN embedding_baai_bge_small_en_v1_5 vector(384);

SELECT '[1,0]'::vector <=> '[0,1]'::vector;   -- cosine distance: 1
SELECT '[1,2]'::vector <#> '[3,4]'::vector;   -- negative inner product: -11
```

- Fixed length: `vector(384)` accepts only lists of exactly 384 numbers. The length is part of the
  column's type, so it is fixed when the column is created and cannot vary from row to row.
- Distance operators: `<=>` is cosine distance (one minus cosine similarity), `<->` is Euclidean
  distance, and `<#>` is the inner product multiplied by minus one. The minus sign exists so that
  for every operator a smaller number means more similar, which lets `ORDER BY ... LIMIT k` return
  the nearest rows.
- One database: chunks, their text, their metadata, and their vectors sit in the same row. Deleting
  a document removes its chunks and their vectors in one statement, and a failed write leaves
  nothing half-stored. A separate vector database would need its own consistency story.

> The schema also defines a generated full-text column, `tsv`, with its own GIN index. Nothing
> queries it in Phase 1. It exists so that keyword search can be added later without reshaping the
> table.

## The HNSW index and its limits

Why it matters: the index is what keeps similarity search from scanning every row, and its
dimension limit is a real constraint on which embedding models can be used at all. One of those
limits shaped the code; the other shaped nothing yet, and the difference is worth being precise
about.

Without an index, finding the nearest vectors means computing the distance to every row. pgvector's
HNSW index (Hierarchical Navigable Small World) builds a layered graph in which each vector is linked
to a few near neighbors, and a search walks that graph toward the query instead of visiting every
row. The result is approximate: the search can miss a true nearest neighbor in exchange for being
much faster.

```sql
CREATE INDEX IF NOT EXISTS embedding_baai_bge_small_en_v1_5_hnsw
ON chunks USING hnsw (embedding_baai_bge_small_en_v1_5 vector_cosine_ops);
```

- Operator class: `vector_cosine_ops` builds the graph for cosine distance, so only queries that
  order by `<=>` use this index.
- Build parameters: `m` (links per node, default 16) and `ef_construction` (candidates considered
  while inserting, default 64) are fixed when the index is built. study_assistant keeps both
  defaults.
- Search parameter: `hnsw.ef_search` (default 40) is the size of the candidate list kept during one
  query. It can be changed per session, which is what retrieval experiments vary.
- Dimension limit: pgvector refuses an HNSW index on a column with more than 2000 dimensions.
  Measured against pgvector 0.8.7, the error is "column cannot have more than 2000 dimensions for
  hnsw index". The store checks this limit itself before creating a column, so the failure is a
  typed error with a clear message rather than a database exception halfway through registration.

The dimension limit is checked in the store rather than left to the database, so registering an oversized model fails with a typed error naming the model and the supported range, instead of a driver exception partway through creating a column and an index.

??? example "check_embedder_dimension"

    ```python
    def check_embedder_dimension(model_id: str, dimension: int) -> None:
        """Raise ``UnsupportedDimensionError`` unless ``dimension`` is 1 to MAX_EMBEDDING_DIMENSION."""
        if dimension < 1 or dimension > MAX_EMBEDDING_DIMENSION:
            raise UnsupportedDimensionError(
                f"{model_id!r} has dimension {dimension}; "
                f"supported dimensions are 1 to {MAX_EMBEDDING_DIMENSION}."
            )
    ```

Source: [`packages/rag_core/src/rag_core/store/validation.py:20-29`](https://github.com/sid-ak/study_assistant/blob/b55615d/packages/rag_core/src/rag_core/store/validation.py#L20-L29)

## Per-model embedding columns and the embedder registry

Why it matters: this is the schema decision that made comparing two embedding models possible at
all. With one shared column it would have been a migration with downtime; with one column per model
it was an addition, and both models could be queried side by side while the comparison ran.

An embedding model always produces vectors of the same length, and two models' vectors cannot be
compared with each other even when the lengths match, because each model places meaning in its own
coordinate system. Changing models therefore means re-embedding every chunk. The question is what
happens to the stored data while that runs.

With one shared `embedding vector(N)` column, changing models is an in-place `ALTER` of the column
that every row and every query depends on. Old and new vectors cannot coexist, so the switch is all
or nothing. study_assistant instead gives each model its own column and its own index
([ADR 0008](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0008-per-model-embedding-columns.md)):

The column name is derived from the model id: lowercased, every run of non-alphanumeric characters replaced by an underscore, and prefixed. Postgres truncates identifiers at 63 bytes, so a name that would leave no room for the index's `_hnsw` suffix is refused rather than silently cut, which would collide with another model's index.

??? example "embedding_column"

    ```python
    def embedding_column(model_id: str) -> str:
        """Name the ``chunks`` column that holds ``model_id``'s embeddings.

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
    ```

Source: [`packages/rag_core/src/rag_core/store/schema.py:12-87`](https://github.com/sid-ak/study_assistant/blob/b55615d/packages/rag_core/src/rag_core/store/schema.py#L12-L87)

- Naming: `BAAI/bge-small-en-v1.5` becomes `embedding_baai_bge_small_en_v1_5`. Postgres truncates
  identifiers longer than 63 bytes, so the function refuses a name that would leave no room for the
  `_hnsw` suffix on the index name.
- Registry: `EmbedderRegistry.register(model_id, dimension)` records the model in an
  `embedding_models` table and adds its column and index. The dimension is an explicit argument, not
  a global setting read at import time. `set_current` marks one model as the default.
- Binding: each store instance is bound to exactly one model and only reads and writes that model's
  column. `store.with_embedder(other)` returns a second store over the same documents and chunks,
  bound to another model. Two models can therefore run side by side, which is how a comparison
  between embedders is evaluated.
- Not built yet: copying existing chunks into a newly registered model's column, and dropping an old
  column, are still open work
  ([study_assistant#15](https://github.com/sid-ak/study_assistant/issues/15)).

The model identity travels as a small immutable value:

??? example "EmbedderInfo"

    ```python
    @dataclass(frozen=True)
    class EmbedderInfo:
        """A registered embedding model: its identifier and the fixed dimension of its vectors."""

        model_id: str
        dimension: int
    ```

Source: [`packages/rag_core/src/rag_core/store/embedders/protocol.py:14-19`](https://github.com/sid-ak/study_assistant/blob/b55615d/packages/rag_core/src/rag_core/store/embedders/protocol.py#L14-L19)

- `@dataclass` generates `__init__`, `__repr__`, and `__eq__` from the annotated fields, so the class
  body is only the field list.
- `frozen=True` makes assignment to a field raise an error after construction. A frozen dataclass is
  also hashable, so it can be a dictionary key or a set member.

## `Protocol` interfaces

Why it matters: every component in this project can be swapped for a fake, and this is the
mechanism that makes it possible. It is also what keeps SQL out of the rest of the codebase, so no
caller can reach past the store into the database.

Every swappable component is defined as a `typing.Protocol`, and callers depend only on that protocol
([ADR 0006](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0006-interface-first-architecture.md)).

??? example "StoreProtocol"

    ```python
    @runtime_checkable
    class StoreProtocol(Protocol):
        """Structural interface for document and chunk storage, independent of any backend."""

        @property
        def embedder(self) -> EmbedderInfo:
            """The embedding model this store writes and reads vectors for."""
            ...

        def with_embedder(self, embedder: EmbedderInfo) -> "StoreProtocol":
            """Return a store over the same documents and chunks, bound to ``embedder``.

            The original store is unchanged, so stores for several models can be used side by side.
            ``embedder`` must already be registered with the embedder registry.
            """
            ...

        def initialize(self) -> None:
            """Idempotently prepare the backing storage for use; safe to call more than once."""
            ...
    ```

Source: [`packages/rag_core/src/rag_core/store/protocol.py:9-94`](https://github.com/sid-ak/study_assistant/blob/b55615d/packages/rag_core/src/rag_core/store/protocol.py#L9-L94)

- Structural typing: a class satisfies a `Protocol` by having methods with matching names and
  signatures. It does not inherit from it. The database `Store` and the in-memory `InMemoryStore`
  share no base class, and `mypy --strict` checks at every call site that each one matches the
  protocol.
- `@runtime_checkable`: allows `isinstance(obj, StoreProtocol)` at run time. That check only confirms
  the method names exist, not their signatures, so the static check by `mypy` remains the real
  guarantee.
- Backend-free contract: the protocol's docstrings describe behavior only. `get_connection()`, which
  returns a raw database connection, is deliberately left off the protocol, so code typed against
  `StoreProtocol` cannot reach past it into Postgres.
- The `user_id` seam: every write takes an optional `user_id`, defaulting to a fixed local user
  ([ADR 0003](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0003-local-single-user-scope.md)).
  The system is single-user, but the column exists so that multi-user support would not reshape
  the tables.

The database implementation turns driver exceptions into the store's own typed errors with a
context manager:

??? example "_embedder_column"

    ```python
    @contextmanager
    def _embedder_column(self) -> Iterator[sql.Identifier]:
        """Yield this store's embedding column, translating a missing column into a typed error."""
        try:
            yield sql.Identifier(embedding_column(self.embedder.model_id))
        except psycopg.errors.UndefinedColumn as e:
            raise EmbedderNotFoundError(
                f"Embedder {self.embedder.model_id!r} is not registered; register it first."
            ) from e
    ```

Source: [`packages/rag_core/src/rag_core/store/client.py:39-130`](https://github.com/sid-ak/study_assistant/blob/b55615d/packages/rag_core/src/rag_core/store/client.py#L39-L130)

- `@contextmanager` turns a function with one `yield` into something usable in a `with` statement.
  The code before `yield` runs on entry, the `with` block runs at the `yield`, and an exception
  raised inside the block is re-raised at the `yield`, where the `try` catches it.
- `raise ... from e` keeps the original database error attached as the cause, so a traceback shows
  both the typed error and what triggered it.
- `sql.Identifier` quotes a column name safely. A column name cannot be a query parameter, so it has
  to be composed into the SQL text, and this is the safe way to do that.

## In-memory fakes that enforce real constraints

Why it matters: a fake that is more permissive than the real thing is worse than no fake, because
it lets a bug pass every fast test and appear only against a database. The value is in the fake
failing in the same places.

A fake is a second, full implementation of a protocol that keeps its data in Python dictionaries.
Unit tests use it to run in milliseconds without a database. A fake is only useful if it fails where
the real backend fails. A fake that accepts a duplicate id the database would reject lets a bug pass
every unit test and appear only in integration.

??? example "add_chunks (in-memory store)"

    ```python
    # Mirrors the chunks primary key, also before any write: an id already stored, or one
    # that repeats within this batch, fails the whole batch instead of overwriting.
    batch_ids: set[UUID] = set()
    for chunk in chunks:
        if chunk["id"] in self.chunks or chunk["id"] in batch_ids:
            raise DuplicateIdError(f"Chunk id {chunk['id']} is already in use.")
        batch_ids.add(chunk["id"])
    ```

Source: [`packages/rag_core_testing/src/rag_core_testing/store.py:98-110`](https://github.com/sid-ak/study_assistant/blob/b55615d/packages/rag_core_testing/src/rag_core_testing/store.py#L98-L110)

- Every constraint the schema enforces has a matching check in the fake: unique document and chunk
  ids, the chunk's foreign key to its document, the embedding length, the supported dimension range,
  and all-or-nothing batches.
- Checks both implementations need, such as the dimension check above, live in one shared module,
  `store/validation.py`, so the two fail with the same error and the same message.
- Every check runs before any write. That is how the fake reproduces the database's all-or-nothing
  batch: the database rolls a failed batch back, and the fake never starts writing one that would
  fail.
- The fakes live in a separate dev-only package, `rag_core_testing`, so the library that ships
  contains only code the application runs.

The database side writes a batch with Postgres's binary `COPY` protocol instead of one `INSERT` per
row. `COPY` streams every row in one command, which is faster for large batches and is a single
statement, so a failure on any row fails the batch.

## Parametrized contract tests

Why it matters: two implementations of one interface drift apart unless something forces them not
to. One test suite run against both is that force, and it is what makes the fake trustworthy enough
to develop against.

The behavior a protocol promises is tested once and run against every implementation:

??? example "backend"

    ```python
    @pytest.fixture(
        params=[
            "memory",
            pytest.param("db", marks=pytest.mark.integration),
        ]
    )
    def backend(request: pytest.FixtureRequest) -> str:
        """Each storage backend, once each: ``memory`` or ``db``, the ``[memory]``/``[db]`` test ids.

        ``store`` and ``embedder_registry`` both follow it, so a test using both gets a matched pair:
        a model registered on ``embedder_registry`` can be bound with ``store.with_embedder``.
        """
        param: str = request.param
        return param
    ```

Source: [`packages/rag_core/tests/conftest.py:6-120`](https://github.com/sid-ak/study_assistant/blob/b55615d/packages/rag_core/tests/conftest.py#L6-L120)

The `store` and `embedder_registry` fixtures both take `backend` and return either the in-memory
implementation or the database one, so a test that asks for both gets a matched pair. A test body
then takes `store: StoreProtocol`, calls only protocol methods, and runs twice.

- A fixture with `params` runs every test that uses it once per parameter. The test ids show up as
  `[memory]` and `[db]`.
- `pytest.param("db", marks=pytest.mark.integration)` marks only the database run as an integration
  test, so `pytest -m unit` runs the whole suite against the fake with no database at all.
- `request.getfixturevalue("db_store")` creates the database fixture only when that parameter runs.
  A unit-only run therefore never needs a connection string.
- The test is typed against `StoreProtocol` and calls only protocol methods. It cannot depend on how
  either implementation stores data, so the same assertion holds both to the same contract.
- Behavior that only the database has, such as raw vector round-trips and schema creation, lives in
  a separate database-only test file.
- Integration tests run against a separate test database and truncate the tables after every test,
  so the application's own data is never touched.

## Python used

Why it matters: these are the language features this stage leans on, listed so the page can be read
as Python practice as well as design.

| Feature | Where it appears | What it does here |
| ------- | ---------------- | ----------------- |
| `typing.Protocol` | `StoreProtocol`, `EmbedderRegistryProtocol` | Defines an interface that classes satisfy by shape, with no inheritance |
| `@dataclass(frozen=True)` | `EmbedderInfo` | An immutable, hashable value object with generated `__init__` and `__eq__` |
| `@contextmanager` | `Store._embedder_column` | Translates a driver exception into a typed store error at one point |
| Type hints under `mypy --strict` | Every signature | Rejects untyped functions, and checks that both stores match their protocol |
| `pydantic-settings` | `rag_core.config.Settings` | Reads `DATABASE_URL` and the default user id from the environment or a `.env` file |
| Typed exception hierarchy | `store/errors.py` | Every error the store raises derives from `StoreError`, never from the driver |
| pytest fixtures with `params` | `tests/conftest.py` | One test body runs against every implementation |
| Custom pytest markers | `unit`, `integration` | A collection hook marks every test that is not an integration test as `unit` |

## Design trade-offs

Why it matters: each row is a decision that could have gone the other way, with the record that
settled it and the alternative it rejected.

| Decision | Chosen | Rejected alternative | Record |
| -------- | ------ | -------------------- | ------ |
| Where retrieval lives | A shared library that the tool server, backend, and CLI import | Retrieval owned by the tool server, with ingestion routed through it or duplicating its database access | [ADR 0001](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0001-rag-retrieval-boundary.md) |
| How components connect | `Protocol` interfaces with implementations injected by the caller | Concrete classes wired straight into their callers | [ADR 0006](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0006-interface-first-architecture.md) |
| Where vectors are stored | One column and HNSW index per model, plus a registry | One shared `embedding` column, altered in place on a model change | [ADR 0008](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0008-per-model-embedding-columns.md) |
| Who the data belongs to | A `user_id` column defaulted to one local user | No user column, added later with a table rewrite | [ADR 0003](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0003-local-single-user-scope.md) |
| Re-ingesting a file | Upsert keyed on the file's hash, keeping the original id | Delete and re-insert, which changes ids and drops chunks | Schema comment on `documents.file_hash` |

The cost of per-model columns is storage: while two models are active, every chunk carries two
vectors and two indexes. The cost of the protocol layer is one level of indirection, and the
standing discipline that callers never reach around the protocol to a concrete class.

## Measured results

Why it matters: this stage has little to measure, and saying so is more useful than implying
otherwise.

Phase 1 produced no retrieval measurements. Nothing embeds or searches yet, so there is nothing to
measure beyond the test suite passing against both backends. Retrieval quality and latency are
measured from the evaluation harness onward.

## Interview questions

Why it matters: the questions this stage invites, with answers short enough to say out loud.

Why keep vectors in Postgres instead of a dedicated vector database?
: The chunks, their text, their metadata, and their vectors live in one row, so a single transaction
  writes or deletes them together, and one backup covers everything. For a single-user corpus of
  thousands of chunks, pgvector's HNSW index is fast enough. A dedicated vector database earns its
  place at much larger scale or when the vectors must scale separately from the rest of the data.

Why does each embedding model get its own column?
: The dimension is part of a `vector(N)` column's type, and vectors from two models are not
  comparable even at the same length. With one column per model, adding a model is an additive
  change: the old column keeps serving queries while the new one fills, and the old one is dropped
  only after the new one is validated. A shared column would make every model change an in-place,
  all-or-nothing rewrite.

What does `ef_search` control, and how does it differ from `m`?
: `ef_search` is the size of the candidate list during a query: larger values visit more of the
  graph, which raises recall and costs latency, and it can be changed per query session. `m` is the
  number of links per node, fixed when the index is built, so changing it means rebuilding the
  index.

Why is the dimension limit checked in Python when the database enforces it anyway?
: Registration creates a row and then a column and an index. Checking the limit first means an
  unsupported model fails before anything is written, with a typed error that both the database
  store and the fake raise identically.

What is the difference between a `Protocol` and an abstract base class?
: An abstract base class requires implementations to inherit from it. A `Protocol` is satisfied by
  any class with matching methods, checked statically by `mypy`. The fake and the real store share no
  base class, and a third-party class could satisfy the protocol without knowing it exists.

How do you stop a test fake from drifting away from the real implementation?
: One contract suite, typed against the protocol, runs every test against both implementations. The
  fake must enforce every constraint the database enforces, and the failure paths are tested too,
  not only the successful ones. Shared checks live in one module, so both raise the same error.

How are integration tests kept away from real data?
: They read a separate `TEST_DATABASE_URL`, refuse to run without it, and truncate the tables after
  every test. The database container creates the test database on first start, so no manual setup
  is needed.
