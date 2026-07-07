# Study Assistant — Agent Context

A local, single-user RAG study assistant over course materials (slides, papers, notes). It answers
questions with synthesis from Claude, grounded in retrieved sources, with citations back to the
exact source slide/page. Ingestion and retrieval run entirely on-machine; only generation calls the
Anthropic API.

## Getting Oriented

- Read [`docs/architecture.md`](docs/architecture.md), it is the full design.
- Read ADRs under [`docs/decisions/`](docs/decisions/), locked decisions live there.
- Read the [GitHub issues](https://github.com/sid-ak/study_assistant/issues), work is tracked as
  phases there.
- Read [`README.md`](README.md), Status blurb states intent.
- Compare against repo, which is the ground truth.
  - Scan with `ls` and compare with directory structure in `architecture.md` to gauge progress.
  - Use `git log` to reveal further current progress whether in between phases or mid-phase.
- Fetch the current issue being worked on from the GitHub repo, read its full content.
  - Also read the full content of the current issue's sub issues (if any).

## Governance

Canonical context lives in `AGENTS.md` files (tool-neutral). Each `CLAUDE.md` is a one-line
`@AGENTS.md` import stub so Claude Code's directory-walk loading picks up the same content. Edit
`AGENTS.md`, never the stub. Each package/service carries its own scoped `AGENTS.md` describing its
surface; agents read the nearest file in the tree, so the closest one wins. This file is the root
entry point — keep package-specific detail in the package's own `AGENTS.md`.

## Development

- Strict TDD, in three passes (binding, not a preference). For any new feature or issue: pass one
  writes tests only — fully describing the expected behavior — with no interface or implementation
  code, run and expect red. Pass two defines the interface(s) the code will satisfy — the `Protocol`
  types and signatures, per the interface-first architecture
  ([ADR 0006](docs/decisions/0006-interface-first-architecture.md)) — with no implementation logic.
  Pass three adds the implementation behind those interfaces until the tests pass (green). This
  applies to both unit and integration tests, per the `@pytest.mark.integration` marker in
  `pyproject.toml`.
- As much as possible, write parametrized tests against the protocol. Use the `rag_core` module as
  an example.
- Docstrings are mandatory on every module, class, and function repo-wide — including fixtures and
  pytest hooks in `conftest.py`. This is machine-enforced: ruff's pydocstyle presence rules
  (`D100`–`D107`) run in the same `ruff check` the CI gate uses, so a missing docstring fails the
  build. A test's docstring states what behavior it pins; a fixture's states what it provides. Keep
  them to one line unless the why is non-obvious.

## Environment

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

## Testing

- The CI plan is in `.github/workflows/ci.yaml`: a `checks` job (ruff lint, ruff format check, mypy,
  pytest against a pgvector service) and a `docs` job that builds the Sphinx site
  (`uv run sphinx-build -b html docs site -W`, build-only — deployment lives in `docs-deploy.yaml`).
- Run the whole suite with `uv run pytest`. Integration tests need the database — run
  `docker compose up -d` first or they fail to connect.
- Integration tests are marked `@pytest.mark.integration`. Scope a run with `uv run pytest -m unit`
  (fast, no DB) or `-m integration` (DB-backed); target one test with `uv run pytest -k "<name>"`.
  The `unit` marker is auto-applied to every non-integration test by the root `conftest.py`, so
  `-m unit` always selects the full fast suite — mark only integration tests explicitly.
- Integration tests run against a separate database (`TEST_DATABASE_URL`, e.g.
  `study_assistant_test`), never the app's `DATABASE_URL`, and truncate their tables between tests.
  `docker compose up -d` remains the only setup step — the test database is created automatically by
  `infra/postgres/init.sql` on first init, so a fresh clone needs nothing extra.
- Lint, format, and typecheck must also be green:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy`. Fix every error and type
  failure until the whole suite is green before you merge.
- Docs must build clean: `uv run sphinx-build -b html docs site -W` (CI runs this too — `-W` turns
  Sphinx warnings into errors, catching broken toctrees, anchors, and autodoc import failures).
- Tests come first, not alongside. Writing or updating tests for the code you change is mandatory
  (even if nobody asked), and under the three-pass rule above it happens in pass one — before the
  interface or implementation exists — not in the same pass as the code.
- Schema changes need a fresh DB: `initialize_schema()` is `CREATE ... IF NOT EXISTS` and will not
  retrofit constraints, so run `docker compose down -v && docker compose up -d` after editing
  `store/schema.py`.

## Style

- `ruff` formats and lints (line length 100, rule set `E,F,I,UP,B`); `mypy` runs in `strict` mode.
  Both must pass — do not silence them without cause.
- Type every function signature; `mypy --strict` rejects untyped defs. Prefer explicit, narrow types
  over `Any`.

## Decisions (ADRs)

The locked architectural decisions are recorded as ADRs, indexed in
[`docs/decisions/`](docs/decisions/). They are binding and the source of truth — read the relevant
ADR before changing what it governs, and do not restate its rules here.

## PRs

- Branch from `dev`, naming the branch with its GitHub issue number first (e.g. `4-embeddings` for
  issue #4) so the branch links back to its issue.
- PR title format: `[<phase or package>] <Title>` — e.g. `[rag_core/store] Add schema + CRUD`.
- Run the full gate green before handing off (with `docker compose up -d`):
  `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run sphinx-build -b html docs site -W`.
- Update the `README.md` Status blurb in the same change — current status lives there (and in the
  GitHub issues), not in this file.
- Never commit; only stage. Do not run `git commit`. At the end of a set of changes, `git add` the
  relevant files and leave them staged for the human to review — but only if 0 files are currently
  staged. If anything is already staged, do not stage at all; leave the working tree as-is.
