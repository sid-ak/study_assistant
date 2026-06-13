# Architecture Decision Records

Short records of the significant decisions on this project, in
[Nygard ADR](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) format:
*context → decision → consequences*. They are the durable record of *why* the project is shaped the
way it is. The phased build plan and structure live in [`../PLAN.md`](../PLAN.md).

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-rag-retrieval-boundary.md) | RAG retrieval boundary: a shared `rag_core` library | Accepted |
| [0002](0002-local-embedding-and-reranking.md) | Embedding and reranking stack: local open-source models | Accepted |
| [0003](0003-local-single-user-scope.md) | Deployment scope: local single-user | Accepted |
| [0004](0004-cli-batch-ingestion.md) | Document ingestion: CLI batch | Accepted |
