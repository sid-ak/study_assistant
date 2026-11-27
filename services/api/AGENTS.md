# api — Agent Context

`api` is the generation lane: the agent that answers a question by searching the corpus through the
MCP server and asking a language model for a cited answer. FastAPI routes come in a later phase. See
the root [`AGENTS.md`](../../AGENTS.md) for project-wide context and
[`docs/architecture.md`](../../docs/architecture.md) for where it sits. The ADRs that bind it are the
retrieval boundary (0001), the generation backend (0007), the free hosted endpoint (0011), and the
bounded agent (0012).

## Surface

- `study-ask "<question>"`: starts the MCP server over stdio, runs the agent once, and prints
  the answer with its sources (document and heading path), or a plain insufficient-context
  message, then the searches made. Exits 1 with a one-line message if the model or the search
  tool fails. Bounds come from `AGENT_MAX_HOPS`, `AGENT_RELEVANCE_THRESHOLD`, and
  `AGENT_SEARCH_LIMIT`.
- `api.graph`: `build_graph(search, generator, config=..., checkpointer=None)` compiles the agent,
  and `ask(graph, question, thread_id=None)` runs it and returns an `AgentAnswer` (status, answer,
  cited chunk ids, the resolved citations, the context shown to the model, queries, hops).
- `api.generate`: `GeneratorProtocol` and `OpenAICompatibleGenerator`, configured by the
  `GENERATION_*` settings in `api.config.ApiSettings`.
- `api.mcp_client`: `SearchClientProtocol` and `McpSearchClient`, which starts `study-mcp` over
  stdio (`stdio_server`) and calls its `search` tool.

## Conventions

- No `rag_core` import, ever. Retrieval is reached only through the MCP `search` tool, and
  `tests/test_retrieval_boundary.py` fails on any `rag_core` import under `src/api`. Tests may
  import `rag_core` and `mcp_server` to build an in-process server.
- The graph is a fixed state machine, not a tool-calling loop: `retrieve -> grade_relevance ->`
  `generate`, or `rewrite_query -> retrieve`, or `insufficient_context`. It searches at most
  `max_hops` times (default 2).
- One model request per step. Grading uses the top hit's `relevance` as the MCP server reports it
  (the cross-encoder's score when `RERANK_ENABLED` is on, the cosine similarity otherwise) against
  `relevance_threshold` (default 0.65), with no model call. Only `rewrite_query` (free text)
  and `generate` (strict JSON schema) call the model.
- The answer schema's `cited_chunk_ids` is an `enum` of the context's chunk ids, and the
  instructions keep ids out of the answer text. `AgentAnswer.cited_chunk_ids` keeps whatever the
  model returned, so a grounding check can still catch an id outside the context.
- The generator is synchronous (`httpx`); graph steps call it through `asyncio.to_thread`, so the
  MCP connection's event loop is not blocked during a request.
- Rate limits and caching live in the adapter, not the graph: it waits out HTTP 429 using the reset
  headers, sends its own User-Agent, and caches replies under `GENERATION_CACHE_DIR`.
- Fakes live in `tests/api_fakes.py`: `ScriptedGenerator` replays prepared replies and records
  requests, and `FakeSearchClient` answers queries with prepared hits.
