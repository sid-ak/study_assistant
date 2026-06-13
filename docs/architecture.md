# Study Assistant — Architecture & Structure

A personal study assistant over graduate course materials (lecture slides, papers, notes).
Answers questions with synthesis from Claude, grounded in retrieved sources, with citations
back to the exact source slide/page.

This document covers the architecture, the governance/context model, the directory layout, and the
project-wide conventions. The phased build plan lives in [`plan.md`](plan.md); the locked decisions
that shaped all of this are recorded as ADRs in [`decisions/`](decisions/).

---

## Architecture

![RAG pipeline architecture](./assets/architecture_svg.svg)

- **Orchestration:** LangGraph graph with tool use and human-in-the-loop checkpoints, backed by
  the Claude API for reasoning/synthesis.
- **RAG pipeline:** document ingestion → semantic chunking → embeddings into pgvector on
  PostgreSQL → hybrid retrieval + reranking (not naive top-k).
- **Tooling boundary:** a custom MCP server exposes retrieval + source documents to the agent,
  decoupling tooling from the model.
- **Backend:** FastAPI with streaming responses.
- **Frontend:** React (TypeScript), renders answers with citations to the exact source slide/page.
- **Ops:** containerized with Docker, CI via GitHub Actions.

The decisions that shaped this architecture — the RAG boundary, the local embedding/reranking
stack, the local single-user scope, and CLI batch ingestion — are recorded as ADRs in
[`decisions/`](decisions/).

---

## Governance / context architecture

Organizing idea: a **layered context model**. The root file stays small and stable (loaded every
turn); component detail lives in *nested* `CLAUDE.md` files pulled in only when working in that
subtree; the deep "why" lives in docs referenced on demand.

### Always-loaded (root, short & stable)
- **`CLAUDE.md`** — entry point. Project one-liner, architecture map, a summary of the key
  decisions (full ADRs in `docs/decisions/`), golden
  rules (e.g. *retrieval logic lives only in `rag_core`*; *never import `torch` at module
  top-level outside `embed/` and `rerank/`*; *Claude calls use `claude-opus-4-8`, streaming,
  adaptive thinking*), how to run/test, and pointers to everything else. A map, not an encyclopedia.
- **`AGENTS.md`** — tool-agnostic twin for non-Claude agents. Implemented as a **symlink to
  `CLAUDE.md`** (single source of truth, no drift).

### Nested (loaded only when working in that component)
- **`packages/rag_core/CLAUDE.md`** — chunking strategy, lazy-model-loading rule, pgvector schema
  conventions, the hybrid + rerank contract.
- **`cli/CLAUDE.md`** — CLI command surface, how it calls into `rag_core`, idempotency rules.
- **`services/mcp_server/CLAUDE.md`** — MCP tool surface, return shapes, citation/source-doc format.
- **`services/api/CLAUDE.md`** — LangGraph node/state conventions, HITL checkpoint placement, SSE
  streaming rules, the Postgres checkpointer.
- **`apps/web/CLAUDE.md`** — citation-rendering contract, SSE client conventions, TS/React style.

### Referenced on demand (not loaded every turn)
- **`docs/architecture.md`** (this document) — full data flow, the governance model, directory
  layout, and conventions; the home for deeper design notes (HITL checkpoint design, DB schema,
  the retrieval/RRF math, eval methodology) as they firm up.
- **`docs/decisions/` (ADRs)** — one short file per locked decision (*context → decision →
  consequences*). Durable record of *why*, survives chat-context summarization.
- **`docs/plan.md`** — the phased build plan.
- **`CONTRIBUTING.md`** — human dev workflow: `uv` setup, running tests, lint/format/typecheck,
  commit + branch conventions.
- **`README.md`** — short public-facing intro + quickstart.
- **`.env.example`** — documented contract for every required env var (DB URL, model names, rerank
  candidate count, Anthropic key).

Deliberately omitted (overkill for a personal single-user tool, easy to add later): `SECURITY.md`,
code of conduct, per-service `AGENTS.md` mirrors.

---

## Directory layout

A `uv`-workspace monorepo with `rag_core` as a path dependency shared by the other Python packages.
Frontend is its own npm app.

```
study_assistant/
├── CLAUDE.md                    # root context (always loaded)
├── AGENTS.md                    # symlink → CLAUDE.md
├── CONTRIBUTING.md
├── README.md
├── .env.example
├── pyproject.toml               # uv workspace root
├── uv.lock
├── docker-compose.yml
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── docs/
│   ├── architecture.md          # this document
│   ├── plan.md                  # phased build plan
│   └── decisions/               # ADRs (0001-rag-retrieval-boundary.md, …)
├── packages/
│   └── rag_core/                # THE shared library — all retrieval logic
│       ├── CLAUDE.md
│       ├── pyproject.toml
│       ├── src/rag_core/
│       │   ├── ingest/          # pptx/pdf/md parsing, semantic chunking
│       │   ├── embed/           # bge embedder (lazy torch load)
│       │   ├── rerank/          # bge cross-encoder reranker
│       │   ├── retrieve/        # dense + BM25 + RRF fusion
│       │   ├── store/           # pgvector access, schema, migrations
│       │   └── config.py
│       └── tests/
├── cli/                         # `study` ingestion CLI — depends on rag_core
│   ├── CLAUDE.md
│   ├── pyproject.toml
│   ├── src/study_cli/
│   │   └── main.py              # `study` console-script entry point
│   └── tests/
├── services/
│   ├── mcp_server/              # thin: wraps rag_core as MCP tools + source docs
│   │   ├── CLAUDE.md
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── src/ + tests/
│   └── api/                     # FastAPI + LangGraph + SSE streaming
│       ├── CLAUDE.md
│       ├── pyproject.toml
│       ├── Dockerfile
│       └── src/api/
│           ├── graph/           # LangGraph nodes, state, HITL checkpoints
│           ├── routes/          # /chat (SSE), /health, /resume
│           ├── mcp_client/      # connects to mcp_server
│           └── main.py
│       └── tests/
├── apps/
│   └── web/                     # React + TypeScript
│       ├── CLAUDE.md
│       ├── package.json
│       ├── Dockerfile
│       └── src/
│           ├── components/      # chat, citation rendering, HITL approval
│           └── api/             # SSE client
└── infra/
    └── postgres/                # pgvector init.sql, model-weights volume notes
```

Notes:
- **The `study` CLI is its own top-level package** (`cli/`), depending on `rag_core` as a workspace
  dependency. Keeps the ingestion entry point cleanly separated from the library.
- **Model weights** are cached in a named Docker volume, not baked into images — the multi-GB `bge`
  download happens once.

---

## Conventions (to be enforced via CLAUDE.md + tooling)
- **Models:** Claude via the Anthropic SDK, `claude-opus-4-8`, adaptive thinking, streaming.
- **Retrieval lives only in `rag_core`.** MCP server and API are consumers, never reimplementers.
- **Lazy model loading:** no `torch` import at module top-level outside `embed/` and `rerank/`.
- **Embedder/reranker behind a small interface** so the rest of the system is agnostic to the
  concrete model; the only real lock-in is the pgvector embedding dimension (`vector(N)`).
- **Python tooling:** `uv` workspace; lint/format/typecheck in pre-commit and CI.
