# Project

> Part of [AI, RAG & Python](../README.md)

One page per stage of [study_assistant](https://github.com/sid-ak/study_assistant), in the order the
stages were built. Each page covers:

- What the stage built and where it sits in the pipeline.
- The Python it used, with short excerpts of the repository's code.
- The design trade-offs, each tied to the decision record that settled it and the alternative it
  rejected.
- Measured results, where the stage produced any.
- Likely interview questions about the stage, each with a concise answer.

The general theory behind each stage is in the [Concepts](../concepts/README.md) section.

---

## Pages

| Page | What it covers |
| ---- | -------------- |
| [Storage and Schema](00-storage-and-schema.md) | pgvector, HNSW limits, per-model embedding columns, the embedder registry, `Protocol` interfaces with in-memory fakes, and contract tests |
| [Ingestion and HNSW Retrieval](01-ingestion-and-hnsw-retrieval.md) | Heading-aware chunking, a lazily loaded fastembed embedder, dense search with `ef_search`, idempotent ingestion, the `study` CLI, and measured latency and recall |
| [Evaluation Harness](02-evaluation-harness.md) | A golden set labeled by section, Recall@5, MRR, and latency percentiles, saved runs, re-embedding for a second model, and the embedder comparison |
| [Bounded Agent over MCP](03-bounded-agent-over-mcp.md) | An MCP search server, a rate-limit-aware generator, a two-hop LangGraph state machine with score-based grading, cited structured output, and the grounding eval |
| [Reranking](04-reranking.md) | A fastembed cross-encoder behind a protocol, search and rerank as separate steps, grading the agent on reranker scores, and the measured recall, MRR, and latency trade-off |
| [Hybrid Retrieval](05-hybrid-retrieval.md) | Postgres full-text search with an OR query, Reciprocal Rank Fusion between search and rerank, and why it measured no gain on a small corpus |
| [Human-in-the-Loop Checkpoint](06-human-in-the-loop-checkpoint.md) | A LangGraph interrupt between grading and generation, paused runs saved in Postgres, resuming by thread id from another process, and the refusals that keep it honest |
| [Code Freeze and Walkthrough](07-code-freeze-and-walkthrough.md) | What a fresh clone and a record audit caught, every measurement in one place, and how to present the project |
