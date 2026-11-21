# MVP: Agentic RAG Study Assistant

Goal: take the study assistant from scaffolding to a small, runnable, measurable system. It answers questions through a bounded agent, cites its sources, and reports how well it performs.

Guiding rule: minimal drift. Every line of code lands where `docs/architecture.md` places it, follows the ADRs and the root `AGENTS.md` rules, and every new design idea is recorded in an ADR. Anything the architecture describes but the MVP does not build is unfinished work, listed under Next Steps, not a deviation. The one known drift is the corpus, recorded in [ADR 0009](decisions/0009-mvp-corpus.md).

The MVP is split into five work chunks. Each chunk ends in something that runs on its own, so the project is in a usable state after every chunk.

---

## Current State

The design is complete and the storage layer is built. Nothing yet ingests, searches, reasons, or measures.

### On `main` (Phase 0, Foundations)

- `uv` workspace with the shared `rag_core` library, currently a stub with a smoke test.
- Postgres 16 + pgvector dev stack via Docker Compose.
- CI on GitHub Actions: Ruff lint and format, mypy, pytest. Pre-commit hooks mirror it.
- Automated Claude code review on pull requests, and a docs site deployed from `main`.
- Architecture doc and ten ADRs (0000 to 0009) covering:
  - The stack.
  - The `rag_core` retrieval boundary.
  - Local embedding and reranking (`bge-m3`, `bge-reranker-v2-m3`).
  - CLI batch ingestion.
  - Interface-first design.
  - The generation backend.
  - Per-model embedding columns.
  - The MVP corpus.
- Layered `AGENTS.md` files that encode architectural rules per package.

### In PR #41 (Phase 1, open against `main`)

- Schema for `documents`, `chunks`, and an `embedding_models` registry.
- `EmbedderRegistry`, which implements ADR 0008: registering a model adds its own `vector(N)` column and HNSW index (cosine ops), and one model can be marked current.
- `Store` behind a `StoreProtocol` interface: idempotent document upsert by file hash, batch chunk insert via binary `COPY`, dimension validation, and typed errors.
- A generated `tsvector` column with a GIN index on `chunks`, so BM25-style lexical search needs no schema change.
- `rag_core_testing` package with in-memory fakes, plus unit and database-backed tests.

Phase 1 does not build:

- A schema migration mechanism. `Store.initialize()` creates tables and indexes only if they are absent, so a schema change needs a fresh database.
- Re-embedding between models, the migration tail of ADR 0008. `packages/rag_core/AGENTS.md` records this gap.

### Not built yet

- Document parsing and chunking.
- A real embedding model wired into the pipeline.
- Any search query: vector, lexical, or hybrid. `Store` can write and read chunks by document but cannot rank them against a query.
- The `study` CLI, MCP server, LangGraph agent, FastAPI backend, and React frontend.
- The golden-set eval harness described in the architecture doc.

### Known pre-existing drift

- README.md and the root AGENTS.md say generation calls the Anthropic API. ADR 0007 replaced that with a vendor-neutral, OpenAI-compatible adapter defaulting to a local model. The fix is a prerequisite, below.

### Prerequisites for Chunk 1

1. Merge PR #41 (Phase 1). Every chunk below builds on that storage layer instead of rebuilding it.
2. Update README.md and the root AGENTS.md to match ADR 0007.

---

## Working Rules

These come from the root `AGENTS.md` and apply to every chunk.

- Strict three-pass TDD: tests first (red), then `Protocol` interfaces, then implementation (green).
- Every swappable component sits behind a `Protocol` with an in-memory fake (ADR 0006). Fakes for `rag_core` protocols live in `rag_core_testing`.
- Docstrings everywhere, `mypy --strict`, Ruff, and a warning-free Sphinx build must all pass.
- No `torch` import at module top level outside `rag_core/embed/` and `rag_core/rerank/` (ADR 0002).
- Each new workspace member gets its own scoped `AGENTS.md`.
- Update the README Status blurb with each merged change.

---

