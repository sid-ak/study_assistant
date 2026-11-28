# 06. Human-in-the-Loop Checkpoint

> Part of the [Project](README.md) section of [AI, RAG & Python](../README.md). Built in
> [study_assistant#70](https://github.com/sid-ak/study_assistant/issues/70), pull request
> [study_assistant#76](https://github.com/sid-ak/study_assistant/pull/76).

Chunk 6 added a stop in the middle of the agent: after retrieval has found its sources and before
the answer is written, the run can pause and wait for a person to approve them. The paused run is
saved in Postgres under a thread id, so the decision can arrive minutes later, from a different
process. Approval continues to the answer; rejection spends one of the run's two searches on a
rewritten query and stops at the same checkpoint again.

| Piece | Module | What it does |
| ----- | ------ | ------------ |
| Checkpoint step | `api/graph/agent.py` | `review_sources`, between the relevance grade and the answer |
| What a pause carries | `api/graph/review.py` | `PendingReview`, `PendingSource`, and the plain payload they travel as |
| Where pauses are saved | `api/graph/checkpoint.py` | LangGraph's `AsyncPostgresSaver`, and the serializer it uses |
| Driving it | `api/cli.py` | `study-ask --review`, then `study-ask --resume <thread-id> --approve` or `--reject` |

The general theory is in [Agents and Tools](../concepts/08-agents-and-tools.md), sections 6 and 7.

## One step, two behaviors

Why it matters: this is the stage that puts a person back in the loop before the system commits to
an answer, which is a requirement wherever a decision has to be auditable. The design question is
whether that costs a second graph.

??? example "agent"

    ```python
    async def review_sources(self, state: AgentState) -> AgentState:
        """The checkpoint: pause for a decision on the graded sources, when one is required.

        ``interrupt`` stops the run here and saves it. What a later resume passes back in becomes
        its return value, and this step runs again from the top, so nothing before it is repeated.
        Without ``require_approval`` the step approves the sources itself and the run goes on.
        """
        if not self.config.require_approval:
            return {"approved": True}
        decision = interrupt(review_payload(state))
        return {"approved": decision_is_approval(decision)}
    ```

Source: [`services/api/src/api/graph/agent.py:15-351`](https://github.com/sid-ak/study_assistant/blob/d42f445/services/api/src/api/graph/agent.py#L15-L351)

- One graph, not two: the step is always in the graph, and `require_approval` decides whether it
  pauses. The one-shot path gains a pass-through node instead of the project gaining a second state
  machine to reason about.
- `interrupt` stops the run where it is called, saves it, and hands its payload to whoever started
  the run. The decision supplied later becomes the call's return value, and the step runs again
  from its first line, so no earlier step is repeated.
- Routing a rejection reuses the grade's own routing, so a rejection is bounded exactly as low
  relevance is:

??? example "route"

    ```python
    def route_after_review(self, state: AgentState) -> str:
        """The step after the checkpoint: generate the answer, or try again, or stop."""
        if state["approved"]:
            return "generate"
        return self.retry_or_stop(state)
    ```

Source: [`services/api/src/api/graph/agent.py:134-152`](https://github.com/sid-ak/study_assistant/blob/d42f445/services/api/src/api/graph/agent.py#L134-L152)

- Irrelevant context never reaches the checkpoint. There is nothing to approve below the
  threshold, and the graph already rewrites on its own.
- A new key in the state (`approved`) has to be declared in the `TypedDict`. LangGraph merges only
  the keys the state declares, so a step returning an undeclared key is silently dropped, and the
  routing that read it failed with a `KeyError` until the channel was added.

## Refusing what cannot work

Why it matters: a pause that cannot be resumed is worse than no pause, because the run is lost
silently. Each refusal here replaces a failure that would otherwise look like success.

The checkpoint has four ways to fail quietly, and each one is refused instead.

| Situation | Without the refusal | With it |
| --------- | ------------------- | ------- |
| Approval required, no checkpointer | The run pauses with nowhere to save it | `build_graph` raises when compiled |
| `ask` on a graph that pauses | `KeyError` on the missing status | A message naming `start` and `resume` |
| Resuming a thread id nothing is waiting on | A new run starts on empty state | A message naming the thread id |
| A decision that is neither word | Counted as a rejection | A message naming the two words |

??? example "resume"

    ```python
    config = thread_config(thread_id)
    saved = await graph.aget_state(config)
    # Resuming a thread that is not paused would run the graph from the start on empty state.
    if not saved.interrupts:
        raise ValueError(f"No run under thread id {thread_id!r} is waiting for a decision.")
    # Checked here as well as in the node, so a bad decision costs no saved state.
    decision_is_approval(decision)
    final: RunResult = await graph.ainvoke(Command(resume=decision), config=config)
    ```

Source: [`services/api/src/api/graph/agent.py:352-359`](https://github.com/sid-ak/study_assistant/blob/d42f445/services/api/src/api/graph/agent.py#L352-L359)

The third row is the one that had to be discovered rather than designed. A probe against the
installed library showed that a decision for an unknown thread id does not fail: the graph runs
from the start, on a state with no question in it. The guard reads the saved state first and
refuses before anything runs.

Three library calls carry the resume, and they are worth naming because each answers a different
question:

- `graph.aget_state(config)` reads back the state saved under this thread id. `config` is a
  `RunnableConfig` carrying `configurable.thread_id`, which is how every call to a compiled graph
  says which run it means.
- `saved.interrupts` is what distinguishes a paused run from an unknown one. It is non-empty only
  while a run sits at an `interrupt`.
- `graph.ainvoke(Command(resume=decision), config=config)` continues it. `Command(resume=...)` is
  the counterpart to `interrupt`: the value it carries becomes the return value of the `interrupt`
  call in `review_sources`. Starting a run uses the same `ainvoke` with an initial state in place
  of the `Command`, so start and resume differ only in what is passed.

## Saving the state in Postgres

Why it matters: a paused run has to outlive the process that started it, or approval is only
possible while someone waits. This is what makes the wait arbitrarily long.

??? example "checkpoint"

    ```python
    def checkpoint_serializer() -> JsonPlusSerializer:
        """The serializer saved runs use, told about the types the graph's state carries.

        A type the serializer does not know is restored as a plain dictionary, which the answer step
        would only trip over later, so every such type is listed here.
        """
        return JsonPlusSerializer(allowed_msgpack_modules=(SearchHit,))
    ```

Source: [`services/api/src/api/graph/checkpoint.py:6-39`](https://github.com/sid-ak/study_assistant/blob/d42f445/services/api/src/api/graph/checkpoint.py#L6-L39)

- The saver is LangGraph's `AsyncPostgresSaver`, opened on `DATABASE_URL` as an async context
  manager, with `await saver.setup()` creating its four tables the first time and checking them
  afterwards. The added dependency is pure Python and reuses the `psycopg` the project already had.
- The same database as the corpus, but not a retrieval path: the checkpointer writes only
  LangGraph's own tables, and the agent still reads documents through the MCP search tool, which a
  test enforces by failing on any import of the retrieval library.
- The serializer needs to be told about the types the state carries. A `SearchHit` the serializer
  does not recognize comes back as a plain dictionary, which fails later, inside the answer step,
  with an attribute error that says nothing about serialization. A test pins both halves: the
  project's serializer restores a `SearchHit`, and a strict serializer without the type restores a
  dictionary.
- The payload a pause carries is plain values only, because the process that resumes a run may have
  none of these classes loaded.

## Proving it survives a process

Why it matters: a test with two savers in one process would pass even if the state never left
memory. Proving durability needs a second process, which is what this test does.

??? example "pause"

    ```python
    pending = asyncio.run(pause())
    finished = resume_in_child_process(THREAD, checkpoint_database_url, APPROVE)

    assert finished["hit_types"] == ["SearchHit"]
    assert finished["searched"] == []
    ```

Source: [`services/api/tests/test_checkpoint.py:220-236`](https://github.com/sid-ak/study_assistant/blob/d42f445/services/api/tests/test_checkpoint.py#L220-L236)

An in-process test with two savers would pass even if the state never left memory, so the
integration test runs a second Python process. The child is given a search client that knows no
answers and reports every query it made, so a cited answer can only have come from the saved state,
and a hidden second search would show up as a non-empty list. It also reports the class names of
the hits it restored, which is what pins the serializer's behavior through a real round trip.

## Python used

Why it matters: these are the language features this stage leans on, listed so the page can be
read as Python practice as well as design.

| Feature | Where it appears | What it does here |
| ------- | ---------------- | ----------------- |
| `AsyncExitStack` | `open_agent` | Opens the MCP server always and the saver only when a run can pause, closing both in reverse |
| `@asynccontextmanager` | `postgres_checkpointer`, `open_agent` | Turns a setup-and-teardown pair into one `async with` |
| Union return type | `AgentOutcome = AgentAnswer \| PendingReview` | One call can finish or pause, and the caller must handle both |
| `isinstance` narrowing | `print_outcome` | Picks the printer for whichever of the two came back |
| `TypedDict` channels | `AgentState.approved` | A state key the graph will merge; an undeclared key is dropped |
| `subprocess.run` | The new-process test | Runs the child with the parent's whole environment and reads its JSON |
| `uuid4().hex` | `study-ask --review` | Names a paused run when the caller gives no name |

## Design trade-offs

Why it matters: each row is a decision that could have gone the other way, with the record that
settled it and the alternative it rejected.

| Decision | Chosen | Rejected alternative | Record |
| -------- | ------ | -------------------- | ------ |
| Where the pause sits | After the relevance grade, before the answer | After the answer, which pays for the generation first | Issue #70 |
| Graph shape | One graph, a setting decides whether the step pauses | A second graph built only for approval | Pull request #76 |
| Cost of a rejection | One of the run's two searches | A free rejection, which lets a person loop forever | Pull request #76 |
| Where paused runs live | Postgres, through LangGraph's saver | In-memory, which cannot outlive the process | Issue #70 |
| Connection string | The existing `DATABASE_URL` | A separate setting for checkpoints | Pull request #76 |
| What a pause shows | Document, section, and the relevance each was ranked by | The full passages, too long to read | Pull request #76 |

## Measured results

Why it matters: these are the numbers this stage produced, and they are what any claim about it
rests on.

The checkpoint adds no retrieval and no model request, so the retrieval and agent numbers from
Chunks 2 to 5 are unchanged: Recall@5 0.95 and MRR 0.83 reranked, grounding 1.00, citation recall
0.95. What it costs is one saved state per step and a run whose latency is now a person's.

The live flow against the dev corpus of 17 documents and 83 chunks, with reranking on:

| Step | Result |
| ---- | ------ |
| `study-ask "Which Bazel flag runs tests under AddressSanitizer?" --review` | Paused with 5 sources, top relevance 0.821, and a thread id |
| The `checkpoints` table for that thread | 4 rows |
| `study-ask --resume <thread-id> --approve`, a new process | "The flag is `--config=asan`.", citing Configs in .bazelrc |
| `--reject` on "What does error E1050 mean?" | Rewrote it to "E1050 error code" and paused again at the second search |
| `--approve` at that second checkpoint | The in-flight-limit answer, citing Orbit 5.0's New features |
| `--review` on "What is the capital of France?" | Never paused: nothing was relevant, so there was nothing to approve |

The relevance printed beside each source is the reranker's score. The same question with reranking
off prints 0.668 for a different top section, against 0.821 reranked, which is a value only
reranking produces.

## Interview questions

Why it matters: the questions this stage invites, with answers short enough to say out loud.

Why pause before generation rather than after?
: Before generation is the last moment where a person's decision can still change the outcome
  without wasting work. The evidence is on the table, the answer has not been paid for, and a
  rejection can still be acted on by searching again. After generation the cost is already spent
  and the only options are to accept or discard.

What does checkpointing actually add?
: Durability and inspectability. Each step's state is saved under a thread id, so a run can be
  resumed by another process or after a restart, read while it is in progress, and audited
  afterwards. Without it, a pause is only a pause inside one process's memory, which is no use when
  the wait is a person's.

How do you keep a human in the loop from making the agent unbounded?
: A rejection costs one of the run's searches, the same budget low relevance spends. Two searches
  means at most one rejection can be acted on; the next one ends the run with "insufficient
  context". The bound is the same one the agent already had, so a person cannot extend it.

What breaks when you save an agent's state to a database?
: Serialization. The state held dataclasses, and the serializer restores a type it does not
  recognize as a plain dictionary rather than raising, so the failure surfaces later in a step that
  expected the record. The fix is to register the state's types with the serializer and to pin it
  with a test that shows both outcomes. The payload a pause hands out is kept to plain values for
  the same reason: the process that resumes it may not have the classes.

How did you check the library's behavior rather than assuming it?
: With probes against the installed version, because the documentation is not versioned and one of
  the pages the issue pointed at had been removed. The probes settled how a pause is reported, how
  a decision is passed back, and what a saved state looks like, and they turned up the behavior
  that mattered most: resuming an unknown thread id silently starts a new run.

How do you test something that is supposed to survive the process?
: By using a second process. A test with two savers in one process cannot tell whether the state
  ever left memory. The child process is given a search client with no answers and made to report
  every query it ran, so a cited answer proves the state came from the database and no hidden
  search replaced it.
