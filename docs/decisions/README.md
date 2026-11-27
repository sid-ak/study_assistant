# Architecture Decision Records

Short records of the significant decisions on this project, in
[Nygard ADR](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) format:
_context → decision → consequences_. They are the durable record of _why_ the project is shaped the
way it is. The architecture and structure live in [`../architecture.md`](../architecture.md); the
phased build plan is tracked as
[GitHub issues](https://github.com/sid-ak/study_assistant/issues?q=is%3Aissue%20label%3Aphase).

| ADR                                           | Decision                                                    | Status   |
| --------------------------------------------- | ----------------------------------------------------------- | -------- |
| [0000](0000-stack.md)                         | Stack: Python, FastAPI, PostgreSQL, React                   | Accepted |
| [0001](0001-rag-retrieval-boundary.md)        | RAG retrieval boundary: a shared `rag_core` library         | Accepted |
| [0002](0002-local-embedding-and-reranking.md) | Embedding and reranking stack: local open-source models     | Accepted, models partly superseded by [0010](0010-lightweight-embedding-and-reranking-models.md) |
| [0003](0003-local-single-user-scope.md)       | Deployment scope: local single-user                         | Accepted |
| [0004](0004-cli-batch-ingestion.md)           | Document ingestion: CLI batch                               | Accepted |
| [0005](0005-documentation-tooling.md)         | Documentation site tooling: Sphinx, MyST, and Furo          | Accepted |
| [0006](0006-interface-first-architecture.md)  | Interface-first architecture: `Protocol`s + implementations | Accepted |
| [0007](0007-generation-backend.md)            | Generation backend: vendor-neutral, OpenAI-compatible       | Accepted, default endpoint partly superseded by [0011](0011-free-hosted-generation.md) |
| [0008](0008-per-model-embedding-columns.md)   | Per-model embedding columns (additive embedder swaps)       | Accepted |
| [0009](0009-mvp-corpus.md)                    | MVP corpus: release-engineering markdown                    | Accepted |
| [0010](0010-lightweight-embedding-and-reranking-models.md) | Lightweight embedding and reranking models on fastembed | Accepted |
| [0011](0011-free-hosted-generation.md)        | Free hosted generation endpoint (Groq) for the MVP          | Accepted |
| [0012](0012-bounded-agent-over-mcp.md)        | Bounded agent over MCP: a fixed state machine with cited output | Accepted |
