# 08. Agents and Tools

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

An agent is a program that uses a language model to decide what to do next, acts through tools, and
repeats until it reaches an answer. In a RAG system, the simplest pipeline searches once and answers
once. An agent can instead check whether the search found anything useful, search again with a
better query, or decline to answer. This page covers agent loops as state machines, tool calling and
how to design a tool, the Model Context Protocol (MCP), why the loop must be bounded, how saving a
run's state makes it resumable, and where to put a person's approval inside the loop.

| Design | Who decides the next step | Number of model requests | Predictability |
| ------ | ------------------------- | ------------------------ | -------------- |
| Single pass | Fixed: search, then answer | One | Fully predictable |
| Fixed state machine | Code, from scores and results | Bounded by the graph | Predictable, with a known worst case |
| Open tool-calling loop | The model, on every turn | Unbounded unless capped | Varies with the model and the question |

## Agent loops as state machines

Why it matters: an agent that decides its own control flow is hard to test and harder to explain.
Writing the loop as a state machine makes every path something that can be listed, tested without
a model, and reproduced, which is what makes an agent defensible in a system that has to be
reliable.

A state machine is a set of steps, the state passed between them, and rules for which step comes
next. Writing an agent this way makes every path explicit.

```text
retrieve -> grade -> answer                    (the passages are relevant)
                  -> rewrite -> retrieve       (not relevant, searches left)
                  -> stop                      (not relevant, no searches left)
```

study_assistant is built this way on LangGraph. Every step is a named node, the transitions are
edges, and the two decisions are routing functions whose possible answers are listed where the edge
is declared, so the paths a run can take are readable in one place.

??? example "build_graph"

    ```python
    nodes = AgentNodes(search, generator, config)
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("grade_relevance", nodes.grade_relevance)
    graph.add_node("rewrite_query", nodes.rewrite_query)
    graph.add_node("review_sources", nodes.review_sources)
    graph.add_node("generate", nodes.generate)
    graph.add_node("insufficient_context", nodes.insufficient_context)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "grade_relevance")
    # route returns the name of the next step; every name it can return is listed here.
    graph.add_conditional_edges(
        "grade_relevance",
        nodes.route,
        ["review_sources", "rewrite_query", "insufficient_context"],
    )
    ```

