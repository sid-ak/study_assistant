# Dev Cheatsheet

## Start the DB

```bash
docker compose up -d
```

## Stop / reset DB (after schema changes)

```bash
docker compose down -v && docker compose up -d
```

## Install deps

```bash
uv sync
```

## Tests

```bash
uv run pytest                        # everything
uv run pytest -m "not integration"   # fast, no DB
uv run pytest -m integration         # DB-backed
uv run pytest -k "<test_name>"       # one test
```

## Lint / format / typecheck

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## Docs preview (clean rebuild + serve)

```bash
rm -rf site && uv run sphinx-build -E -a -b html docs site -W
uv run python -m http.server -d site 8000
```

## Full pre-PR gate

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run sphinx-build -b html docs site -W
```

## DB connection

| Field    | Value           |
| -------- | --------------- |
| Type     | PostgreSQL      |
| Host     | localhost       |
| Port     | 5432            |
| Database | study_assistant |
| User     | study           |
| Password | change-me       |

URL: `postgresql://study:change-me@localhost:5432/study_assistant`
