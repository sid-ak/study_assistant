# Study Assistant — Build Plan

The phased build plan for the study assistant. Each phase is independently testable.

For the architecture, governance/context model, directory layout, and conventions, see
[`architecture.md`](architecture.md); for the decisions that shaped them, see
[`decisions/`](decisions/).

---

## Phased build plan (each phase independently testable)

Bottom-up. Containerization grows incrementally — each service adds its own Dockerfile + compose
entry as it appears — so there is no big-bang infra phase.

### Phase 0 — Foundations
Repo skeleton, governance files, `uv` workspace, `docker-compose.yml` with Postgres+pgvector,
`.env.example`, pre-commit, CI skeleton (lint + empty test run).
**Test:** `docker compose up` gives a Postgres with the `vector` extension live; `pre-commit run
--all` and CI both green.

### Phase 1 — Storage + schema (`rag_core/store`)
pgvector schema (`documents`, `chunks`, `embeddings`, with the `user_id` seam), migrations, CRUD.
**Test:** integration tests against the compose DB — insert/query chunks, vector column round-trips.

### Phase 2 — Ingestion + CLI (`rag_core/ingest` + `cli/`)
pptx/pdf/md parsers, semantic chunker, and the separate `study ingest ./fixtures/` CLI writing
chunks (text + source metadata: file, slide/page) — *no models yet*, embeddings deferred.
**Test:** unit tests on the chunker with sample docs; run the CLI on fixtures, assert chunk rows
with correct slide/page provenance.

### Phase 3 — Embeddings + dense retrieval (`rag_core/embed`)
`bge` embedder with lazy load, embedding backfill at ingest, HNSW index, dense top-k search. Plus a
small **golden-set eval harness** (labeled query → expected-doc) — the eval loop starts here.
**Test:** ingest fixtures, run semantic queries, assert relevant chunk outranks irrelevant; eval
harness reports recall@k.

### Phase 4 — Hybrid retrieval + reranking (`rag_core/retrieve` + `rerank`)
Postgres `tsvector` BM25 sparse search, RRF fusion, `bge` cross-encoder rerank with configurable
candidate count.
**Test:** the same eval harness shows rerank improves MRR/recall@k over dense-only — a concrete,
measurable win.

### Phase 5 — MCP server
Wrap `rag_core` retrieval + source-doc fetch as MCP tools (typed schemas, citations in the payload).
**Test:** an MCP client test calls the tools and gets back ranked chunks + exact citations; contract
tests on the tool schemas.

### Phase 6 — FastAPI + LangGraph + streaming
Graph: query → retrieve (via MCP) → synthesize with Claude (`claude-opus-4-8`, adaptive thinking,
streaming) → stream out over SSE. Postgres checkpointer for graph state.
**Test:** `POST /chat` returns a streamed answer that cites real chunks; graph unit tests with
Claude mocked; checkpointer persists/reloads state.

### Phase 7 — Human-in-the-loop checkpoints
LangGraph `interrupt` points (e.g. *approve retrieved sources before synthesis*), exposed and
resumable through the API.
**Test:** graph pauses at the checkpoint, API surfaces the pending interrupt, `/resume` continues;
interrupt → resume cycle covered by tests.

### Phase 8 — React frontend
Chat UI, SSE consumption, answers rendered with **clickable citations back to the exact slide/page**,
and the HITL approval UI.
**Test:** component tests for citation rendering; a Playwright e2e — ask a question, watch it stream,
click a citation, land on the source.

### Phase 9 — CI/CD hardening + full-stack e2e
Tighten CI (lint + typecheck + unit + integration + image builds), full `docker compose up` stack,
end-to-end smoke test across the whole pipeline.
**Test:** the full stack runs from one `compose up`; CI matrix green including image builds.
