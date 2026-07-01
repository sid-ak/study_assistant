# Study Assistant — Agent Context

A local, single-user RAG study assistant over course materials (slides, papers, notes). It answers
questions with synthesis from Claude, grounded in retrieved sources, with citations back to the
exact source slide/page. Ingestion and retrieval run entirely on-machine; only generation calls the
Anthropic API.

## Getting Oriented

- Read [`docs/architecture.md`](docs/architecture.md), it is the full design.
- Read ADRs under [`docs/decisions/`](docs/decisions/), locked decisions live there.
- Read [`docs/issues.md`](docs/issues.md), work is tracked as phases there.
- Read [`docs/checkpoints.md`](docs/checkpoints.md), completed work is tracked there.
- Read [`README.md`](README.md), Status blurb states intent.
- Compare against repo, which is the ground truth.
  - Scan with `ls` and compare with directory structure in `architecture.md` to gauge progress.
  - Use `git log` to reveal further current progress whether in between phases or mid-phase.
- Fetch the current issue being worked on from the GitHub repo, read its full content.
  - Also read the full content of the current issue's sub issues (if any).

## Governance model

Canonical context lives in `AGENTS.md` files (tool-neutral). Each `CLAUDE.md` is a one-line
`@AGENTS.md` import stub so Claude Code's directory-walk loading picks up the same content. Edit
`AGENTS.md`, never the stub. Each package/service carries its own scoped `AGENTS.md` describing its
surface; agents read the nearest file in the tree, so the closest one wins. This file is the root
entry point — keep package-specific detail in the package's own `AGENTS.md`.

## Dev environment tips

- Python 3.12 on a `uv` workspace. Run `uv sync` once to resolve and install every workspace member
  (root + `packages/*`) into a single `.venv`.
- Run tools through the workspace venv with `uv run <cmd>` (e.g. `uv run pytest`); do not call a
  global `python`/`pip`.
- Add a runtime dependency by editing the owning package's `pyproject.toml` `dependencies`, then
  `uv sync`. Add a dev/test-only tool to the root `[dependency-groups] dev` instead.
- Bring up the store with `docker compose up -d` (PostgreSQL + pgvector). Copy `.env.example` to
  `.env` first — the connection string and secrets live there. The DB is required for the store
  layer and its tests.
- New workspace members go under `packages/` (libraries) or top-level (`cli/`, `services/`,
  `apps/web/`) per `docs/architecture.md`; each gets its own scoped `AGENTS.md` plus a one-line
  `CLAUDE.md` stub (`@AGENTS.md`).
- Install hooks once with `pre-commit install`; `pre-commit run --all-files` runs lint + format +
  typecheck across the tree.

## Testing instructions

- The CI plan is in `.github/workflows/ci.yaml`: a `checks` job (ruff lint, ruff format check, mypy,
  pytest against a pgvector service) and a `docs` job that builds the Sphinx site
  (`uv run sphinx-build -b html docs site -W`, build-only — deployment lives in `docs-deploy.yaml`).
- Run the whole suite with `uv run pytest`. Integration tests need the database — run
  `docker compose up -d` first or they fail to connect.
- Integration tests are marked `@pytest.mark.integration`. Scope a run with
  `uv run pytest -m "not integration"` (fast, no DB) or `-m integration` (DB-backed); target one
  test with `uv run pytest -k "<name>"`.
- Lint, format, and typecheck must also be green:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy`. Fix every error and type
  failure until the whole suite is green before you merge.
- Docs must build clean: `uv run sphinx-build -b html docs site -W` (CI runs this too — `-W` turns
  Sphinx warnings into errors, catching broken toctrees, anchors, and autodoc import failures).
- Add or update tests for the code you change, even if nobody asked.
- Schema changes need a fresh DB: `initialize_schema()` is `CREATE ... IF NOT EXISTS` and will not
  retrofit constraints, so run `docker compose down -v && docker compose up -d` after editing
  `store/schema.py`.

## Code style

- `ruff` formats and lints (line length 100, rule set `E,F,I,UP,B`); `mypy` runs in `strict` mode.
  Both must pass — do not silence them without cause.
- Type every function signature; `mypy --strict` rejects untyped defs. Prefer explicit, narrow types
  over `Any`.

## Binding decisions (ADRs)

The locked architectural decisions are recorded as ADRs, indexed in
[`docs/decisions/`](docs/decisions/). They are binding and the source of truth — read the relevant
ADR before changing what it governs, and do not restate its rules here.

## PR instructions

- Branch from `dev`, naming the branch with its GitHub issue number first (e.g. `4-embeddings` for
  issue #4) so `docs/checkpoints.md` attributes correctly.
- PR title format: `[<phase or package>] <Title>` — e.g. `[rag_core/store] Add schema + CRUD`.
- Run the full gate green before handing off (with `docker compose up -d`):
  `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run sphinx-build -b html docs site -W`.
- Update the `README.md` Status blurb in the same change — current status lives there (and in
  `docs/issues.md` / `docs/checkpoints.md`), not in this file.
- Never commit; only stage. Do not run `git commit`. At the end of a set of changes, `git add` the
  relevant files and leave them staged for the human to review — but only if 0 files are currently
  staged. If anything is already staged, do not stage at all; leave the working tree as-is.
