# Walkthrough: the MVP end to end

This document follows the MVP of Study Assistant from a folder of markdown to a cited answer that a
person approved, in the order the system was built. Each section says what the stage does, the one
decision behind it that was not obvious, and what it measured. Nothing here is aspirational: every
number comes from a saved run in [`evals/results/`](https://github.com/sid-ak/study_assistant/tree/main/evals/results)
or from a command recorded in the pull request that added the stage.

The system answers questions about a corpus of release-engineering documents: build guides, release
notes, and CI failure write-ups. It runs on one machine, for one person, with no per-call cost
beyond a free hosted model's plan.

## What runs today

```text
study ingest   ->  Postgres + pgvector  <-  study query
                            ^
                            | MCP search tool
                            |
study-ask  ->  LangGraph agent  ->  approval checkpoint  ->  cited answer
                            |
                   study-eval, study-eval-agent
```

| Stage | Command | Package |
| ----- | ------- | ------- |
| Ingestion | `study ingest <folder>` | `cli/`, over `packages/rag_core/` |
| Retrieval | `study query "<text>"` | `packages/rag_core/` |
| Retrieval as a tool | started by the agent | `services/mcp_server/` |
| The agent | `study-ask "<question>"` | `services/api/` |
| Approval checkpoint | `study-ask --review`, `--resume` | `services/api/` |
| Measurement | `study-eval`, `study-eval-agent` | `evals/` |

## 1. Storage and schema

Chunk 0, [issue #2](https://github.com/sid-ak/study_assistant/issues/2).

Documents and chunks live in Postgres with the pgvector extension, which holds the text, the
metadata, and the vectors in one store, so a retrieval result and its citation come from one query.

Each embedding model gets its own `vector(N)` column and its own HNSW index, tagged by a model
identifier, rather than one shared column
([ADR 0008](decisions/0008-per-model-embedding-columns.md)). Adding a model is then an additive
schema change, and two models' vectors coexist while one is compared against the other. The
alternative, one column altered in place, makes every model change a migration with no way back.

Every swappable part sits behind a `Protocol` with an in-memory fake beside it
([ADR 0006](decisions/0006-interface-first-architecture.md)), and one parametrized contract suite
runs against both the real store and the fake, so the fake cannot drift into accepting what
Postgres rejects.

## 2. Ingestion and dense retrieval

Chunk 1, [issue #46](https://github.com/sid-ak/study_assistant/issues/46).

`study ingest` splits each markdown document at its headings, embeds every chunk, and writes it with
the heading path that a citation points at. Re-running it hashes each file and writes nothing for
documents that have not changed, which makes the command safe to repeat.

Chunking follows the document's own headings rather than a fixed window. A section is a unit its
author already decided was one, and the heading path is exactly what a citation needs.

The embedder and the reranker run locally on `fastembed`
([ADR 0010](decisions/0010-lightweight-embedding-and-reranking-models.md)): `bge-small-en-v1.5` at
384 dimensions, chosen on an 8 GB machine where a larger model costs memory and latency. The model
is loaded lazily, so a command that never embeds never pays for it.

Measured: the corpus is 17 documents and 83 chunks. Ingestion takes about 4 seconds from an empty
database, and a second run reports 17 unchanged and writes nothing.

## 3. The evaluation harness

Chunk 2, [issue #47](https://github.com/sid-ak/study_assistant/issues/47).

Ten questions, each labeled with the document sections that answer it, and a runner that reports
Recall@5, MRR, and latency percentiles, saving each run as JSON. Every later stage is judged against
it.

Labels name a document and a section heading, not a chunk id. Chunk ids change whenever the chunker
or the corpus changes, which would quietly invalidate the labels; a heading survives re-chunking. A
unit test checks every label against the committed corpus, so a renamed heading fails the build
instead of never matching.

The harness refuses inputs that cannot produce a meaningful number. A model that is registered but
never embedded would score zero on every question, so the runner checks for unembedded chunks first
and exits with a usage error pointing at `study embed`.

Measured, dense retrieval with the default embedder:

| Run | Recall@5 | MRR | p50 | p95 |
| --- | -------- | --- | --- | --- |
| `dense-bge-small` | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| `dense-bge-base` | 0.90 | 0.85 | 42.1 ms | 56.1 ms |

The larger model found nothing more for 16 ms more per search, so the small one stayed the default.
The three questions the baseline missed are the ones the next two stages were built to address: an
exact error code ranked third, and two questions whose answers span two documents found only one
section each.

## 4. The bounded agent over MCP

Chunk 3, [issue #48](https://github.com/sid-ak/study_assistant/issues/48).

Retrieval is exposed as a single MCP `search` tool, and the agent reaches it only through that tool
([ADR 0001](decisions/0001-rag-retrieval-boundary.md)). A test fails on any import of the retrieval
library inside the generation lane, so the boundary is enforced rather than agreed.

The agent is a fixed state machine, not a tool-calling loop
([ADR 0012](decisions/0012-bounded-agent-over-mcp.md)): search, grade the top hit's relevance
against a threshold in code, then answer, or rewrite the query and search once more, or stop with
"insufficient context". Two searches and two model requests is the worst case, known before the run.
On a free plan of 30 requests a minute, an open loop can spend the whole budget on one question, and
a run whose shape depends on the model's mood is hard to measure.

The answer comes back under a strict JSON schema whose `cited_chunk_ids` is an enumeration of the
chunk ids the model was shown, so it cannot cite a document it never saw. The grounding check in the
evaluation verifies it anyway, because the guarantee rests on the provider enforcing the schema.

Measured, over the same ten questions:

| Run | Answered | Grounding | Citation recall | p50 | p95 |
| --- | -------- | --------- | --------------- | --- | --- |
| `agent-qwen3.8-27b` | 10/10 | 1.00 | 0.90 | 1003 ms | 9709 ms |
| `agent-qwen3.8-27b-rerank` | 10/10 | 1.00 | 0.95 | 1026 ms | 12252 ms |

Every answer cited only chunks it was shown, and every question was answered from the first search.
The p95 is one question that waited on the hosted model; the adapter waits out rate limits using the
response headers, and it does not yet log when it does, so a single slow question cannot be
attributed with certainty.

## 5. Reranking

Chunk 4, [issue #49](https://github.com/sid-ak/study_assistant/issues/49).

Dense search fetches 20 candidates and a cross-encoder, `jina-reranker-v1-tiny-en`, scores each one
against the query and keeps the best five. A cross-encoder reads the query and the passage together,
which is what lets it separate two passages that an embedding model places close to each other.

It is on by default. The agent then grades relevance on the reranker's score rather than the cosine
similarity, because that is the number the ranking used.

Measured:

| Run | Recall@5 | MRR | p50 | p95 |
| --- | -------- | --- | --- | --- |
| `dense-bge-small` | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| `dense-bge-small-rerank` | 0.95 | 0.83 | 283.1 ms | 417.5 ms |

Recall@5 rose from 0.90 to 0.95 and the agent's citation recall from 0.90 to 0.95, for about 255 ms
more per search. MRR fell from 0.88 to 0.83: the reranker finds sections the dense ranking missed
entirely, and places some already-found ones a rank lower. For a question that needs every relevant
section, finding more of them is the better trade.

One mistake here is worth recording, because it shaped how later results were checked. An agent run
was first saved as "reranked" when the setting had never reached the MCP server, which runs as a
separate process with a filtered environment. The setting was added to that environment with a test,
and no result is now reported for a mode without a value only that mode can produce.

## 6. Hybrid retrieval

Chunk 5, [issue #69](https://github.com/sid-ak/study_assistant/issues/69).

Postgres full-text search runs beside dense search, and Reciprocal Rank Fusion merges the two ranked
lists before the reranker sees them. Keyword search finds the chunks that contain the question's
exact words, which is where a small embedding model is weakest: it represents `E1050` as a few
generic word pieces that `E1013` shares.

Fusion uses ranks, not scores. Cosine distance and `ts_rank` are on unrelated scales, so summing
them would let either dominate; 1 / (60 + rank) per list needs no calibration.

Measured:

| Run | Recall@5 | MRR | p50 | p95 |
| --- | -------- | --- | --- | --- |
| `dense-bge-small-rerank` | 0.95 | 0.83 | 283.1 ms | 417.5 ms |
| `hybrid-bge-small-rerank` | 0.95 | 0.83 | 330.3 ms | 451.4 ms |

No change on the golden set, which the measurement also explains: the 20 dense candidates already
contained the sections keyword search would add, and the reranker promotes them either way. Twenty
candidates is about a quarter of an 83-chunk corpus. With reranking off, hybrid search does find the
bare query `E1050`'s defining section, which dense search misses. So the setting ships off, with the
reason recorded and a run worth repeating on a larger corpus.

## 7. The approval checkpoint

Chunk 6, [issue #70](https://github.com/sid-ak/study_assistant/issues/70).

A run can stop between the relevance grade and the answer, list the sources it would answer from
with the relevance each was ranked by, and wait. The paused state is saved in Postgres under a
thread id, so the decision can arrive later, from another process.

```sh
uv run study-ask "Which Bazel flag runs tests under AddressSanitizer?" --review
uv run study-ask --resume <thread-id> --approve
```

The pause sits before generation because that is the last point where a decision can still change
the outcome without the answer having been paid for. A rejection costs one of the run's two
searches: it rewrites the query, searches again, and stops at the same checkpoint on what the new
query found. The bound that limits the agent limits the person too.

Durability is the reason for the database. A pause that lives in one process's memory is no use when
the wait is a person's. The test for it runs a second Python process that reads the state out of
Postgres and finishes the answer, with a search client that knows no answers, so a cited answer can
only have come from the saved state.

Measured, live against the corpus: a question paused with five sources and a thread id, four
checkpoint rows were written for that thread, a new process approved them and got the
`--config=asan` answer citing Configs in .bazelrc, a rejection on "What does error E1050 mean?"
rewrote it to "E1050 error code" and paused again, and approving that produced the in-flight-limit
answer citing Orbit 5.0's New features. A question the corpus cannot answer never paused: there was
nothing to approve.

## 8. What a fresh clone does

Chunk 7, [issue #50](https://github.com/sid-ak/study_assistant/issues/50).

The MVP's test is that someone else can run it. A clone of this branch, with `.env` copied from
`.env.example` and a Groq key added, was taken through the README on 2026-11-27: `uv sync`,
`docker compose up -d`, the full test suite, ingestion, a query, an eval run, the agent, the
checkpoint flow, and the agent eval.

| Step | Result from the fresh clone |
| ---- | --------------------------- |
| `uv run pytest` | 513 passed |
| `uv run study ingest corpus/release_engineering` | 17 added, 83 chunks, about 4 s |
| `uv run study query "Which Bazel flag turns on AddressSanitizer?"` | Configs in .bazelrc first, 305 ms |
| `uv run study-eval` | Recall@5 0.95, MRR 0.83, p50 267 ms |
| `uv run study-ask "<question>"` | `--config=asan`, one search, one citation |
| `--review` then `--resume --approve` | Paused with 5 sources, resumed to the same answer |
| `uv run study-eval-agent` | 10/10 answered, grounding 1.00, citation recall 0.95 |

The numbers match the saved runs, which is the point of the exercise: the recorded results are
reproducible from a clean checkout, not artifacts of one working copy.

## 9. What is not built, and what is known to be missing

- Later phases: the FastAPI backend with streaming, the React frontend, the pptx and pdf parsers,
  and course materials in place of the release-engineering corpus
  ([ADR 0009](decisions/0009-mvp-corpus.md)).
- Hybrid search's benefit is unmeasured where it should matter, on a corpus large enough that an
  answer can fall outside the dense candidates.
- Without a reranker, a fused result's relevance is a Reciprocal Rank Fusion score rather than a 0
  to 1 relevance, so the agent's threshold assumes reranking is on whenever hybrid is. Nothing
  enforces that pairing.
- A rejected source list is not remembered. The next search can return the same chunks, and nothing
  tells the model which ones were turned down.
- There is no way to list the runs waiting for a decision; a lost thread id can only be found in the
  `checkpoints` table.
- Saved evaluation runs do not record the query prefix, the chunk size, or the commit they ran on.
- The agent's p95 has one question over 9 seconds that cannot be attributed, because the generation
  adapter does not log the rate-limit waits it performs.
- The in-memory store fake does not model embedder registration, so no fake raises the error the
  real store raises for an unregistered model.
