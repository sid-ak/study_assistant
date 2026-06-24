# Architecture Decision Records

Short records of the significant decisions on this project, in
[Nygard ADR](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) format:
_context → decision → consequences_. They are the durable record of _why_ the project is shaped the
way it is. The architecture and structure live in [`../architecture.md`](../architecture.md); the
phased build plan is tracked as
[GitHub issues](https://github.com/sid-ak/study_assistant/issues?q=is%3Aissue%20label%3Aphase).

| ADR                                           | Decision                                                | Status   |
| --------------------------------------------- | ------------------------------------------------------- | -------- |
| [0000](0000-stack.md)                         | Stack: Python, FastAPI, PostgreSQL, React               | Accepted |
| [0001](0001-rag-retrieval-boundary.md)        | RAG retrieval boundary: a shared `rag_core` library     | Accepted |
| [0002](0002-local-embedding-and-reranking.md) | Embedding and reranking stack: local open-source models | Accepted |
| [0003](0003-local-single-user-scope.md)       | Deployment scope: local single-user                     | Accepted |
| [0004](0004-cli-batch-ingestion.md)           | Document ingestion: CLI batch                           | Accepted |
