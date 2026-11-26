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

Phase 1 — Storage + Schema is complete. Phase 1.5 — MVP (issue #45) is in progress: a thin
end-to-end slice from ingestion to a cited answer, built in seven chunks. Its models are settled:
`fastembed` runs the embedder and reranker locally (ADR 0010), and generation uses Groq's free
plan (ADR 0011).

Chunk 1 (#46) adds ingestion and dense retrieval:

- The `study` CLI (`cli/`) ingests a folder of markdown with `study ingest <folder>` and searches
  it with `study query "<text>"`, printing each chunk's cosine distance and the latency.
- Ingestion splits documents at their headings, embeds each chunk with `bge-small-en-v1.5`, and
  stores it in that model's own pgvector column (ADR 0008). Re-runs write only changed files.
- Retrieval ranks chunks by cosine distance. Postgres uses the column's HNSW index once the
  table is large enough to prefer it over an exact scan, and `ef_search` is settable per query.
- The MVP corpus is an original set of release-engineering documents in
  `corpus/release_engineering/` (ADR 0009).

Chunk 2 (#47), the golden-set evaluation harness, is in progress in `evals/`. Ten golden
questions are labeled by document and section heading rather than by chunk, so labels survive
re-chunking. `study-eval <name>` scores them against the ingested corpus, reporting Recall@5, MRR,
and p50 and p95 latency, and saves the run in `evals/results/`. Re-embedding existing chunks into a newly
registered model's column is still to come (issue #15). Later phases add the MCP server, the
FastAPI backend, and the React frontend.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker (Docker Desktop on macOS) for Postgres + pgvector
- [`pre-commit`](https://pre-commit.com/) — `uv tool install pre-commit`

## Quickstart

```sh
cp .env.example .env          # then edit secrets
uv sync                       # resolve + install the workspace
pre-commit install            # enable lint/format/typecheck hooks
docker compose up -d          # start Postgres with the vector extension
uv run pytest                 # run the test suite
```

Ingest the MVP corpus and search it. The first run downloads the 64 MB embedding model.

```sh
uv run study ingest corpus/release_engineering
uv run study query "Which Bazel flag turns on AddressSanitizer?"
```

Verify pgvector is live:

```sh
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dx'
```

The `vector` extension should appear in the list.
