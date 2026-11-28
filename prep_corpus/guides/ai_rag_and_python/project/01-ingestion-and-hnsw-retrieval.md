# 01. Ingestion and HNSW Retrieval

> Part of the [Project](README.md) section of [AI, RAG & Python](../README.md). Built in
> [study_assistant#46](https://github.com/sid-ak/study_assistant/issues/46), pull request
> [study_assistant#71](https://github.com/sid-ak/study_assistant/pull/71).

Chunk 1 built the first path through the system that runs end to end. A folder of markdown goes in
through `study ingest`. Each file is split into section-sized chunks, embedded on the local machine
with `bge-small-en-v1.5`, and stored in that model's own pgvector column. `study query` embeds a
question, ranks the stored chunks by cosine distance, and prints each one's distance and the time
the search took. Everything after this chunk, including the evaluation harness, the agent, the
reranker, and hybrid search, calls the retrieval function built here.

| Piece | Module | What it does |
| ----- | ------ | ------------ |
| Section parser and chunker | `rag_core/ingest/` | Splits markdown at headings, keeps code fences whole, prefixes each chunk with its heading path |
| Embedder | `rag_core/embed/` | `EmbedderProtocol`, a `fastembed` implementation that loads the model on first use, and a hashing fake for tests |
| Dense search | `rag_core/store/` | `search_dense` ranks one model's vectors by cosine distance, with `ef_search` per query |
| Retrieval entry point | `rag_core/retrieve/` | `retrieve` embeds the query, searches, and reports latency |
| Folder ingestion | `rag_core/ingest/pipeline.py` | Idempotent: skips unchanged files, replaces changed ones |
| CLI | `cli/` | `study ingest <folder>` and `study query "<text>"` |
| Corpus | `corpus/release_engineering/` | 17 original documents: build guides, release notes, CI failure write-ups |

The general theory is in [Embeddings](../concepts/03-embeddings.md),
[Chunking](../concepts/04-chunking.md), and [Retrieval](../concepts/05-retrieval.md).

## The ingestion path

Why it matters: ingestion is the only stage that writes, so every mistake it makes is stored and
read back by everything else. Its hard requirement is that running it twice costs nothing, because
a corpus gets re-ingested constantly while a pipeline is being built.

`ingest_folder` runs the whole path for one folder. For each markdown file it:

1. Hashes the file's bytes with SHA-256.
2. Skips the file if a document with that hash is already stored with chunks.
3. Decodes it as UTF-8, or reports it as unreadable and moves on to the next file.
4. Chunks the text and embeds every chunk, before anything is written.
5. Stores the document under an id derived from its relative path, replacing an older version of
   the same path.
6. Writes all of the file's chunks in one batch.

??? example "ingest_folder"

    ```python
    document_id = uuid.uuid5(DOCUMENT_ID_NAMESPACE, source)
    try:
        stored_id = store.add_document(id=document_id, filename=source, file_hash=file_hash)
    except DuplicateIdError:
        # This path was ingested before with other content: drop that version and its chunks.
        store.delete_document(document_id)
        stored_id = store.add_document(id=document_id, filename=source, file_hash=file_hash)
        report.replaced.append(source)
    ```

Source: [`packages/rag_core/src/rag_core/ingest/pipeline.py:93-118`](https://github.com/sid-ak/study_assistant/blob/e294ca3/packages/rag_core/src/rag_core/ingest/pipeline.py#L93-L118)

- Deterministic ids: `uuid.uuid5(namespace, name)` hashes a fixed namespace and a name into a UUID,
  so the same relative path always gives the same document id. A re-run therefore finds the same
  document instead of creating a second one. `uuid4`, by contrast, is random on every call.
- Idempotency: running `study ingest` twice on an unchanged folder writes nothing the second time.
  The store already rejects a document id that belongs to different content (`DuplicateIdError`),
  and ingestion uses exactly that signal to detect a changed file.
- Failure ordering: chunking and embedding happen before any write, so a model or parsing failure
  leaves the store untouched. If a run stops between storing a document and its chunks, the next
  run sees a document with no chunks and writes them.

## Heading-aware chunking

Why it matters: the chunk is the unit that gets retrieved and cited, so where the boundaries fall
decides what an answer can be built from. Splitting on the author's own headings is cheaper than
inferring boundaries and produces chunks a reader would recognise.

The corpus is markdown, so the chunker splits at headings rather than at a fixed size
([Chunking](../concepts/04-chunking.md) compares the approaches). A section that fits the word
budget is one chunk, and a longer one is split between paragraphs, then lines, then words.

??? example "TextChunk"

    ```python
    def pack(units: list[str], separator: str, max_words: int) -> list[str]:
        """Join consecutive ``units`` with ``separator`` into groups of at most ``max_words`` words.

        Units are added to the current group until the next one would overflow it. A unit that is over
        the budget on its own still becomes a group of its own.
        """
        groups: list[str] = []
        current: list[str] = []
        current_words = 0
        for unit in units:
            words = count_words(unit)
            if current and current_words + words > max_words:
                groups.append(separator.join(current))
                current = []
                current_words = 0
            current.append(unit)
            current_words += words
        if current:
            groups.append(separator.join(current))
        return groups
    ```

Source: [`packages/rag_core/src/rag_core/ingest/chunking.py:22-96`](https://github.com/sid-ak/study_assistant/blob/e294ca3/packages/rag_core/src/rag_core/ingest/chunking.py#L22-L96)

- Greedy packing: units are added to the current group until the next one would overflow it. The
  same function packs paragraphs (joined with a blank line) and lines (joined with a newline).
- Code fences: the parser tracks whether it is inside a fenced code block, so `# configure` in a
  shell snippet is not read as a heading, and a blank line inside a code block is not a split point.
- Breadcrumbs: each chunk's text starts with its heading path, such as
  `CI failure: undefined reference to pthread_create > Fix`. The corpus repeats section names such
  as "Fix" and "Symptom" in every CI write-up, and the path is what tells them apart, both for the
  embedding and for a citation.
- Metadata: each chunk records `source`, `section`, `headings`, and `chunk_index`, which is what a
  citation needs.

## The embedder and lazy loading

Why it matters: the embedding model is the slowest thing to start and the only component both
ingestion and retrieval need. When it loads decides whether a process starts in milliseconds or
seconds, which matters because the tool server is started per run.

`EmbedderProtocol` is the interface ingestion and retrieval depend on:

??? example "protocol"

    ```python
    @runtime_checkable
    class EmbedderProtocol(Protocol):
        """Structural interface for turning text into unit-length vectors."""

        @property
        def info(self) -> EmbedderInfo:
            """The model id and vector dimension; a store bound to this ``info`` holds its vectors."""
            ...

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            """Embed passages for storage, returning one vector per text, in order."""
            ...

        def embed_query(self, text: str) -> list[float]:
            """Embed a search query, which may be encoded differently from a stored passage."""
            ...
    ```

Source: [`packages/rag_core/src/rag_core/embed/protocol.py:12-27`](https://github.com/sid-ak/study_assistant/blob/e294ca3/packages/rag_core/src/rag_core/embed/protocol.py#L12-L27)
`FastembedEmbedder` implements it with `fastembed`, which runs quantized models on ONNX Runtime
instead of PyTorch. Building one checks the configuration and loads nothing:

??? example "load"

    ```python
    def load(self) -> TextEmbedding:
        """Return the model, downloading and loading it the first time it is needed."""
        if self._model is None:
            self._model = TextEmbedding(model_name=self._info.model_id)
        return self._model
    ```

Source: [`packages/rag_core/src/rag_core/embed/fastembed_embedder.py:72-76`](https://github.com/sid-ak/study_assistant/blob/e294ca3/packages/rag_core/src/rag_core/embed/fastembed_embedder.py#L72-L76)

- Lazy loading: the model object is created the first time text is embedded. Commands that never
  embed, and unit tests that build the embedder only to check its settings, pay nothing.
- Why not fastembed's own option: a probe showed that `TextEmbedding(..., lazy_load=True)` still
  downloads the model files when constructed, so the deferral had to live in this class.
- Fail fast on configuration: the constructor looks the model up in fastembed's bundled model list
  and raises `ValueError` if the model is unknown or the configured dimension does not match. That
  check needs no network, so a typo in `EMBEDDING_MODEL` fails immediately instead of after a
  download.
- `@classmethod from_settings(cls, settings)`: an alternative constructor that reads the model id,
  dimension, and query prefix from the `pydantic-settings` configuration. Switching to
  `bge-base-en-v1.5` is a change to environment variables, not to code.
- Query prefix: fastembed's `query_embed` adds no instruction for the bge models (probed: its
  output equals `embed`). `embed_query` prepends the model card's instruction itself, and the
  prefix is a setting so the evaluation harness can measure it on and off.
- Test fake: `HashingEmbedder` hashes each word into one of 64 buckets and normalizes the counts.
  Texts that share words score as similar, so retrieval tests rank real sentences without loading a
  model. One parametrized contract suite runs against the fake and the real model.

## Dense search and ef_search

Why it matters: this is where a question becomes a database query, and the one tunable that trades
recall against latency lives here. Getting the query's shape right is also what lets the index
serve it at all.

`search_dense` was added to `StoreProtocol` and implemented in both stores. The database version is
one SQL statement:

```sql
SELECT id, document_id, content, metadata, embedding_baai_bge_small_en_v1_5 <=> %(query)s AS distance
FROM chunks WHERE embedding_baai_bge_small_en_v1_5 IS NOT NULL
ORDER BY embedding_baai_bge_small_en_v1_5 <=> %(query)s LIMIT %(limit)s
```

- `ORDER BY column <=> query LIMIT k` is the shape pgvector's HNSW index serves. Adding a second
  sort key for ties made `EXPLAIN` switch to a sequential scan, so equal distances have no defined
  order.
- Binding the query vector: a plain Python list binds as `double precision[]`, which has no `<=>`
  operator. The query is wrapped in `pgvector.Vector`.
- `ef_search` per query: set with `SELECT set_config('hnsw.ef_search', %s, true)`. `SET` cannot take
  a bind parameter and `set_config` can, and the `true` argument limits the setting to the current
  transaction, so it never leaks into another search.
- Validation shared by both stores: `ef_search` must be 1 to 1000 and at least `limit`. A probe
  showed HNSW returns at most `ef_search` rows, and that Postgres accepts any value for the setting
  before pgvector is loaded in the session, so the store checks the range itself.
- Zero vectors: cosine distance to an all-zero vector is NaN in pgvector, so both stores refuse an
  all-zero embedding on write and on query with a typed `ZeroEmbeddingError`.
- `m` and `ef_construction` stay at pgvector's defaults (16 and 64). Only `ef_search` is varied,
  since it changes per query without rebuilding the index.

## The retrieval entry point

Why it matters: everything above retrieval, the command line, the tool server and the agent, calls
this one function. Its signature is therefore the contract for the whole retrieval half of the
system.

??? example "retrieve"

    ```python
    def retrieve(
        query: str,
        *,
        embedder: EmbedderProtocol,
        store: StoreProtocol,
        limit: int = 5,
        ef_search: int | None = None,
    ) -> RetrievalResult:
        check_same_model(embedder, store)
        started = time.perf_counter()
        query_embedding = embedder.embed_query(query)
        rows = store.search_dense(query_embedding, limit=limit, ef_search=ef_search)
        latency_ms = (time.perf_counter() - started) * 1000.0
    ```

Source: [`packages/rag_core/src/rag_core/retrieve/dense.py:32-51`](https://github.com/sid-ak/study_assistant/blob/e294ca3/packages/rag_core/src/rag_core/retrieve/dense.py#L32-L51)

- One entry point: the CLI, the evaluation harness, and the tool server all retrieve through this
  function. Reranking and hybrid search are added to it later, behind settings.
- Same-model check: a query vector from one model compared with stored vectors from another gives
  meaningless distances, so retrieval and ingestion both refuse a store bound to a different model.
- Keyword-only arguments: the bare `*` in the signature makes every argument after it keyword-only,
  so a call reads `retrieve(text, embedder=e, store=s)` and the two components cannot be swapped by
  position.
- `time.perf_counter()` is a monotonic clock with the highest available resolution. It is meant for
  measuring durations and never jumps when the system clock is adjusted.
- `study query` embeds a warm-up query first, so the reported latency covers embedding and search,
  not the one-time model load.

## The CLI

Why it matters: the command line is what makes the pipeline usable before any service exists, and
it is how every measurement on this page was taken.

`cli/` is a separate workspace package that exposes the `study` console script through
`[project.scripts] study = "study_cli.main:main"`. It uses `argparse` subcommands:

??? example "build_parser"

    ```python
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Load every markdown file under a folder.")
    ingest.add_argument("folder", type=Path, help="Folder to ingest, searched recursively.")
    ```

Source: [`cli/src/study_cli/main.py:53-56`](https://github.com/sid-ak/study_assistant/blob/e294ca3/cli/src/study_cli/main.py#L53-L56)

- `required=True` makes `argparse` print usage and exit with status 2 when no command is given.
- `type=Path` converts the argument to a `pathlib.Path` during parsing.
- Each command is a function that receives its components (embedder, store, registry) as an
  argument. `main` builds the real ones, and the tests replace the builder with in-memory fakes
  through `monkeypatch.setattr`, then read printed output with pytest's `capsys` fixture.
- On the first ingest, `register_embedder` registers the configured model, which adds its
  `vector(384)` column and HNSW index, and marks it current only if no model is current yet.

## Python used

Why it matters: these are the language features this stage leans on, listed so the page can be
read as Python practice as well as design.

| Feature | Where it appears | What it does here |
| ------- | ---------------- | ----------------- |
| `typing.Protocol` with `@runtime_checkable` | `EmbedderProtocol`, `ChunkerProtocol` | Interfaces satisfied by shape; contract tests check `isinstance` on each implementation |
| `@dataclass(frozen=True)` | `Section`, `TextChunk`, `RetrievedChunk`, `RetrievalResult` | Immutable value objects with generated `__init__` and `__eq__` |
| `field(default_factory=list)` | `IngestReport` | Gives each report its own empty list; a plain `= []` default is refused by dataclasses because one list would be shared |
| `@property` | `FastembedEmbedder.info`, `is_loaded` | Read-only attributes computed from private state |
| `@classmethod` | `FastembedEmbedder.from_settings` | An alternative constructor from configuration |
| `uuid.uuid5`, `hashlib.sha256` | `ingest_folder` | Deterministic ids from paths, content identity from bytes |
| `pathlib.Path.rglob` | `markdown_files` | Recursive file search; results are sorted for a stable order |
| `re` with groups | `HEADING_PATTERN` | Matches ATX headings and captures the level and text |
| Keyword-only parameters (`*`) | `retrieve`, `ingest_folder` | Forces callers to name the embedder and store |
| `argparse` subparsers | `study_cli.main` | `study ingest` and `study query` with typed options |
| pytest `monkeypatch`, `capsys`, `tmp_path` | CLI and ingestion tests | Swap a function, capture printed output, and write files into a fresh folder per test |

## Design trade-offs

Why it matters: each row is a decision that could have gone the other way, with the record that
settled it and the alternative it rejected.

| Decision | Chosen | Rejected alternative | Record |
| -------- | ------ | -------------------- | ------ |
| Embedding runtime | `fastembed` on ONNX Runtime with `bge-small-en-v1.5` | `bge-m3` on PyTorch, too large for an 8 GB machine with about 7 GB of free disk | [ADR 0010](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0010-lightweight-embedding-and-reranking-models.md) |
| Where vectors live | The model's own `vector(384)` column and HNSW index | One shared column altered on every model change | [ADR 0008](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0008-per-model-embedding-columns.md) |
| How documents enter | A CLI over a folder, with the pipeline in the library | A UI upload with a background worker | [ADR 0004](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0004-cli-batch-ingestion.md) |
| What the MVP indexes | Release-engineering markdown | Course slides and PDFs, which need extraction parsers | [ADR 0009](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0009-mvp-corpus.md) |
| How documents are split | Heading-aware sections | Fixed-size windows with overlap | Pull request #71 |
| How chunk size is counted | Words, at most 120 | Tokens from the embedding model's tokenizer, which would tie the chunker to one model | Pull request #71 |

Per-model columns pay off directly here: registering `bge-small-en-v1.5` added its column and index
next to the existing tables, and the next chunk registers `bge-base-en-v1.5` beside it for a
comparison, with no migration of existing vectors.

## Measured results

Why it matters: these are the numbers this stage produced, and they are what any claim about it
rests on.

Measured on an M1 with 8 GB of memory, against the 17-document corpus.

| Measurement | Result |
| ----------- | ------ |
| Ingest 17 files | 83 chunks, 4.8 s wall time, 317 MB peak memory including the model |
| Second ingest of the same folder | 17 unchanged, 0 chunks written |
| Chunk length | Median 79 tokens, largest 221 tokens (90 words) |
| Tokens per word | 1.8 median, 2.5 at p90, 4.1 at most (code and log excerpts) |
| Query latency in a warm process (30 queries) | p50 22 ms, p95 91 ms |
| Part of that latency: embedding the query | p50 about 5 ms |
| Part of that latency: opening a Postgres connection | p50 about 15 ms |
| HNSW recall@5 against exact search, `ef_search` 5 to 100 | 1.000 at every value, about 0.5 ms per SQL query |

- Chunk size: the 4.1 tokens per word in code-heavy chunks is why the default budget is 120 words.
  At that ratio, 200 words would exceed the model's 512-token limit and be truncated.
- `ef_search` at 83 chunks: Postgres chooses a sequential scan over the index for a table this
  small, so search is exact by default. With the index forced, every `ef_search` value from 5 to 100
  returned the exact top 5. The recall and latency trade-off described in
  [Retrieval](../concepts/05-retrieval.md) only appears in larger collections.
- Where the time goes: opening a new database connection per search costs more than the embedding
  and the search combined, which makes a connection pool the first latency fix once a long-running
  server issues repeated queries.
- Where dense search fails: `study query "E1050"`, an error code defined in the Orbit 5.0 release
  notes, does not return that section in its top three. The top results are release-note sections
  mentioning `E1013` and other codes. Questions in plain language, such as "Which Bazel flag turns
  on AddressSanitizer?", rank a correct section first. This is the gap the hybrid retrieval chunk
  closes with full-text search.

## Interview questions

Why it matters: the questions this stage invites, with answers short enough to say out loud.

How does `ef_search` trade recall for latency, and why is `m` different?
: `ef_search` is the size of the candidate list HNSW keeps during a query. A larger list explores
  more of the graph, so it misses fewer true neighbors and takes longer, and it can change per
  query. `m` is the number of links each node keeps, part of the graph's structure, so changing it
  means rebuilding the index. On this corpus every `ef_search` gave recall@5 of 1.0, because 83
  vectors are too few for the approximation to miss anything.

Why did Postgres not use the HNSW index?
: The planner estimates that a sequential scan of a small table plus a sort is cheaper than an
  index scan, and for 83 rows it is right. The index starts to pay off as the table grows. Forcing
  it with `enable_seqscan = off` was only done to measure recall.

Why do per-model embedding columns make embedder swaps additive?
: Each model gets its own `vector(N)` column and index, registered at runtime. Adding
  `bge-base-en-v1.5` adds a 768-dimension column beside the 384-dimension one, while the existing
  column keeps serving queries. A shared column would need an in-place `ALTER` of the column every
  row and query depends on.

Why does dense retrieval miss exact error codes?
: The embedding model places text by meaning, and it was never trained to separate `E1050` from
  `E1013`. Both become nearly the same vector, surrounded by similar release-note text. Lexical
  search matches the exact token, which is why the design adds full-text search and fuses the two
  result lists.

How is ingestion idempotent?
: Document ids are `uuid5` of the relative path, and content is identified by a SHA-256 hash. A
  stored document with the same hash and chunks is skipped. The same path with a new hash raises
  `DuplicateIdError` from the store, and ingestion replaces that document and its chunks.

Why load the model lazily?
: Constructing the embedder happens in every command and test that needs the configuration, but
  only some of them embed text. Deferring the load means those paths never download or load the
  64 MB model, and a configuration error is still caught at construction because the model list
  check needs no files.

Why prefix each chunk with its heading path?
: The corpus repeats section names such as "Fix" in every CI write-up. Without the path, those
  chunks look alike to the embedding model and to a reader of a citation. With it, the chunk says
  which incident it belongs to.

Why is the query embedded differently from the documents?
: The bge v1.5 models were trained with an instruction on short queries. `embed_query` adds it
  and `embed_documents` does not. fastembed did not add it automatically, which a probe confirmed,
  so the application does, and the prefix is a setting so its effect can be measured.
