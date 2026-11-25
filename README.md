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

Phase 1 — Storage + Schema is complete. Next is Phase 1.5 — MVP (issue #45), a thin end-to-end
slice from ingestion to a cited answer. Its models are settled: `fastembed` runs the embedder and
reranker locally (ADR 0010), and generation uses Groq's free plan (ADR 0011). The repo contains the
`uv` workspace root, the
shared `packages/rag_core/` library with the pgvector storage layer behind a `StoreProtocol`
interface (with in-memory fakes in the dev-only `packages/rag_core_testing/` for DB-free unit
tests), and the Postgres + pgvector dev stack.
Embeddings are stored in per-model columns registered at runtime (ADR 0008); re-embedding between
models is still to come (issue #15).
Later phases add ingestion, retrieval logic, the CLI, MCP server, FastAPI backend, and React
frontend.

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

Verify pgvector is live:

```sh
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dx'
```

The `vector` extension should appear in the list.
