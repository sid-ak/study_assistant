# 02. Evaluation Harness

> Part of the [Project](README.md) section of [AI, RAG & Python](../README.md). Built in
> [study_assistant#47](https://github.com/sid-ak/study_assistant/issues/47), pull request
> [study_assistant#72](https://github.com/sid-ak/study_assistant/pull/72).

Chunk 2 built the measurement every later chunk is judged by. Ten questions about the corpus are
labeled with the document sections that answer them. `study-eval` sends each question through the
same `retrieve` function the CLI uses, scores the top five chunks against the labels, times the
retrievals, and saves the run. Two runs are recorded: the default `bge-small-en-v1.5` embedder,
and `bge-base-en-v1.5` registered beside it and given vectors for the same chunks by a new
`study embed` command.

| Piece | Module | What it does |
| ----- | ------ | ------------ |
| Golden set | `evals/golden/questions.toml` | Ten questions, each labeled by document path and section heading |
| Loader and label check | `evals/golden.py` | Rejects malformed files, and checks every label names a heading in the corpus |
| Metrics | `evals/metrics.py` | Label matching, recall, reciprocal rank, nearest-rank percentiles |
| Runner | `evals/runner.py` | `run_eval` scores a golden set, `write_run` saves it as JSON |
| Command | `evals/main.py` | `study-eval <name>` |
| Re-embedding | `rag_core/embed/backfill.py`, `rag_core/store/` | Fills a newly registered model's column for chunks already stored |
| Command | `cli/` | `study embed` |

The general theory is in [Evaluation](../concepts/09-evaluation.md).

## The golden set

Why it matters: without a fixed set of questions with known answers, every change is judged by
impression. This is the stage that turned the rest of the project from opinion into measurement,
which is why it was built before reranking or hybrid search.

Each question lists every section that answers it, by the document's path under the corpus folder
and one of its headings.

```toml
[[questions]]
id = "workers-flag-replacement"
text = "Which option replaces --orbit-workers?"
expected = [
    { document = "releases/orbit-4.1.md", section = "Deprecations" },
    { document = "releases/orbit-5.0.md", section = "Breaking changes" },
]
```

- Labels outlive chunking: ingestion records each chunk's `source` and its heading path in
  `metadata`, so a retrieved chunk is checked against a label by those two fields. Changing the
  chunk size changes chunk ids and boundaries, and no label has to change.
- The question mix: paraphrases that share few words with their answer, one exact error code
  (`E1050`), and five questions whose answer is spread over two documents, such as a release note
  and the CI write-up about the same change.
- Strict loading: TOML is read with the standard library's `tomllib`, and the loader rejects
  unknown keys, empty fields, duplicate ids, and questions without labels. A misspelled key such as
  `expect` fails instead of producing a question with no labels.
- Label check: `check_labels` parses each labeled document with the same section parser ingestion
  uses, and fails if a label's heading is not in any section's heading path. A unit test runs it
  over the committed golden set and corpus, so renaming a heading in the corpus fails CI.

## Matching chunks to labels and scoring

Why it matters: a label has to survive re-chunking, or the set has to be rewritten every time the
chunker changes. How a retrieved chunk is matched to a label is what decides that.

A chunk matches a label when it comes from the labeled document and the labeled heading is anywhere
in its heading path, so chunks from a subsection also match.

??? example "chunk_matches"

    ```python
    def chunk_matches(metadata: dict[str, Any], expected: ExpectedSection) -> bool:
        if metadata.get("source") != expected.document:
            return False
        return expected.section in metadata.get("headings", [])


    def section_recall(ranked: list[dict[str, Any]], expected: tuple[ExpectedSection, ...]) -> float:
        found = 0
        for section in expected:
            for metadata in ranked:
                if chunk_matches(metadata, section):
                    found += 1
                    # One matching chunk is enough; more chunks from the same section add nothing.
                    break
        return found / len(expected)
    ```

Source: [`evals/src/evals/metrics.py:13-48`](https://github.com/sid-ak/study_assistant/blob/8ae689b/evals/src/evals/metrics.py#L13-L48)

- Recall per question is the share of its labeled sections found in the top five, so a question
  with two labels and one found scores 0.5. Recall@5 for a run is the mean over questions.
- Reciprocal rank is one over the rank of the first chunk matching any label, and MRR is its mean.
- Latency percentiles use the nearest-rank method, so p95 is always a measured latency rather than
  a value interpolated between two.

## The runner and `study-eval`

Why it matters: a harness that measures a different code path than production measures nothing.
This one calls the same entry point the command line and the agent call.

`run_eval` retrieves each question `repeats` times and scores the first ranking.

??? example "run_eval"

    ```python
    # Untimed warm-up: an embedder that loads its model on first use does it here.
    retrieve(questions[0].text, embedder=embedder, store=store, limit=k, ef_search=ef_search)

    for question in questions:
        attempts: list[RetrievalResult] = []
        for _ in range(repeats):
            attempts.append(
                retrieve(
                    question.text, embedder=embedder, store=store, limit=k, ef_search=ef_search
                )
            )
        latencies = [attempt.latency_ms for attempt in attempts]
    ```

Source: [`evals/src/evals/runner.py:85-175`](https://github.com/sid-ak/study_assistant/blob/8ae689b/evals/src/evals/runner.py#L85-L175)

- Same path as production: the harness calls `rag_core`'s `retrieve`, the function the CLI calls
  and the agent will call through its search tool, so a run measures the real path rather than a
  copy of it.
- Warm-up: the embedder loads its model on first use, which takes far longer than a query. One
  untimed retrieval absorbs that load, so it never appears in the percentiles.
- Repeats: each question is timed five times by default, giving 50 samples per run. With one
  sample per question, p95 of ten values would just be the slowest query.
- Inputs first: `study-eval` checks the run name, the golden set, and every label before it
  retrieves anything, and exits with status 2 on any problem.
- Saved runs: `write_run` serializes the run with `dataclasses.asdict` and opens the file with
  mode `"x"`, which fails if the file exists, so a saved run is never overwritten. The name is
  limited to letters, digits, dots, dashes, and underscores, so it cannot point outside the results
  folder.

## Embedding stored chunks with a second model

Why it matters: comparing two embedding models needs both models' vectors over the same chunks.
This is the step that fills a newly registered model's column without re-reading the corpus.

Ingestion skips a file whose content is already stored, so ingesting with a second model would add
nothing to that model's column. Two methods on `StoreProtocol` close the gap:

- `get_unembedded_chunks(limit)` lists chunks with no vector from the store's bound model, in the
  order they were added.
- `set_embeddings(rows)` writes vectors into the bound model's column only, replacing any vector
  already there, and fails the whole batch on an unknown chunk id, a wrong dimension, an all-zero
  vector, or a repeated id.

??? example "embed_missing"

    ```python
    def embed_missing(
        store: StoreProtocol, embedder: EmbedderProtocol, *, batch_size: int = DEFAULT_BATCH_SIZE
    ) -> int:
        check_same_model(embedder, store)
        embedded = 0
        while True:
            rows = store.get_unembedded_chunks(limit=batch_size)
            if not rows:
                return embedded
            texts = [row["content"] for row in rows]
            vectors = embedder.embed_documents(texts)
            updates: list[dict[str, Any]] = []
            for row, vector in zip(rows, vectors, strict=True):
                updates.append({"id": row["id"], "embedding": vector})
            store.set_embeddings(updates)
            embedded += len(updates)
    ```

Source: [`packages/rag_core/src/rag_core/embed/backfill.py:13-39`](https://github.com/sid-ak/study_assistant/blob/8ae689b/packages/rag_core/src/rag_core/embed/backfill.py#L13-L39)

- The loop asks the store again on every pass rather than keeping an offset. Each pass's vectors
  are stored before the next request, so the next request returns only what is still missing, and
  the loop ends when nothing is.
- `study embed` registers the configured model without making it current, then runs
  `embed_missing`. Run with `EMBEDDING_MODEL=BAAI/bge-base-en-v1.5` and `EMBEDDING_DIMENSION=768`,
  it filled the second column for all 83 chunks while `bge-small-en-v1.5` stayed current.
- In the database, each row is one `UPDATE` inside one transaction. An update that changes no row
  means the id names no chunk, and raising inside the connection's `with` block rolls back the rows
  already updated.
- The in-memory fake checks every id before writing any, so both stores fail the same batches the
  same way, and one contract suite runs against both.

## Python used

Why it matters: these are the language features this stage leans on, listed so the page can be
read as Python practice as well as design.

| Feature | Where it appears | What it does here |
| ------- | ---------------- | ----------------- |
| `tomllib` | `load_golden` | Reads TOML with the standard library, so the harness adds no dependency |
| `@dataclass(frozen=True)` | `GoldenQuestion`, `ExpectedSection`, `EvalRun` | Immutable value objects; frozen ones compare by value in tests |
| `dataclasses.asdict` | `write_run` | Turns a run and the dataclasses nested in it into dicts and lists for `json.dump` |
| `open(..., "x")` | `write_run` | Exclusive creation: fails with `FileExistsError` instead of overwriting |
| `re.fullmatch` | `run_path` | Checks the whole run name against the allowed characters |
| `math.ceil` | `percentile` | The nearest rank; multiplying before dividing keeps `95 * 20 / 100` exactly 19 |
| `isinstance` checks | `read_tables`, `read_string` | Validates parsed TOML, whose values can be any type |
| `[project.scripts]` | `evals/pyproject.toml` | Installs `study-eval` as a command in the workspace environment |
| `zip(..., strict=True)` | `embed_missing` | Raises if the model returns a different number of vectors than texts |
| pytest `parametrize` with `ids` | Golden-set and store tests | One test per malformed file or bad batch row, each named in the output |

## Design trade-offs

Why it matters: each row is a decision that could have gone the other way, with the record that
settled it and the alternative it rejected.

| Decision | Chosen | Rejected alternative | Record |
| -------- | ------ | -------------------- | ------ |
| What a label names | Document path and section heading | Chunk ids, which change whenever chunking does | Pull request #72 |
| How the eval runs | A console script that saves a JSON file | A pytest test, which would need the database and model in CI and reports pass or fail rather than a measurement | Pull request #72 |
| Metrics | Recall@5 and MRR, with p50 and p95 latency | Recall alone, which cannot show a reranker's reordering | Pull request #72 |
| Filling a second model's column | A separate `study embed` | Making `study ingest` re-embed unchanged files, which mixes "what changed in the folder" with "what this model is missing" | Pull request #72 |
| Default embedder after the comparison | `bge-small-en-v1.5` | `bge-base-en-v1.5`, which showed no recall gain | [ADR 0010](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0010-lightweight-embedding-and-reranking-models.md) |

Per-model columns made the comparison additive. Registering `bge-base-en-v1.5` added a 768-dimension
column and index beside the 384-dimension one, `study embed` filled it, and the default model kept
serving queries throughout.

## Measured results

Why it matters: these are the numbers this stage produced, and they are what any claim about it
rests on.

Ten golden questions, 83 chunks, `k = 5`, 5 timed retrievals per question, default `ef_search`, on
an M1 with 8 GB of memory.

| Run | Embedding model | Recall@5 | MRR | p50 latency | p95 latency |
| --- | --------------- | -------- | --- | ----------- | ----------- |
| Dense baseline | `bge-small-en-v1.5`, 384 dimensions | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| Comparison | `bge-base-en-v1.5`, 768 dimensions | 0.90 | 0.85 | 42.1 ms | 56.1 ms |

- The baseline's weak spots: "What does error E1050 mean?" ranks its section third, behind two
  release-note sections that list other error codes. The tokenizer splits `E1050` into `e`,
  `##10`, and `##50`, and `E1013` into `e`, `##10`, and `##13`, so the codes share most of their
  input to the model. "What CMake version does Orbit 5.0 require?" ranks Orbit 4.0's breaking
  changes first and misses Orbit 5.0's, and the two version strings differ in a single token.
- Same sections, different order: both models find exactly the same labeled sections for every
  question. `bge-base-en-v1.5` ranks the first match higher on two questions and lower on two
  others, which nets to an MRR 0.03 lower, less than one question's worth of change.
- Cost of the larger model: 16 ms more at the median. ADR 0010's probe measured query embedding at
  12 ms for `bge-base-en-v1.5` against 4 ms for `bge-small-en-v1.5`, which accounts for most of the
  gap. `study embed` for 83 chunks took 28 s including the 208 MB download, with a 905 MB peak.
- Noise: two runs of the same baseline configuration differed by about 4 ms at p50 and 16 ms at
  p95, so latency differences of that size are not results.

## Interview questions

Why it matters: the questions this stage invites, with answers short enough to say out loud.

Why label the golden set by section instead of by chunk?
: Chunk ids and boundaries are produced by the chunker, so any change to chunking would invalidate
  chunk-level labels. Sections are written by the document's author and stay put. Each retrieved
  chunk carries its source and heading path in metadata, so it can be checked against a section
  label whatever the chunking.

Why report MRR next to Recall@5?
: Recall@5 says whether a labeled section reached the top five and ignores its position. MRR says
  how high the first correct chunk ranked. A reranker only reorders candidates, so its effect shows
  in MRR while Recall@5 over the same candidates can stay unchanged.

Why p95 instead of the average latency?
: An average is pulled up by a few slow requests and describes none of them. p95 says how slow the
  slowest one in twenty requests is, which is what a user experiences as unreliability. Each
  question is timed five times so the run has 50 samples and p95 is not just the single slowest.

Why did the larger embedding model not become the default?
: It found exactly the same labeled sections, and its MRR was 0.03 lower, within one question's
  change. It cost 16 ms more per query, twice the vector storage, and about twice the memory to
  load. A recall gain was the stated condition for switching, and there was none.

How do you add a second embedding model without re-ingesting?
: Register it, which adds its own vector column and HNSW index. Then list the chunks with no
  vector in that column, embed their stored text in batches, and write the vectors into that
  column only. The current model keeps serving queries the whole time, and the comparison is a
  matter of binding the store and embedder to the other model.

How small is too small for a golden set?
: With ten questions, one question changing moves Recall@5 or MRR by 0.1 or less, so differences
  below that are not evidence. Ten is enough to catch large regressions and to compare methods
  with clear effects, and the failures it exposes, such as exact codes and multi-document answers,
  are the cases the next chunks target.