## Corpus

A markdown-only, release-engineering corpus:

- Build-system documentation (CMake, Bazel).
- Release notes.
- CI failure write-ups, each recording a failing log excerpt, its cause, and its fix.

This is the one drift from the architecture, recorded in [ADR 0009](decisions/0009-mvp-corpus.md). The architecture defines the corpus as course materials (lecture slides, papers, and notes in pptx, pdf, and md), with citations back to the exact slide or page. The MVP indexes release-engineering documentation instead, with citations at the level of a markdown section.

- Unaffected: the pipeline itself. No code is specific to either domain, and markdown is already a supported format, so no new parser is needed.
- Different: the content the assistant answers questions about, and citation granularity (section heading rather than slide or page).
- Reconciliation: ingest course materials with `study ingest` once the pptx and pdf parsers land (see Next Steps). No other code changes are required.

---

## Tracking

The MVP is Phase 1.5, tracked in [#45](https://github.com/sid-ak/study_assistant/issues/45) under the `Phase 1.5 — MVP` milestone. Each chunk is a sub-issue:

| Chunk | Issue | Overlaps |
| --- | --- | --- |
| 1. Ingestion and HNSW retrieval | [#46](https://github.com/sid-ak/study_assistant/issues/46) | Phase 2 (#3), dense half of Phase 3 (#4) |
| 2. Evaluation harness | [#47](https://github.com/sid-ak/study_assistant/issues/47) | Eval harness in Phase 3 (#4) |
| 3. Bounded agent over MCP | [#48](https://github.com/sid-ak/study_assistant/issues/48) | Phase 5 (#6), graph part of Phase 6 (#7), per-turn cap in #11 |
| 4. Reranking | [#49](https://github.com/sid-ak/study_assistant/issues/49) | Reranking half of Phase 4 (#5) |
| 5. Code freeze and walkthrough | [#50](https://github.com/sid-ak/study_assistant/issues/50) | None |

Existing issues that this plan affects:

- #16 asks to isolate Anthropic SDK calls in one generation module. ADR 0007 removed the Anthropic SDK, and `services/api/src/api/generate/` in Chunk 3 is that one module, so #16 is closed or retitled when Chunk 3 lands.
- #15 asks to record the embedder model and dimension and stub the re-embed migration. PR #41 delivers the first part. The re-embed migration remains, listed under Next Steps.

---

## Chunk 1: Ingestion and HNSW Retrieval

### Outcome

Markdown documents go in through the `study ingest` command, get chunked and embedded with `bge-m3` into its own per-model column (ADR 0008), and can be retrieved top-K by cosine similarity through the pgvector HNSW index.

### Tasks

- `rag_core/ingest/`: markdown parser and the first stage of the semantic chunker, heading-aware splitting. Every chunk keeps its source document and section heading in `metadata`.
- `rag_core/embed/`: an `Embedder` Protocol, a `bge-m3` implementation with lazy model loading, and a fake in `rag_core_testing`.
- `rag_core/store/`: add a query method to `StoreProtocol` that ranks chunks against a query vector. The store owns the SQL. Implement it in the pgvector `Store` and the in-memory fake, with tests parametrized against the Protocol.
- `rag_core/retrieve/`: a dense retrieval function that embeds the query and calls the store's query method. It is the retrieval entry point for every caller. The CLI, the eval harness, and the MCP server never call the store's query method directly, so hybrid retrieval later grows here without changing those callers.
- `cli/`: a new workspace package exposing the `study` console script with `study ingest <folder>`, a thin entry point over `rag_core`. Include its `AGENTS.md`.
- Register `bge-m3` (dimension 1024) and mark it current on first ingest.
- A query path, through `rag_core/retrieve/`, that prints chunk IDs, cosine distances, and latency in milliseconds.
- Retrieval experiments vary `ef_search` only. `m` and `ef_construction` stay at pgvector's defaults, since the registry builds each HNSW index without build parameters. No recall or latency target exists to tune them against until Chunk 2 provides one.

### Completion Criteria

`study ingest <folder>` loads the corpus idempotently, and a query returns ranked chunks with distances and latency.

### Project Value

This is the foundation every later chunk depends on, built in the modules the architecture assigns, so nothing has to be moved later.

### Learning Value

- How HNSW trades recall for latency through `ef_search`, and why `m` is a build-time choice.
- Why per-model embedding columns make embedder swaps additive instead of destructive.
- Where pure vector search fails on exact symbols, flags, and error codes, which motivates the hybrid design.

---

## Chunk 2: Evaluation Harness

### Outcome

A golden-set eval harness (ADR 0002) that measures retrieval quality and latency against the dense retrieval built in Chunk 1. It becomes the baseline every later chunk is measured against.

### Tasks

- `evals/`: a new workspace member, placed as in `docs/architecture.md`, depending on `rag_core`. Include its `AGENTS.md`.
- Write 10 golden questions in `evals/golden/`. Label each expected answer by source document and section heading, not chunk ID, so labels survive re-chunking.
- A pytest or CLI runner that calls `rag_core/retrieve/` and reports Recall@5 and p50 and p95 latency. Results are written to `evals/results/` so runs can be compared.
- Record the dense-only baseline run.

### Completion Criteria

One command runs the eval suite against the ingested corpus, and the dense-only baseline is saved in `evals/results/`.

### Project Value

Every later change can be measured from here on, starting with the agent and the reranker.

### Learning Value

- Building golden sets that survive refactors.
- Reading retrieval quality as recall at a fixed K, and latency as p95 rather than averages.

---

## Chunk 3: Bounded Agent over MCP

### Outcome

A LangGraph agent that reaches retrieval only through the MCP server (ADR 0001), generates through a vendor-neutral `Generator` (ADR 0007), loops at most twice, and returns structured, cited answers.

### Tasks

- `services/mcp_server/`: a minimal MCP server exposing one `search` tool that calls `rag_core/retrieve/`. It is a consumer of `rag_core`, never a reimplementer. Include its `AGENTS.md`.
- `services/api/src/api/generate/`: the `Generator` Protocol with one OpenAI-compatible adapter, pointed at a local runtime (Ollama) by default. The model is chosen in config. Its fake lives in `services/api/tests/`, since `rag_core_testing` holds fakes for `rag_core` protocols only.
- `services/api/src/api/mcp_client/`: the client the graph uses to call the MCP server.
- `services/api/src/api/graph/`: the state machine `retrieve -> grade_relevance -> generate`, or `rewrite_query -> retrieve`. No FastAPI routes yet. Include the `services/api` `AGENTS.md`.
- Max-2-hop guardrail. After the limit, return the best grounded answer or an explicit "insufficient context" result.
- Structured output: the answer plus the list of cited chunk IDs.
- Extend the Chunk 2 harness with a citation-grounding pass rate: every cited ID must exist in the retrieved context.
- Write ADR 0010 recording the bounded corrective loop, the hop limit, and cited structured output.

### Completion Criteria

A question about the corpus produces a cited answer in at most two hops, entirely through the MCP tool, an unanswerable question ends cleanly, and the harness reports the citation-grounding pass rate.

### Project Value

The generation lane exists in its intended shape: decoupled retrieval, a swappable model, and predictable, bounded behavior.

### Learning Value

- Designing agents as explicit, bounded state machines instead of open-ended loops.
- How MCP separates tool implementation from agent logic.
- How open-weight models differ in tool calling and structured output reliability.
- Separating retrieval quality from generation quality.

---

## Chunk 4: Reranking

### Outcome

A cross-encoder reranker (ADR 0002) whose effect is measured by the Chunk 2 harness.

### Tasks

- `rag_core/rerank/`: a `Reranker` Protocol, a `bge-reranker-v2-m3` implementation with lazy loading and a configurable candidate count, and a fake in `rag_core_testing`.
- Wire the reranker into `rag_core/retrieve/` behind a setting, so retrieval can run with or without it.
- Run the evals with and without reranking and record both results in `evals/results/`.

### Completion Criteria

The saved results show the before/after effect of reranking on Recall@5, latency, and citation grounding.

### Project Value

The reranker, the design's highest-leverage quality lever, is in place with measured evidence for it.

### Learning Value

- The latency cost of cross-encoder reranking versus its quality gain, read from p95 rather than averages.

---

## Chunk 5: Code Freeze and Walkthrough

### Outcome

A clean, runnable repository that matches its own documentation, and a walkthrough of the system.

### Tasks

- Stop feature work.
- Run the full gate: Ruff, mypy, pytest (unit and integration), and the Sphinx build.
- Confirm a fresh clone can run ingestion, a query, the agent, and the evals by following the README.
- Update the README Status blurb, setup steps, and latest eval results.
- Check the code against the architecture directory layout and ADRs 0000 to 0010.
- Prepare the walkthrough: ingestion and retrieval, the eval baseline, the bounded agent over MCP, then the reranking results.

### Completion Criteria

The repo runs from a clean checkout, the docs match the code, and the walkthrough covers each chunk's results.

### Project Value

Another person can run and review the project by following the README.

### Learning Value

- Explaining design tradeoffs concisely: decoupled retrieval, bounded agents, per-model columns, and measured reranking.
- Presenting recommendations backed by measured results.

---

## Scope Valves

If time runs short, cut in this order. Each cut becomes a Next Steps item, not drift.

1. Golden set from 10 questions to 6.
2. The reranker in Chunk 4. The harness stays, and reranking moves to Next Steps.
3. Latency percentiles. Recall@5 and citation grounding stay.

Two parts are never cut:

- The eval harness in Chunk 2. Every later chunk is measured against it.
- The MCP path in Chunk 3. A direct `rag_core` import from the graph would contradict ADR 0001.

---

## Next Steps

Work the architecture describes that the MVP does not build. None of it is drift: it is unfinished work in the planned order. If a scope valve was used, the cut item is added back here.

### Retrieval Lane (`rag_core`)

- Hybrid retrieval in `rag_core/retrieve/`: BM25 over the existing `tsvector` column, fused with dense results via RRF. Rerun the golden set to measure dense-only versus hybrid.
- Semantic chunking, second stage: the embedding-similarity boundary pass on top of the heading-aware splitter built in Chunk 1.
- pptx and pdf parsers in `rag_core/ingest/`, with slide- and page-level citation metadata. This also resolves the corpus drift.
- Embedder migration: re-embed existing chunks into a new model's column, validate with the golden set, flip the current marker, and drop the old column (ADR 0008). `packages/rag_core/AGENTS.md` records this as not built, tracked in #15.
- HNSW build parameters: expose `m` and `ef_construction` as registry options if build-time tuning becomes worthwhile.

### Ingestion

- Ingest the course-materials corpus once the pptx and pdf parsers land.
- Chunk-level idempotency on re-ingest. Documents are already idempotent by file hash.
- The light UI upload path ADR 0004 defers, reusing the same `rag_core` pipeline.

### Generation Lane

- FastAPI backend in `services/api/`: `/chat` with SSE streaming, `/health`, and `/resume`.
- HITL checkpoints in the graph, persisted with a Postgres-backed LangGraph checkpointer.
- Model selection: re-check the ADR 0007 candidate list against the current landscape and choose a default based on tool-calling eval results.

### Frontend

- React + TypeScript app under `apps/web/`: chat view, streaming client over `fetch` and `ReadableStream`, citation rendering back to source, and the HITL approval UI.

### Evaluation

- Generation-quality evals beyond citation grounding (answer correctness and faithfulness), extending the golden-set discipline as ADR 0007 describes.
- A golden set over the course-materials corpus, replacing or extending the MVP's set.

### Packaging and Docs

- Dockerfiles for `services/mcp_server`, `services/api`, and `apps/web`, with model weights cached in a named volume rather than baked into images.
- Keep the README Status blurb current as each phase lands.
