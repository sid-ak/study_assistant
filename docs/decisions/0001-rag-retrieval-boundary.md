# 1. RAG retrieval boundary: a shared `rag_core` library

- Status: Accepted
- Date: 2026-06-13

## Context

A core goal of the project is to decouple tooling from the model — the agent reaches retrieval
through a custom MCP server rather than importing it directly. Claude handles reasoning and
synthesis; retrieval (chunking, embedding, hybrid search, reranking) is a separate concern that
several components need: the MCP server (to expose it as tools), the FastAPI backend (for
ingestion/admin paths), and the CLI (for batch ingestion).

The question is where the retrieval logic should _physically_ live. Three options were considered:

1. Shared library, MCP + API both import it. Retrieval lives in a standalone package; the MCP
   server wraps it as tools, the API uses it directly.
2. MCP server owns retrieval. All RAG logic lives behind the MCP server; the API/LangGraph layer
   is a pure MCP client. Maximal decoupling, but ingestion/admin must also route through MCP or
   duplicate database access.
3. API owns retrieval, MCP is a façade. The backend owns the pipeline; the MCP server is a thin
   HTTP proxy. Adds a network hop for little gain and weakens the decoupling story.

## Decision

Adopt option 1: retrieval logic lives in a standalone `rag_core` library (chunking, embedding,
hybrid retrieval, reranking, pgvector access). Both the MCP server and the FastAPI backend depend on
it. The MCP server exposes it as tools; the API uses it directly for ingestion/admin; the CLI also
depends on it.

## Consequences

- Single home for retrieval. There is exactly one implementation; the MCP server and API are
  consumers, never reimplementers. This is enforced as a golden rule in `AGENTS.md`.
- No service-to-service hop for retrieval, and no duplicated database access for ingestion.
- `rag_core` is a shared dependency (a `uv` workspace path dependency), so its public surface
  must be treated as an internal API and versioned with care.
- The embedder and reranker sit behind a small interface in `rag_core`, so the rest of the
  system is agnostic to the concrete models. The only hard lock-in is the pgvector embedding
  dimension (`vector(N)`) — see [ADR 0002](0002-local-embedding-and-reranking.md).
- The "decoupling" property now depends on discipline (keeping the MCP server thin) rather than a
  physical service boundary; the golden rule in governance is what preserves it.
