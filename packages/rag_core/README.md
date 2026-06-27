# rag_core

The shared retrieval library and the single home for all retrieval logic — ingestion,
embedding, hybrid retrieval (dense + BM25 + RRF), reranking, and pgvector access. The MCP
server, API, and CLI all depend on it as consumers; they never reimplement retrieval
(see [ADR 0001](../../docs/decisions/0001-rag-retrieval-boundary.md)).

Scaffold only at this phase — the modules (`ingest/`, `embed/`, `rerank/`, `retrieve/`,
`store/`) are built out in later phases. See [`AGENTS.md`](AGENTS.md) for the conventions that
govern this package.
