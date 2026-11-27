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
- `study-ask "<question>" --review [--thread-id <id>]`: stops at the approval checkpoint instead
  of answering, and prints the query searched, each pending source with the relevance it was
  ranked by, the thread id, and the two commands that continue the run. The thread id is a fresh
  `uuid4().hex` unless one is given.
- `study-ask --resume <thread-id> (--approve | --reject)`: carries the decision to the saved run
  and prints its answer, or the next checkpoint when a rejection searched again. Needs
  `DATABASE_URL`. Exits 2 before anything starts for a resume without a decision, a decision
  without a resume, a question together with a resume, neither of them, a `--thread-id` without
  `--review`, and the approval flow without `DATABASE_URL`. A thread id that no paused run answers
  to also exits 2, but only once the search server and the saver are open, since the check reads
  the saved state through the compiled graph. A database that cannot be reached exits 1 with one
  line, like a failed model request.
- `api.graph`: `build_graph(search, generator, config=..., checkpointer=None)` compiles the agent,
  and `ask(graph, question, thread_id=None)` runs it and returns an `AgentAnswer` (status, answer,
  cited chunk ids, the resolved citations, the context shown to the model, queries, hops).
- `api.graph` approval checkpoint: with `require_approval`, `start(graph, question,
  thread_id=...)` runs until the sources need a decision and `resume(graph, decision,
  thread_id=...)` continues that run with `APPROVE` or `REJECT`. Both return an `AgentOutcome`:
  an `AgentAnswer`, or a `PendingReview` (thread id, question, query, hops, and the sources as
  `PendingSource` records of id, document, section, and the relevance they were ranked by).
- `api.graph.checkpoint`: `postgres_checkpointer(database_url)`, an async context manager over
  LangGraph's `AsyncPostgresSaver` that creates its own checkpoint tables on first use, and
  `checkpoint_serializer()`, the serializer it uses.
- `api.generate`: `GeneratorProtocol` and `OpenAICompatibleGenerator`, configured by the
  `GENERATION_*` settings in `api.config.ApiSettings`.
- `api.mcp_client`: `SearchClientProtocol` and `McpSearchClient`, which starts `study-mcp` over
  stdio (`stdio_server`) and calls its `search` tool.

## Conventions

- No `rag_core` import, ever. Retrieval is reached only through the MCP `search` tool, and
  `tests/test_retrieval_boundary.py` fails on any `rag_core` import under `src/api`. Tests may
  import `rag_core` and `mcp_server` to build an in-process server.
- The graph is a fixed state machine, not a tool-calling loop: `retrieve -> grade_relevance ->`
  `review_sources -> generate`, or `rewrite_query -> retrieve`, or `insufficient_context`. It
  searches at most `max_hops` times (default 2).
- `review_sources` is the human-in-the-loop checkpoint, and it is where every approval rule lives:
  - Without `require_approval` (the default) it approves the sources itself, so the one-shot path
    is unchanged.
  - With it, the node calls LangGraph's `interrupt` with the pending sources as plain values, and
    the run stops there until a decision arrives. The node runs again from the top on resume, so
    no earlier step is repeated.
  - A rejection costs a hop: it routes to `rewrite_query` while `hops < max_hops`, and to
    `insufficient_context` otherwise. Rejections are bounded by the same limit as low relevance.
  - Irrelevant context never reaches the checkpoint: there is nothing to approve, and the graph
    rewrites on its own.
  - `require_approval` without a checkpointer is refused when the graph is compiled, since a pause
    saved nowhere could not be resumed. `ask` refuses a graph that pauses, and `resume` refuses a
    thread id that is not waiting for a decision, which would otherwise start a new run on empty
    state. An unknown decision is refused rather than counted as a rejection.
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
- Paused runs are saved by `api.graph.checkpoint`, in the `DATABASE_URL` database, in LangGraph's
  own `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, and `checkpoint_migrations` tables.
  Writing checkpoints there is not a retrieval path: the corpus is still read only through the
  search tool.
  - The serializer is told about every type the state carries (`SearchHit`). An unlisted type is
    restored as a plain dictionary, which would fail later inside the answer step, and LangGraph
    will refuse unlisted types outright in a later version. Add new state types to
    `checkpoint_serializer()`, with a test.
  - Integration tests save to `TEST_DATABASE_URL` through the `checkpoint_database_url` fixture in
    `tests/conftest.py`, which drops the checkpoint tables afterwards.
- Fakes live in `tests/api_fakes.py`: `ScriptedGenerator` replays prepared replies and records
  requests, and `FakeSearchClient` answers queries with prepared hits.
