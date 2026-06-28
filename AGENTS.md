# Study Assistant — Agent Context

A local, single-user RAG study assistant over course materials (slides, papers, notes). It answers
questions with synthesis from Claude, grounded in retrieved sources, with citations back to the
exact source slide/page. Ingestion and retrieval run entirely on-machine; only generation calls the
Anthropic API.

Start here: [`docs/architecture.md`](docs/architecture.md) is the full design. Locked decisions live
as ADRs in [`docs/decisions/`](docs/decisions/). Work is tracked as phases in
[`docs/issues.md`](docs/issues.md).

## Resuming work (fresh agent)

To pick up where the project was left off — whether between phases or mid-phase — orient in this
order. Docs (1–3) state intent; repo metadata (4) is the ground truth and is what reveals progress
made within or between phases. If they disagree, trust the tree and git, then update the docs.

1. General context — read [`docs/architecture.md`](docs/architecture.md) (target design) and
   [`docs/decisions/`](docs/decisions/) (ADRs — locked decisions and constraints) to understand the
   system and why it is the way it is.
2. `README.md` → Status and [`docs/checkpoints.md`](docs/checkpoints.md) — the quickest read of the
   current phase, plus an append-only table of every major iteration (branch, phase, checkpoint)
   showing how the project got here.
3. [`docs/issues.md`](docs/issues.md) — the phase roadmap: closed phases are done, the
   lowest-numbered open phase is next up, and child rows flag in-flight improvements.
4. Repo metadata (ground truth) — confirm the docs against reality; this also exposes work done
   within or between phases:
   - Branch name (e.g. `4-embeddings`) — usually names the active phase.
   - `git log` plus staged/unstaged changes — the most recent real work and anything in progress.
   - Actual tree — which packages/modules exist versus the architecture's target layout.
   - `uv sync` then `uv run pytest` — install the workspace and run the tests to see what is
     actually implemented and passing.

[`docs/checkpoints.md`](docs/checkpoints.md) is appended automatically — by the `sync-checkpoints`
workflow on phase-PR merges and `checkpoint:` commits (see `CONTRIBUTING.md`); do not hand-edit it.
At every major iteration still update the manual living docs so the next agent can resume cleanly:
the `README.md` Status blurb and the "Workspace layout" section below. Name branches starting with
their GitHub issue number (e.g. `1-foundations` for issue #1) so checkpoints attribute correctly.

## Governance model

Canonical context lives in `AGENTS.md` files (tool-neutral). Each `CLAUDE.md` is a one-line
`@AGENTS.md` import stub so Claude Code's directory-walk loading picks up the same content. Edit
`AGENTS.md`, never the stub. Each package/service carries its own scoped `AGENTS.md` describing its
surface; this one is the root entry point.

## Primary conventions (enforced)

- Retrieval lives only in `rag_core`. The MCP server and API are consumers, never reimplementers
  ([ADR 0001](docs/decisions/0001-rag-retrieval-boundary.md)).
- Lazy model loading: no `torch` import at module top-level outside `embed/` and `rerank/`
  ([ADR 0002](docs/decisions/0002-local-embedding-and-reranking.md)).
- Embedder/reranker behind a small interface so the system is agnostic to the concrete model; the
  only hard lock-in is the pgvector embedding dimension (`vector(N)`).
- Secrets via `.env` (documented in `.env.example`), single local user, no auth
  ([ADR 0003](docs/decisions/0003-local-single-user-scope.md)).
- Never commit; only stage. Do not run `git commit`. At the end of a set of changes, `git add` the
  relevant files and leave them staged for the human to review and commit — but only if there are
  currently 0 staged files. If anything is already staged, do not stage at all; leave the working
  tree as-is for the human.

## Stack & tooling

- Python 3.12, `uv` workspace. Lint/format (`ruff`) and typecheck (`mypy`) run in pre-commit and CI.
- PostgreSQL + pgvector is the single store, stood up via `docker compose`.
- Models: Claude via the Anthropic SDK (`claude-opus-4-8`); `bge-m3` embeddings and
  `bge-reranker-v2-m3` reranking run in-process.

## Workspace layout

The repo is built phase by phase (see `docs/issues.md`). Today the workspace contains the root and
`packages/rag_core/` (the shared retrieval library — the foundation everything else depends on).
`cli/`, `services/`, and `apps/web/` are added in their respective phases; the target tree is
documented in `docs/architecture.md`.

## Common commands

```sh
uv sync                       # resolve + install the workspace
docker compose up -d          # start Postgres + pgvector
pre-commit install            # enable hooks
pre-commit run --all-files    # lint + format + typecheck
uv run pytest                 # run tests
```
