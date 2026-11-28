# 03. Bounded Agent over MCP

> Part of the [Project](README.md) section of [AI, RAG & Python](../README.md). Built in
> [study_assistant#48](https://github.com/sid-ak/study_assistant/issues/48), pull request
> [study_assistant#73](https://github.com/sid-ak/study_assistant/pull/73).

Chunk 3 built the generation lane. A question goes to an agent that searches the corpus through an
MCP server, checks whether the best result is similar enough to the question, and asks a hosted
language model for a short answer that cites the chunks it used. The agent is a fixed state
machine: it searches at most twice, makes at most two model requests, and always ends with either a
cited answer or an explicit "insufficient context". `study-ask` runs it from the command line, and
`study-eval-agent` checks its citations over the golden set.

| Piece | Module | What it does |
| ----- | ------ | ------------ |
| MCP server | `services/mcp_server` | Exposes `rag_core`'s `retrieve` as one `search` tool |
| MCP client | `services/api/src/api/mcp_client` | Starts the server over stdio and turns tool results into `SearchHit` records |
| Generator | `services/api/src/api/generate` | `GeneratorProtocol` and an OpenAI-compatible adapter with 429 waits and a reply cache |
| Agent graph | `services/api/src/api/graph` | `retrieve -> grade_relevance -> generate`, or `rewrite_query -> retrieve`, or stop |

Chunk 6 later added one step between grading and generation, the approval checkpoint, which this
page's diagrams predate; see
[Human-in-the-Loop Checkpoint](06-human-in-the-loop-checkpoint.md).
| Commands | `services/api`, `evals` | `study-ask "<question>"` and `study-eval-agent <name>` |
| Decision record | ADR 0012 | The bounded loop, the threshold, and cited structured output |

The general theory is in [Generation](../concepts/07-generation.md),
[Agents and Tools](../concepts/08-agents-and-tools.md), and the grounding section of
[Evaluation](../concepts/09-evaluation.md).

## The MCP server and the retrieval boundary

Why it matters: this is the stage where retrieval stops being a function call and becomes a tool
contract. The boundary it draws is what keeps the agent from reaching into the database directly.

The server is a thin adapter: it validates arguments, calls `retrieve`, and reshapes each chunk into
a record an agent can cite.

??? example "SearchTool"

    ```python
    class SearchTool:
        def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[SearchHit]:
            if not query.strip():
                raise ToolError("query must contain text.")
            if limit < 1 or limit > MAX_SEARCH_LIMIT:
                raise ToolError(f"limit must be 1 to {MAX_SEARCH_LIMIT}, not {limit}.")
            result = retrieve(query, embedder=self.embedder, store=self.store, limit=limit)
            return [hit_from_chunk(chunk) for chunk in result.chunks]


    server = MCPServer(SERVER_NAME)
    tool = SearchTool(embedder, store)
    # The tool's name, description, and argument schema come from the method's signature and
    # docstring.
    server.add_tool(tool.search, name="search")
    ```

Source: [`services/mcp_server/src/mcp_server/server.py:38-79`](https://github.com/sid-ak/study_assistant/blob/3200fe0/services/mcp_server/src/mcp_server/server.py#L38-L79)

- One tool: `search(query, limit=5)` returns `{id, document, section, content, distance}` per chunk.
  The id is the stored chunk id, which is what answers cite.
- `ToolError`, not `ValueError`: in the MCP SDK (`mcp` 2.x), a `ToolError` reaches the client as an
  error result carrying its message. Any other exception is treated as a crash, and a probe showed
  the client then sees only "Error executing tool search".
- An enforced boundary: `services/api` has no `rag_core` dependency, and a test parses every module
  under its source with `ast` and fails on any `rag_core` import. The test was checked to fail with a
  planted import.
- In-process tests: `mcp.Client` accepts a server object and connects to it in-process, so the tests
  drive the real MCP protocol over the in-memory store and hashing embedder, with no subprocess.

## The MCP client

Why it matters: the client owns the connection for a whole run, so where it is opened and closed
decides how many times a model gets loaded and how errors surface.

`McpSearchClient` holds one MCP connection for a whole run.

??? example "answer_question"

    ```python
    server = stdio_server(settings.mcp_server_command, Path.cwd())
    async with McpSearchClient(server) as search:
        graph = build_graph(search, generator, config=config)
        return await ask(graph, question)
    ```

Source: [`services/api/src/api/cli.py:34-37`](https://github.com/sid-ak/study_assistant/blob/3200fe0/services/api/src/api/cli.py#L34-L37)

- Async context manager: entering starts the server process and opens the connection, and every
  search reuses it. The class implements `__aenter__` and `__aexit__` directly.
- Exception groups: the SDK's client runs an `anyio` task group, and a probe showed that an exception
  raised inside `async with Client(...)` escapes wrapped in nested `ExceptionGroup`s. The client's
  `__aexit__` closes the connection as a clean exit, so Python re-raises the original exception and
  callers can catch `SearchError` directly.
- The server's environment: the client passes only `DATABASE_*`, `EMBEDDING_*`, `FASTEMBED_*`, and
  `TMPDIR`, on top of the SDK's safe defaults, so the generation key never reaches the server. The
  first version left out `TMPDIR`: fastembed keeps its model cache under the temporary folder, so the
  server looked in `/tmp`, downloaded a second copy of the model, and took 4.3 s to connect instead
  of 0.9 s.

## The Generator and the free plan

Why it matters: the model endpoint is the one part of this system that can refuse to answer.
Handling that refusal is what separates a pipeline that pauses from one that fails halfway through
an evaluation run.

`GeneratorProtocol.generate(messages, response_schema=None)` returns one reply: free text, or JSON
matching a strict schema. `OpenAICompatibleGenerator` sends chat-completion requests with `httpx`
at temperature 0.

??? example "from_settings"

    ```python
    if response.status_code != 429:
        break
    if retries == MAX_RETRIES:
        raise RateLimitError(
            f"{self.base_url} is still rate limiting after {MAX_RETRIES} retries."
        )
    wait = wait_from_headers(response.headers)
    if wait is None:
        # No hint from the endpoint: wait 1, 2, 4, then 8 seconds.
        wait = 2.0**retries
    if wait > self.max_wait_seconds:
        raise RateLimitError(
            f"{self.base_url}'s rate limit resets in {wait:.0f} s, "
            f"longer than the {self.max_wait_seconds:.0f} s this client waits."
        )
    self.sleep(wait)
    ```

Source: [`services/api/src/api/generate/openai_compatible.py:75-141`](https://github.com/sid-ak/study_assistant/blob/3200fe0/services/api/src/api/generate/openai_compatible.py#L75-L141)

- Reading the wait: `retry-after` if present, otherwise the reset of whichever budget ran out, in
  the provider's `1m26.4s` format. `parse_duration` reads hours, minutes, seconds, and milliseconds.
- An injected `sleep`: tests pass a function that records each wait instead of pausing, so they
  assert the exact delays and run instantly.
- Cache: replies are stored on disk under the SHA-256 of the whole request body, which holds the
  model, every message, and the schema. A live repeat took 400 ms, then 0 ms from the cache.
- No key in errors: an error reply raises `GenerationError` naming only the HTTP status, since an
  error body can echo the request.

## The graph

Why it matters: this is where the agent's control flow becomes explicit. Writing it as named steps
with listed transitions is what makes its behavior testable without a model and reproducible with
one.

??? example "__post_init__"

    ```python
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("grade_relevance", nodes.grade_relevance)
    graph.add_node("rewrite_query", nodes.rewrite_query)
    graph.add_node("generate", nodes.generate)
    graph.add_node("insufficient_context", nodes.insufficient_context)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "grade_relevance")
    graph.add_conditional_edges(
        "grade_relevance",
        nodes.route,
        ["generate", "rewrite_query", "insufficient_context"],
    )
    graph.add_edge("rewrite_query", "retrieve")
    return graph.compile(checkpointer=checkpointer)
    ```

Source: [`services/api/src/api/graph/agent.py:54-233`](https://github.com/sid-ak/study_assistant/blob/3200fe0/services/api/src/api/graph/agent.py#L54-L233)

- State: `AgentState` is a `TypedDict` with `total=False`. Each step returns only the keys it
  changes, and LangGraph merges them into the run's state.
- Grading without a model: `grade_relevance` takes the top hit's cosine similarity, 1 minus its
  distance, and compares it with 0.65. `route` then picks the next step from that grade and the hop
  count.
- One request per step: only `rewrite_query` (free text) and `generate` (strict schema) call the
  model. Both call the synchronous generator through `asyncio.to_thread`, so the event loop that
  carries the MCP connection is not blocked during a request.
- The threshold came from a probe: the ten golden questions' top hits scored 0.668 to 0.884,
  off-topic questions 0.45 to 0.64, and questions near the corpus that it cannot answer up to 0.738.
  No value separates the last group, so the threshold only screens out clearly irrelevant context,
  and the model's `answerable` field handles the rest.
- Checkpointer: `build_graph` takes an optional checkpointer, none by default. A test runs the graph
  with LangGraph's in-memory saver and reads the saved state back.

## Cited structured output

Why it matters: this is where grounding stops being a request in a prompt and becomes a constraint
the model cannot violate.

The answer is one strict-schema request whose cited ids can only be ids the model was shown.

??? example "answer_schema"

    ```python
    context_ids = [hit.id for hit in context]
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean"},
            "answer": {"type": "string"},
            "cited_chunk_ids": {"type": "array", "items": {"type": "string", "enum": context_ids}},
        },
        "required": ["answerable", "answer", "cited_chunk_ids"],
        "additionalProperties": False,
    }
    ```

Source: [`services/api/src/api/graph/prompts.py:48-58`](https://github.com/sid-ak/study_assistant/blob/3200fe0/services/api/src/api/graph/prompts.py#L48-L58)

- The `enum` is built per request from the context's chunk ids. A probe confirmed the provider
  accepts a dynamic `enum` in strict mode and that the model then cites only those ids.
- `answerable: false` ends the run as insufficient context, which is how a question near the
  corpus that it cannot answer ends cleanly.
- The instructions say ids go in `cited_chunk_ids` only, never in the answer text. ADR 0011's probe
  had seen this model copy ids into the text. In the agent evaluation, no answer did.

## Python used

Why it matters: these are the language features this stage leans on, listed so the page can be
read as Python practice as well as design.

| Feature | Where it appears | What it does here |
| ------- | ---------------- | ----------------- |
| `async def`, `await`, `asyncio.run` | MCP client, graph steps, commands | One event loop carries the MCP connection and the graph run |
| `__aenter__` and `__aexit__` | `McpSearchClient` | Makes the client an `async with` context manager that owns the connection |
| `asyncio.to_thread` | `rewrite_query`, `generate` | Runs the blocking HTTP request in a thread so the event loop stays free |
| `TypedDict` with `total=False` | `AgentState` | A typed dict whose keys may be absent, so a step can return only what it changes |
| `typing.Protocol`, `@runtime_checkable` | `GeneratorProtocol`, `SearchClientProtocol` | Interfaces the fakes and real classes satisfy by shape |
| `pydantic.SecretStr` | `ApiSettings.generation_api_key` | Keeps the key out of `repr` and logs |
| `httpx.MockTransport` | Generator tests | Answers requests in-process, so tests check exactly what the adapter sends |
| `ast.parse`, `ast.walk` | Retrieval-boundary test | Reads every import in the source without importing it |
| `hashlib.sha256`, `json.dumps(sort_keys=True)` | Reply cache | The same request always gives the same key |
| `__call__` | `GraphAnswerer` | An object that can be called like a function, holding the graph it answers with |

## Design trade-offs

Why it matters: each row is a decision that could have gone the other way, with the record that
settled it and the alternative it rejected.

| Decision | Chosen | Rejected alternative | Record |
| -------- | ------ | -------------------- | ------ |
| Agent shape | A fixed state machine with a two-search limit | An open tool-calling loop, unbounded and one extra request per search | [ADR 0012](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0012-bounded-agent-over-mcp.md) |
| Relevance grading | Top-hit similarity against 0.65, no model call | A model call per grade, which spends quota on every hop | ADR 0012, [ADR 0011](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0011-free-hosted-generation.md) |
| Path to retrieval | The MCP `search` tool only | Importing `rag_core` in the agent | [ADR 0001](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0001-rag-retrieval-boundary.md) |
| Generation endpoint | Groq's free plan through the OpenAI-compatible protocol | A vendor SDK, or a local model too small for this machine | [ADR 0007](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0007-generation-backend.md), ADR 0011 |
| Citations | A strict schema with an `enum` of context ids | Free text with ids parsed out of the answer | ADR 0012 |
| Testing the agent eval | The agent passed in as an async function | Reusing the API package's fakes across packages | Pull request #73 |

## Measured results

Why it matters: these are the numbers this stage produced, and they are what any claim about it
rests on.

Measured on an M1 with 8 GB of memory, `bge-small-en-v1.5` for retrieval and `qwen/qwen3.8-27b` on
Groq for generation.

| Measurement | Result |
| ----------- | ------ |
| Agent evaluation, ten golden questions | 10 answered, grounding pass rate 1.00, citation recall 0.90 |
| Searches per question in that run | 1 for every question |
| Agent latency per question | p50 1.0 s, p95 9.7 s (one outlier; the rest about 1 s) |
| `study-ask`, answerable question | Answered from one search, 4.0 s including server start |
| `study-ask "What is the capital of France?"` | Rewritten, searched twice, no answer request |
| MCP server connect over stdio | 0.9 s, or 4.3 s when it re-downloaded the model |
| Cached repeat of a generation request | 400 ms, then 0 ms |

- Citation recall 0.90: the two partial questions are the ones whose answers span two documents.
  Each cites the one labeled section retrieval returned; the other was not in the top five, so the
  model never saw it. The miss belongs to retrieval, which the reranker and hybrid search target.
- The version trap: for "What CMake version does Orbit 5.0 require?", retrieval ranked Orbit 4.0's
  breaking changes first, and the answer still cited the CI write-up about the 5.0 upgrade and gave
  the correct version, 3.28.
- The outlier: one question took 9.7 s. The adapter does not log rate-limit waits, so whether it
  waited on the per-minute token budget is not known.

## Interview questions

Why it matters: the questions this stage invites, with answers short enough to say out loud.

Why a fixed state machine instead of letting the model call the search tool?
: The graph already knows when a search is needed, so a tool call would spend a model request to
  make a decision the code makes for free. A fixed graph bounds every run at two searches and two
  model requests, which matters on a 30-requests-per-minute plan, and its routing can be tested
  without a model.

How does the agent decide whether the retrieved context is good enough?
: It compares the top hit's cosine similarity with a threshold of 0.65, measured on the golden set
  and on off-topic questions. That screens out clearly irrelevant context without a model call.
  Questions close to the corpus that it cannot answer score as high as some answerable ones, so the
  final decision is the model's, through an `answerable` field in the schema.

How do you stop the model from citing sources it was not given?
: The answer's schema restricts `cited_chunk_ids` to an `enum` of the ids sent in the prompt, and
  strict structured output enforces the schema during decoding. The agent evaluation still checks
  every citation against the context, since the guarantee rests on the provider.

What does MCP give you over a direct function call?
: A protocol boundary. The search implementation lives in a server process, and the agent only sees
  a tool with a schema. The agent cannot touch the database, the server can serve other clients,
  and either side can change without the other. A test enforces that the agent never imports the
  retrieval library.

How does the client survive the free plan's rate limits?
: On HTTP 429 it waits for the reset the response headers give and retries, up to four times, and
  refuses to wait longer than 90 seconds, so a spent daily budget fails fast. Replies are cached
  under a hash of the whole request, so an unchanged rerun of the eval makes no requests.

What did evaluating generation separately from retrieval show?
: All answers were grounded, and the only citation misses were sections that retrieval never
  returned. So the next improvements belong in retrieval, which is what the reranker and hybrid
  search chunks measure.
