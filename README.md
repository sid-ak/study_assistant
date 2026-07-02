# Study Assistant

A local, single-user RAG study assistant over course materials (lecture slides, papers, notes). It
answers questions with synthesis from Claude, grounded in retrieved sources, with citations back to
the exact source slide or page. Ingestion and retrieval run entirely on-machine, offline, and for
free; only answer generation calls the Anthropic API.

- Design: [`docs/architecture.md`](docs/architecture.md)
- Decisions: [`docs/decisions/`](docs/decisions/) (ADRs)
- Roadmap: [GitHub issues](https://github.com/sid-ak/study_assistant/issues) (phased)

## Status

Early scaffolding (Phase 0 — Foundations). The repo currently contains the `uv` workspace root, the
shared `packages/rag_core/` library, and the Postgres + pgvector dev stack. Later phases add the
CLI, MCP server, FastAPI backend, and React frontend.

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
