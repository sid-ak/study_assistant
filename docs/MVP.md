# MVP: Agentic RAG Study Assistant

Goal: take the study assistant from scaffolding to a small, runnable, measurable system. It should answer questions through a bounded agent, cite its sources, and report how well it performs.

Guiding rule: minimal drift. Every line of code lands where `docs/architecture.md` places it, follows the ADRs and the root `AGENTS.md` rules, and every new design idea is recorded in an ADR. Anything the architecture describes but the MVP does not build is unfinished work, listed under Next Steps, not a deviation. The one known drift is the corpus, described below.

The MVP is split into four work chunks. Each chunk ends in something that runs on its own, so the project is in a usable state after every chunk.

---

## Where the Project Stands

The design is complete and the storage layer is built. Nothing yet ingests, searches, reasons, or measures.

**On `main` and `dev` (Phase 0, Foundations)**
- `uv` workspace with the shared `rag_core` library (currently a stub with a smoke test).
- Postgres 16 + pgvector dev stack via Docker Compose.
- CI on GitHub Actions: Ruff lint and format, mypy, pytest. Pre-commit hooks mirror it.
- Automated Claude code review on pull requests, and a docs site deployed from `main`.
- Architecture doc and nine ADRs (0000 to 0008) covering the stack, the `rag_core` retrieval boundary, local embedding and reranking (`bge-m3`, `bge-reranker-v2-m3`), CLI batch ingestion, interface-first design, the generation backend, and per-model embedding columns.
- Layered `AGENTS.md` files that encode architectural rules per package.

**On branch `2-phase-1-storage-and-schema` (Phase 1, not yet merged)**
- Schema for `documents`, `chunks`, and an `embedding_models` registry.
- `EmbedderRegistry` that implements ADR 0008: registering a model adds its own `vector(N)` column and HNSW index (cosine ops), and one model can be marked current.
- `Store` behind a `StoreProtocol` interface: idempotent document upsert by file hash, batch chunk insert via binary `COPY`, dimension validation, and typed errors.
- A generated `tsvector` column with a GIN index already exists on `chunks`, so BM25-style lexical search needs no schema change.
- `rag_core_testing` package with in-memory fakes, plus unit and database-backed tests.

**Not built yet**
- Document parsing and chunking.
- A real embedding model wired into the pipeline.
- Any search query: vector, lexical, or hybrid. `Store` can write and read chunks by document but cannot rank them against a query.
- The `study` CLI, MCP server, LangGraph agent, FastAPI backend, and React frontend.
- The golden-set eval harness described in the architecture doc.

**Known pre-existing drift**
- README.md and the root AGENTS.md say generation calls the Anthropic API. ADR 0007 replaced that with a vendor-neutral, OpenAI-compatible adapter defaulting to a local model. Chunk 2 fixes the docs.

**Before Chunk 1**
Merge the Phase 1 branch. Every chunk below builds on that storage layer instead of rebuilding it.

---

## Working Rules for Every Chunk

These come from the root `AGENTS.md` and apply throughout.

- Strict three-pass TDD: tests first (red), then `Protocol` interfaces, then implementation (green).
- Every swappable component sits behind a `Protocol` with an in-memory fake in `rag_core_testing` (ADR 0006).
- Docstrings everywhere, `mypy --strict`, Ruff, and a warning-free Sphinx build must all pass.
- No `torch` import at module top level outside `rag_core/embed/` and `rag_core/rerank/` (ADR 0002).
- Each new workspace member gets its own scoped `AGENTS.md`.
- Update the README Status blurb with each merged change.

---

## Corpus

A markdown-only, release-engineering corpus: build-system documentation (CMake/Bazel), release notes, and CI failure write-ups that each capture a failing log excerpt, its cause, and its fix.

> **DRIFT**
> The architecture defines the corpus as course materials (lecture slides, papers, notes in pptx, pdf, and md), with citations back to the exact slide or page. The MVP instead indexes release-engineering documentation, with citations at the level of a markdown section.
>
> - **What is unaffected:** the pipeline itself. No code is specific to either domain, and markdown is already a supported format, so no new parser is needed.
> - **What differs:** the content the assistant answers questions about, and citation granularity (section heading rather than slide or page).
> - **To reconcile:** ingest course materials with `study ingest` once the pptx and pdf parsers land (see Next Steps). No other code changes are required.

