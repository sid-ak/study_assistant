# Study Assistant

A local, single-user RAG study assistant over course materials (lecture slides, papers, notes). It
answers questions with synthesis from a language model, grounded in retrieved sources, with
citations back to the exact source slide or page. Ingestion and retrieval run entirely on-machine,
offline, and for free. Generation goes through any OpenAI-compatible endpoint: the MVP uses a free
hosted model, and a local runtime works through the same adapter.

- Design: [`docs/architecture.md`](docs/architecture.md)
- Decisions: [`docs/decisions/`](docs/decisions/) (ADRs)
- Roadmap: [GitHub issues](https://github.com/sid-ak/study_assistant/issues) (phased)

## Status

Phase 1 — Storage + Schema and Phase 1.5 — MVP (issue #45) are complete: a thin end-to-end slice
from ingestion to a cited answer a person approved, built in seven chunks and measured at each step.
Its models are settled: `fastembed` runs the embedder and reranker locally (ADR 0010), and
generation uses Groq's free plan (ADR 0011).

[`docs/walkthrough.md`](docs/walkthrough.md) is the MVP end to end with its measured results, and
the chunk summaries below say what each step added.

Measured over ten golden questions on the 17-document corpus, reproduced from a fresh clone:

| | Recall@5 | MRR | p50 | p95 |
| --- | --- | --- | --- | --- |
| Dense | 0.90 | 0.88 | 26 ms | 42 ms |
| Dense, reranked (the default) | 0.95 | 0.83 | 283 ms | 418 ms |
| Hybrid, reranked | 0.95 | 0.83 | 330 ms | 451 ms |

The agent answers all ten, cites only chunks it was shown (grounding 1.00), and reaches citation
recall 0.95 with reranking, at a median of about 1 s per question.

Chunk 1 (#46) adds ingestion and dense retrieval:

- The `study` CLI (`cli/`) ingests a folder of markdown with `study ingest <folder>` and searches
  it with `study query "<text>"`, printing each chunk's cosine distance and the latency.
- Ingestion splits documents at their headings, embeds each chunk with `bge-small-en-v1.5`, and
  stores it in that model's own pgvector column (ADR 0008). Re-runs write only changed files.
- Retrieval ranks chunks by cosine distance. Postgres uses the column's HNSW index once the
  table is large enough to prefer it over an exact scan, and `ef_search` is settable per query.
- The MVP corpus is an original set of release-engineering documents in
  `corpus/release_engineering/` (ADR 0009).

Chunk 2 (#47) adds the golden-set evaluation harness in `evals/`. Ten golden
questions are labeled by document and section heading rather than by chunk, so labels survive
re-chunking. `study-eval <name>` scores them against the ingested corpus, reporting Recall@5, MRR,
and p50 and p95 latency, and saves the run in `evals/results/`. The dense baseline with
`bge-small-en-v1.5` scores Recall@5 0.90 and MRR 0.88. An exact error code ranks third, and two
questions whose answer spans two documents find only one of their sections. `study embed` fills a
newly registered model's column for the chunks already stored, and with it `bge-base-en-v1.5`
measured the same Recall@5 at 16 ms more median latency, so `bge-small-en-v1.5` stays the default.

Chunk 3 (#48) adds the generation lane:

- `services/mcp_server` exposes retrieval as one MCP `search` tool. The agent in `services/api`
  reaches retrieval only through it, and a test fails if the agent's code imports `rag_core`.
- The agent is a fixed state machine (ADR 0012): search, grade the top hit's similarity against a
  threshold, then answer, or rewrite the query and search once more, or stop with "insufficient
  context". It makes at most two searches and two model requests per question.
- Answers come from Groq's free plan (ADR 0011) as strict JSON with the cited chunk ids, limited to
  the chunks the model was shown. `study-ask "<question>"` prints the answer and its sources.
- `study-eval-agent <name>` checks citations over the golden set: all ten answered, all grounded,
  with citation recall 0.90.

Chunk 4 (#49) adds reranking, on by default: dense search fetches 20 candidates and the
`jina-reranker-v1-tiny-en` cross-encoder rescores them. Recall@5 rises from 0.90 to 0.95 and the
agent's citation recall from 0.90 to 0.95, for about 255 ms more per search, and the agent grades
relevance on the reranker's score.

Chunk 5 (#69) adds hybrid retrieval behind `HYBRID_ENABLED`: Postgres full-text search, ranked by
`ts_rank` (an approximation of BM25), runs beside dense search, and Reciprocal Rank Fusion merges
the two lists before reranking. On the golden set it changes no ranking once reranking is on, so it
is off by default; with reranking off it finds exact codes dense search misses.

Chunk 6 (#70) puts a person in the loop. With `study-ask "<question>" --review` the run stops after
retrieval, lists the sources it would answer from with the relevance each was ranked by, and prints
a thread id. The paused run is saved in Postgres, so the decision can come later, from another
process: `study-ask --resume <thread-id> --approve` answers from those sources, and `--reject`
spends the next hop on a rewritten query and stops at the same checkpoint again.

Chunk 7 (#50) is the code freeze: a fresh clone was taken through this README, the docs were checked
against the code, and the walkthrough was written. What is known to be missing is listed at the end
of [the walkthrough](docs/walkthrough.md).

After the MVP, `study-chat` (`apps/chat/`) adds a local Streamlit chat page over the same agent,
so questions can be asked one after another without the command line. It is a stopgap ahead of the
planned React frontend: it runs one full agent run per question, with no streaming and no approval
step.

Later phases add the FastAPI backend and the React frontend.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker for Postgres + pgvector (Docker Desktop or Colima on macOS). `docker compose up -d`
  bind-mounts `infra/postgres/init.sql`, so the clone has to sit in a folder the Docker runtime
  shares with its virtual machine — under your home directory with Colima's defaults. Outside it,
  the mount becomes an empty directory, the test database is never created, and every integration
  test fails to connect.
- [`pre-commit`](https://pre-commit.com/) — `uv tool install pre-commit`

## Quickstart

```sh
cp .env.example .env          # then edit secrets
uv sync                       # resolve + install the workspace
pre-commit install            # enable lint/format/typecheck hooks
docker compose up -d          # start Postgres with the vector extension
uv run pytest                 # run the test suite
```

Ingest the MVP corpus and search it. The first ingestion downloads the 63 MB embedding model, and
the first search downloads the 126 MB reranker, which is on by default.

```sh
uv run study ingest corpus/release_engineering
uv run study query "Which Bazel flag turns on AddressSanitizer?"
```

Score retrieval on the golden set and save the run as `evals/results/<name>.json`. The saved runs
and what each one shows are described in
[`evals/results/README.md`](evals/results/README.md):

```sh
uv run study-eval my-run
```

Ask the agent a question. It needs `GENERATION_API_KEY` in `.env` (a free Groq key), and it starts
the MCP server itself:

```sh
uv run study-ask "Which Bazel flag runs every test under AddressSanitizer?"
uv run study-eval-agent my-agent-run
```

Or ask from a chat page in the browser. It listens on `localhost:8501` only, and runs the same agent
once per message:

```sh
uv run study-chat
```

Approve the sources before the answer is written. The first command prints the thread id to use in
the second, and the paused run waits in the database until a decision arrives:

```sh
uv run study-ask "Which Bazel flag runs every test under AddressSanitizer?" --review
```

```sh
uv run study-ask --resume <thread-id> --approve
```

Verify pgvector is live:

```sh
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dx'
```

The `vector` extension should appear in the list.