Source: [`services/api/src/api/graph/agent.py:215-266`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/services/api/src/api/graph/agent.py#L215-L266)

The grading step is the clearest case of deciding in code rather than asking a model. It reads the
best hit's relevance, which the search already reported, and compares it with a threshold. No
request is made, so the decision costs nothing, is reproducible, and can be tested with a fake
search client.

??? example "grade_relevance"

    ```python
    hits = state["hits"]
    best_relevance = 0.0
    if hits:
        # Hits arrive ordered by relevance, so the first is the best.
        best_relevance = hits[0].relevance
    # With no hits there is nothing to answer from, whatever the threshold.
    relevant = bool(hits) and best_relevance >= self.config.relevance_threshold
    return {"relevant": relevant, "context": hits}
    ```

Source: [`services/api/src/api/graph/agent.py:114-128`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/services/api/src/api/graph/agent.py#L114-L128)
- State: a record of what the run knows so far, such as the question, the current query, the
  passages found, and how many searches were made. Each step reads the state and returns the parts
  it changes.
- Routing in code: when the decision about the next step is made by code from measurable values,
  such as a similarity score, the run's behavior can be tested without a model and reproduced
  exactly.
- Graph libraries: libraries such as LangGraph represent steps as nodes and transitions as edges,
  including conditional edges chosen by a routing function, and run the graph over a shared state.
- Corrective retrieval: grading the retrieved passages and searching again with a rewritten query
  when they are poor is a common pattern. It recovers from questions phrased differently from the
  documents.

## Tool calling

Why it matters: a tool is the only way a model can reach anything outside its own input. For a
retrieval system, the tool is how the model gets passages at all, so the tool's contract is the
interface the whole design rests on.

Tool calling lets a model ask the program to run a function. The program describes each tool with a
name, a description, and a JSON schema for its arguments. Instead of an answer, the model can reply
with a tool call: the tool's name and arguments. The program runs the tool and sends the result
back as a new message, and the model continues.

```json
{
  "name": "search",
  "description": "Return the passages nearest to the query, nearest first.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "limit": {"type": "integer", "minimum": 1, "maximum": 20}
    },
    "required": ["query"]
  }
}
```

- The model never runs code: it only produces a request to run a tool. The program decides whether
  to run it and with what permissions.
- Cost: every tool call is one model request to produce the call, then another to read the result.
  An answer that needs three searches through tool calling costs at least four requests.
- Reliability: models differ in how reliably they produce valid calls and pick the right tool.
  Smaller open-weight models are noticeably less reliable than large ones.
- An alternative: when the program already knows a search is needed, it can run the search itself
  and give the model only the results. The model is then used for what needs language, such as
  rewriting a query or writing the answer.

## Designing a tool

Why it matters: the tool's shape decides what the model can and cannot do. A narrow tool with
validated arguments and a result shaped for citing is the difference between an agent that can be
reasoned about and one that can do anything.

A tool is an interface for a reader that cannot ask follow-up questions, so its description and
results have to be self-explanatory.

- One job per tool: a `search` tool that only searches is easier to describe and use correctly than
  one that also filters, summarizes, and formats.
- Clear arguments: few arguments, with bounds stated in the schema, such as a limit between 1 and
  20. The service or the tool rejects out-of-range values instead of guessing.
- Results that can be cited: each result carries a stable id, its source, and its location, so an
  answer can refer to it and a reader can find it.
- Errors as results: a refused argument returns an error message the caller can read and correct,
  rather than ending the session.
- Small results: tool results enter the model's context, so returning a few short passages keeps
  room for the question and the answer.

study_assistant's server exposes exactly one tool, and every rule above is visible in it. It takes
a query and a limit, rejects an empty query and a limit outside 1 to 20 before doing any work, and
returns each chunk's id, source document, heading path, text, distance and relevance, which is what
an answer cites. The error type is the detail worth knowing: the SDK treats its own `ToolError` as
an anticipated failure whose message reaches the client, while any other exception reads as a crash
and the client sees nothing useful.

??? example "search"

    ```python
    # ToolError is the SDK's anticipated failure: its message reaches the client. Any other
    # exception is treated as a crash, and the client sees only a generic message.
    if not query.strip():
        raise ToolError("query must contain text.")
    if limit < 1 or limit > MAX_SEARCH_LIMIT:
        raise ToolError(f"limit must be 1 to {MAX_SEARCH_LIMIT}, not {limit}.")
    result = retrieve(
        query,
        embedder=self.embedder,
        store=self.store,
        limit=limit,
        reranker=self.reranker,
        candidates=self.candidates,
        hybrid=self.hybrid,
    )
    return [hit_from_chunk(chunk) for chunk in result.chunks]
    ```

Source: [`services/mcp_server/src/mcp_server/server.py:61-85`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/services/mcp_server/src/mcp_server/server.py#L61-L85)

## The Model Context Protocol

Why it matters: it turns a tool from something wired into one program into something any client can
call. For this project it also draws a boundary: the agent cannot reach the database except through
the tool.

The Model Context Protocol (MCP) is an open protocol for exposing tools, and other context such as
documents, to agents. A server implements the tools. A client, inside the agent, connects to the
server, lists its tools, and calls them.

- Messages: client and server exchange JSON-RPC messages. A tool listing returns each tool's name,
  description, and argument schema. A tool call returns content and, optionally, structured data,
  or an error result.
- Transports: a client can start the server as a subprocess and talk over its standard input and
  output (stdio), or connect to a server over HTTP.
- Separation: the tool's implementation lives in the server, and the agent's logic lives in the
  client. Either can be replaced without changing the other, and the same server can serve several
  agents and applications.
- Boundary: when the agent's only access to a capability is the MCP tool, the protocol becomes an
  enforced boundary. The agent cannot reach into the database or call internal functions directly.

> A course assistant exposes a `search` tool through an MCP server that owns the vector database. A
> chat agent, a command-line tool, and an editor plugin all connect as clients. When the search
> improves, all three get the improvement without any change to their code.

In study_assistant the boundary is not a convention but a test. The agent's package has no
dependency on the retrieval library, and a test parses every module in it and fails on any import
of that library, which was itself checked by planting one. The client starts the server as a
subprocess over stdio and holds one connection for a whole run, and it passes the server only the
environment variables it needs, so the generation key never reaches it.

## Bounded loops

Why it matters: an unbounded loop is the failure mode agents are known for, spending time and money
without converging. A hard limit turns that from an open risk into a known worst case.

A bound is a hard limit on how many steps a run may take, such as at most two searches per
question.

- Guaranteed termination: an open loop can repeat a failing search indefinitely. A bound makes
  every run end, with an answer or an explicit "not enough information".
- Known cost: the worst case in requests, tokens, and time is known before the run, which matters
  under rate limits and for latency targets.
- An explicit failure result: when the limit is reached without relevant evidence, returning
  "insufficient context" is a correct outcome, not an error. It is better than answering from
  irrelevant passages.
- Choosing the limit: one retry recovers most questions whose first query was poorly phrased.
  Further retries cost the same each time and help less, so small limits are common.

study_assistant allows two searches per question: the first, and one more after rewriting the query
if the first was graded irrelevant. The worst case is therefore two searches and two model requests
per question, which is what makes it safe to run on a free plan. Reaching the limit without
relevant context ends the run on the insufficient-context path rather than answering anyway, and a
rejection at the approval step routes through the same bound, so a rejected run cannot loop either.

## Checkpointing: saving a run between steps

Why it matters: without saved state, a run exists only in the memory of the process running it. With
it, a run can be paused, inspected, and resumed somewhere else, which is what makes human approval
possible at all.

A checkpointer saves the state of a run after each step, under a name for the run, usually called a
thread. The run becomes durable: it can be read back, continued, or inspected after the process
that started it is gone.

```text
retrieve   -> save  (question, query, passages, searches so far)
grade      -> save
answer     -> save
```

- Thread: the name a run's saved states share. Continuing a run means pointing the graph at the
  same thread; a new name starts from an empty state.
- Checkpoint: one saved state, written after a step. Keeping each one rather than overwriting lets
  a run be replayed, or rolled back and continued differently.
- Where it is saved: in memory for tests, in a database for anything that must survive a restart.
  The store is a separate concern from the graph, so the same graph runs with either.
- Serialization: the state has to be written as bytes and read back. Values a serializer does not
  recognize come back as something simpler, such as a plain dictionary in place of a record, which
  then fails in a step that expected the record. A state type the store does not know about is a
  bug waiting for the first resume.
- What it buys beyond durability: a run can be inspected while it is in progress, continued on
  another machine, and audited afterwards, because every step's state was recorded.

study_assistant saves checkpoints in the same Postgres database that holds the corpus, through
LangGraph's Postgres saver, which creates its own tables on first use. Two details came out of
building it, and both are the kind of thing only a real resume exposes.

- The serializer has to be told about the types the state carries. A retrieved hit it does not
  recognize comes back as a plain dictionary, and the failure surfaces much later, inside the
  answer step, as an attribute error that says nothing about serialization.
- The payload a pause carries is restricted to plain values, because the process that resumes a run
  may have none of the project's classes loaded. That is a constraint on what a checkpoint can
  contain, not a style preference.

Using the corpus database for checkpoints does not make the agent a database client: the saver
writes only LangGraph's own tables, and the agent still reads documents through the tool, which the
import test enforces.

## Human in the loop

Why it matters: some actions should not happen on a model's judgment alone. A checkpoint where a
person approves what the run is about to use is the standard way to put a decision back in human
hands, and it is a requirement in regulated and safety-certified work.

A human-in-the-loop checkpoint is a point where the run stops, presents what it has, and waits for
a person's decision before continuing. Durable checkpointing is what makes it practical, because
the wait can be arbitrarily long.

```text
retrieve -> grade -> review -> answer                  (approved)
                            -> rewrite -> retrieve     (rejected, searches left)
                            -> stop                    (rejected, no searches left)
```

- The mechanism: the step raises a pause that carries a payload, such as the passages found. The
  framework saves the run and returns the payload to the caller. A later call supplies the
  decision, which becomes the pause's result, and the step runs again from its start.
- Where to put it: before an action that is expensive, irreversible, or hard to judge afterwards.
  In a RAG system that is just before the answer is written, where a person can see the evidence
  the answer would rest on. Pausing after the answer costs the generation anyway, and pausing
  before retrieval shows the person nothing to judge.

study_assistant puts the checkpoint between grading and answering, and keeps it in the graph
always, with a setting deciding whether it pauses. One graph with a pass-through step is easier to
reason about than two graphs, and it means the approval path and the direct path share every other
step.

What the pause presents is built as plain values, for the reason given above: whatever resumes the
run may be a different process.

??? example "review_payload"

    ```python
    sources: list[dict[str, Any]] = []
    for hit in state["hits"]:
        sources.append(
            {
                "id": hit.id,
                "document": hit.document,
                "section": hit.section,
                "relevance": hit.relevance,
            }
        )
    ```

Source: [`services/api/src/api/graph/review.py:43-64`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/services/api/src/api/graph/review.py#L43-L64)

Four things that could fail quietly are refused instead, which is the part worth describing as
design rather than defensiveness: requiring approval with nowhere to save a pause fails when the
graph is compiled; asking for a plain answer from a graph that can pause explains which calls to
use; resuming a thread that nothing is waiting on names the thread rather than silently starting a
new run on empty state; and a decision that is neither of the two accepted words is refused rather
than counted as a rejection. The third of those was found by probing the library, which runs the
graph from the start on an unknown thread id instead of failing.
- What to present: enough to decide and no more. The sources' titles and locations, and the score
  each was ranked by, are enough to see whether the evidence fits the question; the full passages
  are usually too much to read.
- A rejection needs a next step: it is not just "no". Routing a rejection to a rewritten query and
  one more search makes it useful, and spending one of the run's bounded searches on it keeps the
  loop finite, so a person cannot make a run go on forever.
- Payload across processes: whatever resumes the run may be another program, so the payload should
  be plain data, not objects whose classes have to be loaded.
- Resuming safely: a name that no paused run answers to is an error worth reporting. A framework
  that treats a decision for an unknown thread as a fresh run will silently start one.
- Cost: one saved state per step, one more round trip, and a run whose latency is now set by a
  person rather than by the model.

The practical rule is to write the agent as a state machine whose routing is decided in code where
possible, give the model only the steps that need language, expose capabilities as small tools with
citable results behind a protocol boundary, bound every loop so each run ends with an answer or an
explicit refusal, and save each step's state when a run has to outlive its process or wait for a
person.