---

## Chunk 1: Ingestion and HNSW Retrieval

**What it achieves**
Markdown documents go in through the `study ingest` command, get chunked and embedded with `bge-m3` into its own per-model column (ADR 0008), and can be retrieved top-K by cosine similarity through the pgvector HNSW index.

**Tasks**
- `rag_core/ingest/`: markdown parser and the first stage of the semantic chunker, heading-aware splitting. Every chunk keeps its source document and section heading in `metadata`.
- `rag_core/embed/`: an `Embedder` Protocol, a `bge-m3` implementation with lazy model loading, and a fake in `rag_core_testing`.
- `rag_core/store/`: add a query method to `StoreProtocol` that ranks chunks against a query vector. Implement it in the pgvector `Store` and the in-memory fake, with tests parametrized against the Protocol.
- `cli/`: a new workspace package exposing the `study` console script with `study ingest <folder>`, a thin entry point over `rag_core`. Include its `AGENTS.md`.
- Register `bge-m3` (dimension 1024) and mark it current on first ingest.
- A query path that prints chunk IDs, cosine distances, and latency in milliseconds.
- Retrieval experiments vary `ef_search` only. `m` and `ef_construction` stay at the registry defaults.

**Done when**
`study ingest <folder>` loads the corpus idempotently, and a query returns ranked chunks with distances and latency.

**Value to the project**
This is the foundation every later chunk depends on, built in the modules the architecture assigns, so nothing has to be moved later.

**Learning value**
- How HNSW trades recall for latency through `ef_search`, and why `m` is a build-time choice.
- Why per-model embedding columns make embedder swaps additive instead of destructive.
- Where pure vector search fails on exact symbols, flags, and error codes, which motivates the hybrid design.

---

## Chunk 2: Bounded Agent over MCP

**What it achieves**
A LangGraph agent that reaches retrieval only through the MCP server (ADR 0001), generates through a vendor-neutral `Generator` (ADR 0007), loops at most twice, and returns structured, cited answers.

**Tasks**
- `services/mcp_server/`: a minimal MCP server exposing one `search` tool that calls `rag_core`. It is a consumer of `rag_core`, never a reimplementer. Include its `AGENTS.md`.
- `Generator` Protocol with one OpenAI-compatible adapter, pointed at a local runtime (Ollama) by default. The model is chosen in config. Add a fake for tests.
- `services/api/src/api/mcp_client/`: the client the graph uses to call the MCP server.
- `services/api/src/api/graph/`: the state machine `retrieve -> grade_relevance -> generate`, or `rewrite_query -> retrieve`. No FastAPI routes yet. Include the `services/api` `AGENTS.md`.
- Max-2-hop guardrail. After the limit, return the best grounded answer or an explicit "insufficient context" result.
- Structured output: the answer plus the list of cited chunk IDs.
- Write ADR 0009 recording the bounded corrective loop, the hop limit, and cited structured output.
- Fix README.md and the root AGENTS.md to match ADR 0007.

**Done when**
A question about the corpus produces a cited answer in at most two hops, entirely through the MCP tool, and an unanswerable question ends cleanly.

**Value to the project**
The generation lane exists in its intended shape: decoupled retrieval, a swappable model, and predictable, bounded behavior.

**Learning value**
- Designing agents as explicit, bounded state machines instead of open-ended loops.
- How MCP separates tool implementation from agent logic.
- How open-weight models differ in tool calling and structured output reliability.

---

## Chunk 3: Evaluation Harness and Reranking

**What it achieves**
A golden-set eval harness (ADR 0002) that measures retrieval and generation, and a cross-encoder reranker whose effect is proven by the numbers.

**Tasks**
- Add `evals/` to the directory layout in `docs/architecture.md`, then create it.
- Write 10 golden questions. Label each expected answer by source document and section heading, not chunk ID, so labels survive re-chunking.
- A pytest or CLI runner that reports Recall@5, p50 and p95 latency, and the citation-grounding pass rate (every cited ID must exist in the retrieved context). Results are written to a file so runs can be compared.
- `rag_core/rerank/`: a `Reranker` Protocol, a `bge-reranker-v2-m3` implementation with lazy loading and a configurable candidate count, and a fake.
- Run the evals with and without reranking and record both results.

