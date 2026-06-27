# 2. Embedding and reranking stack: local open-source models

- Status: Accepted
- Date: 2026-06-13

## Context

Claude has no embeddings endpoint, so the retrieval stack is an independent vendor/tech choice with
two distinct stages:

- Embedding — turns each chunk and each query into a vector stored in pgvector; powers the dense
  half of hybrid search.
- Reranking — a slower cross-encoder that re-scores a candidate set (e.g. top-50) and reorders
  it to the final top-k. It reads query and document together, catching relevance that bi-encoder
  embeddings miss. This is the "not naive top-k" requirement and the single highest-leverage quality
  lever in the pipeline.

Three stacks were considered:

1. Voyage AI (`voyage-3` + `rerank-2.5`) — Anthropic's recommended pairing. Best quality with
   least tuning, trivial infra, but hosted: requires an API key, network access, and chunks transit
   to a vendor.
2. Local open-source (BGE embeddings + a BGE cross-encoder reranker) — runs in-process. No
   per-call cost, fully offline and private, but heavier containers and slower CPU reranking, and
   the eval/model-selection work is owned in-house.
3. OpenAI + Cohere — solid hosted option, but spans three vendors and three keys to do what
   Voyage does in one.

At this project's scale (a personal course corpus, ~10K–50K chunks) cost is negligible for every
option and all three clear the quality bar for course Q&A. The deciding axis is therefore
offline/privacy and learning value vs. operational simplicity, not cost or quality.

## Decision

Adopt the local open-source stack: `bge-m3` for embeddings and `bge-reranker-v2-m3`
(cross-encoder) for reranking, both running in-process within `rag_core`.

This is driven by the explicit goals of no per-call cost, keeping everything on-machine, and
learning the RAG stack end-to-end (model loading, the eval loop, CPU/MPS performance).

## Consequences

- No per-call cost, fully on-machine, private, and works offline.
- Container weight: only the component that loads the `bge` models carries PyTorch + weights (a
  multi-GB image). Model loading is isolated to the `embed/` and `rerank/` modules — no `torch`
  import at module top-level elsewhere — and weights are cached in a named Docker volume rather than
  baked into images, so the download happens once.
- Reranking is the slow step on CPU: a cross-encoder scoring ~50 candidates per query is the
  cost of "not naive top-k." It uses MPS on macOS and CPU in Linux containers/CI. The rerank
  candidate count is configurable to trade latency for quality, and model loads stay out of the
  request path.
- We own the eval loop — a golden-set harness (labeled query → expected-doc) introduced in the
  embeddings phase — to validate retrieval quality and demonstrate that reranking improves it.
- The embedding model's output dimension is baked into the pgvector `vector(N)` column and its
  index. Changing embedders later means a re-embed plus a schema migration; this is the main lock-in
  and the reason the choice is fixed early.
- Query and document vectors must come from the same model, so the embedder is pinned in config,
  not chosen per call.
