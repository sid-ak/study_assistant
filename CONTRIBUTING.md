# Contributing

## Development setup

```sh
cp .env.example .env
uv sync                 # resolves the workspace + dev tooling
pre-commit install      # installs the git hooks
```

## Workflow

- One language, one workspace. Everything is a `uv` workspace member under `packages/` (and, in
  later phases, `cli/`, `services/`, `apps/web/`). Run `uv sync` from the repo root.
- Quality gates run in pre-commit and CI: `ruff` (lint + format) and `mypy` (typecheck). Run them
  all locally before pushing:

  ```sh
  pre-commit run --all-files
  uv run pytest
  uv run sphinx-build -b html docs site -W
  ```

- CI (`.github/workflows/ci.yaml`) runs the same checks on every push and pull request, plus a docs
  build (`sphinx-build ... -W`). It builds and tests, but does not deploy (see
  [ADR 0003](docs/decisions/0003-local-single-user-scope.md)); the docs site is deployed separately
  by `.github/workflows/docs-deploy.yaml`.

## Branches & Commits

- Branch names and commit messages must start with the GitHub issue number they address — the issue
  number, not the phase number.
  - Branch: the bare number, e.g. `1-foundations` (issue #1), `4-embeddings` (issue #4). (`#` isn't
    valid in branch names.)
  - Commit message: prefix with `#<number>` so GitHub auto-links the issue, e.g.
    `#1 add pgvector schema`.
  - Checkpoint commit messages: `checkpoint: <text>` (optional `#<number>-` prefix). Recorded when
    the commit is merged into `dev`, not on the feature-branch push.

## Governance (`AGENTS.md`)

Architectural invariants are encoded as scoped `AGENTS.md` files placed where the work happens.
Canonical content lives in `AGENTS.md`; each `CLAUDE.md` is a one-line `@AGENTS.md` import stub —
edit `AGENTS.md`, not the stub. Honor the primary conventions (retrieval lives only in `rag_core`;
lazy `torch` loading; embedder/reranker behind an interface).

## Architectural decisions

Significant decisions are recorded as ADRs in [`docs/decisions/`](docs/decisions/). Add a new
numbered record (see [`docs/decisions/README.md`](docs/decisions/README.md)) rather than silently
changing direction.

## Issues / roadmap

Work is tracked as phases on GitHub Issues, which are the source of truth. `docs/issues.md` is an
auto-generated mirror: the `sync-issues` workflow (`.github/workflows/sync-issues.yaml`) regenerates
and commits it whenever an issue is opened, closed, edited, or relabeled. Manage issues on GitHub —
don't hand-edit `docs/issues.md`. Issue bodies are not mirrored.