**Done when**
One command runs the full eval suite, and the saved results show the before/after effect of reranking.

**Value to the project**
Every later change can be measured. The reranker, the design's highest-leverage quality lever, is in place with evidence for it.

**Learning value**
- Separating retrieval quality from generation quality.
- Building golden sets that survive refactors.
- The latency cost of cross-encoder reranking versus its quality gain, read from p95 rather than averages.

---

## Chunk 4: Code Freeze and Walkthrough

**What it achieves**
A clean, runnable repository that matches its own documentation, and a short, sharp explanation of the system.

**Tasks**
- Stop feature work.
- Run the full gate: Ruff, mypy, pytest (unit and integration), and the Sphinx build.
- Confirm a fresh clone can run ingestion, a query, the agent, and the evals by following the README.
- Update the README Status blurb, setup steps, and latest eval results.
- Check the code against the architecture directory layout and ADRs 0000 to 0009 one last time.
- Prepare a short walkthrough: ingestion and retrieval, the bounded agent over MCP, then the eval and reranking results.

**Done when**
The repo runs from a clean checkout, the docs match the code, and the walkthrough can be delivered without notes.

**Value to the project**
The project becomes something another person can run, review, and trust.

**Learning value**
- Explaining design tradeoffs concisely: decoupled retrieval, bounded agents, per-model columns, and measured reranking.
- Practicing the habit of presenting recommendations from measured results.

---

## Scope Valves

If time runs short, cut in this order. Each cut becomes a Next Steps item, not drift.

1. Golden set from 10 questions to 6.
2. The reranker in Chunk 3. Keep the harness; reranking moves to Next Steps.
3. Latency percentiles. Keep Recall@5 and citation grounding.

Never cut the MCP path in Chunk 2. A direct `rag_core` import from the graph would contradict ADR 0001.

---

## Next Steps

Work the architecture describes that the MVP does not build. None of it is drift; it is unfinished work in the planned order. If a scope valve was used, add the cut item back here.

### Retrieval Lane (`rag_core`)
- **Hybrid retrieval** in `rag_core/retrieve/`: BM25 over the existing `tsvector` column, fused with dense results via RRF. Rerun the golden set to measure dense-only versus hybrid.
- **Semantic chunking, second stage**: add the embedding-similarity boundary pass on top of the heading-aware splitter built in Chunk 1.
- **pptx and pdf parsers** in `rag_core/ingest/`, with slide- and page-level citation metadata. This also resolves the corpus drift.
- **Embedder migration**: re-embed existing chunks into a new model's column, validate with the golden set, flip the current marker, and drop the old column (ADR 0008). `schema.py` notes this is not implemented.
- **HNSW build parameters**: expose `m` and `ef_construction` as registry options if build-time tuning becomes worthwhile.

### Ingestion
- Ingest the course-materials corpus once the pptx and pdf parsers land.
- Chunk-level idempotency on re-ingest. Documents are already idempotent by file hash.
- The light UI upload path ADR 0004 defers, reusing the same `rag_core` pipeline.

### Generation Lane
- **FastAPI backend** in `services/api/`: `/chat` with SSE streaming, `/health`, and `/resume`.
- **HITL checkpoints** in the graph, persisted with a Postgres-backed LangGraph checkpointer.
- **Model selection**: re-check the ADR 0007 candidate list against the current landscape and choose a default based on tool-calling eval results.

### Frontend
- React + TypeScript app under `apps/web/`: chat view, streaming client over `fetch` and `ReadableStream`, citation rendering back to source, and the HITL approval UI.

### Evaluation
- Generation-quality evals beyond citation grounding (answer correctness and faithfulness), extending the golden-set discipline as ADR 0007 describes.
- A golden set over the course-materials corpus, replacing or extending the MVP's set.

### Packaging and Docs
- Dockerfiles for `services/mcp_server`, `services/api`, and `apps/web`, with model weights cached in a named volume rather than baked into images.
- Keep the README Status blurb current as each phase lands.
