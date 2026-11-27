# mcp_server — Agent Context

`mcp_server` exposes `rag_core`'s retrieval to agents over the Model Context Protocol (MCP). See the
root [`AGENTS.md`](../../AGENTS.md) for project-wide context and
[`docs/architecture.md`](../../docs/architecture.md) for where it sits. The ADR that binds it is
the retrieval boundary (0001).

## Surface

- `study-mcp`: runs the server over stdio. A client starts it as a subprocess and speaks MCP over
  its standard input and output. It reads the same settings as the `study` CLI (`DATABASE_URL`,
  `EMBEDDING_*`), loads the embedding model at startup, and searches that model's vectors.
- One tool, `search(query, limit=5)`: returns up to `limit` (1 to 20) chunks nearest to the query,
  each as `{id, document, section, content, distance}`. `id` is the stored chunk id, which is what
  answers cite. `section` is the heading path joined with ` > `. `distance` is cosine distance.
- Invalid arguments are raised as `ValueError`, which the MCP SDK returns to the client as an error
  result rather than a broken connection.

## Conventions

- A consumer of `rag_core`, never a reimplementer. The tool validates arguments, calls `retrieve`,
  and reshapes the result. Ranking, embedding, and storage changes belong in `rag_core`, so the CLI,
  the eval harness, and the agent all see the same retrieval.
- The server is the only path from the agent to retrieval. `services/api` does not depend on
  `rag_core`, and a test there fails if its source imports it.
- `build_server(embedder=..., store=...)` takes its components as arguments, so tests connect an
  `mcp.Client` to a server built over the in-memory fakes, in-process, with no model or database.
  This is `mcp` 2.x: `MCPServer` (formerly `FastMCP`) and `mcp.Client`.
