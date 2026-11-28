# 07. Code Freeze and Walkthrough

> Part of the [Project](README.md) section of [AI, RAG & Python](../README.md). Built in
> [study_assistant#50](https://github.com/sid-ak/study_assistant/issues/50), pull request
> [study_assistant#77](https://github.com/sid-ak/study_assistant/pull/77).

Chunk 7 built nothing. It froze the code, took a fresh clone through the README, checked every
document against the code, and wrote the walkthrough. The value of the exercise is what it caught:
a setup instruction that only worked by accident of where the repository happened to sit, and a
decision record that described a graph the code no longer had.

| Step | What it checks |
| ---- | -------------- |
| The full gate | Lint, format, types, unit and integration tests, and a strict docs build |
| A fresh clone | That the README is sufficient, not just familiar |
| The directory audit | That the architecture's tree matches what exists |
| The record audit | That each decision record still describes the code |
| The walkthrough | That the whole system can be explained with its measurements |

## What the fresh clone caught

Why it matters: a project that only runs on the machine it was built on is not finished. Cloning
it somewhere clean is the cheapest way to find what the working copy was hiding.

A clone of the branch, its own `.env`, its own empty database, nothing shared with the working copy
except the downloaded models. Every README step ran, and one of them failed for a reason no test
could have found.

```text
db-1 | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/init.sql
db-1 | psql: error: could not read from input file: Is a directory
```

- The cause: `docker compose up -d` bind-mounts `infra/postgres/init.sql`, the script that creates
  the pgvector extension and the separate test database. The clone was in a folder the container
  runtime does not share with its virtual machine, so Docker created an empty directory at the
  mount point instead of passing the file through.
- The symptom: 114 integration tests failing to connect, with nothing in the message about a mount.
  The test database simply did not exist.
- The fix: the README's prerequisite now says where a clone has to live. The second clone, inside
  the shared path, ran the whole README with no change to any code.

This is the class of bug a fresh clone exists to find. Nothing about it is visible from a working
copy that was set up months earlier, and no unit test can see it, because the failure is in the
environment the tests assume.

## What the record audit caught

Why it matters: a design record that no longer matches the code is worse than no record, because
it will be quoted in good faith. The audit is what keeps the written history trustworthy.

Thirteen decision records, each checked against the code rather than against memory. Twelve held.
The one that did not had been written by the chunk that anticipated the feature:

> Checkpointing: the graph compiles with an optional checkpointer, none by default, so a later
> stage can pause a run without changing the graph.

The checkpointer needed no change, and the sentence was still half wrong: a pause is a step, so the
graph gained a node. The record was amended with the current diagram and the checkpoint's own
decisions rather than superseded, because the checkpoint changes the shape of the same decision, the
agent's state machine.

The directory tree in the architecture document had drifted in both directions. It listed a web
application, API routes, Dockerfiles, and document parsers that do not exist yet, and omitted files
that do: the cheat sheet, the root test configuration, the probe scripts, two of the three
workflows, and the generation lane's command-line entry point. The tree is now marked as the target
layout, with every unbuilt entry marked as a later phase.

One tension was recorded rather than fixed. The retrieval-boundary record expects the backend to use
the retrieval library directly for administration, while the generation lane forbids importing it at
all, enforced by a test. Nothing conflicts today, because the lane has no administrative surface.
The record now says what has to give when it does: either the endpoints sit outside the lane the
test guards, or the test narrows to the agent's own modules.

## The whole system, measured

Why it matters: every number the project can defend, in one place, so a claim can be checked
against the run it came from rather than from memory.

Everything the seven chunks produced, in one table. Ten golden questions over 17 documents and 83
chunks, on an Apple M1 with 8 GB of memory.

| Configuration | Recall@5 | MRR | p50 | p95 |
| ------------- | -------- | --- | --- | --- |
| Dense, `bge-small-en-v1.5` | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| Dense, `bge-base-en-v1.5` | 0.90 | 0.85 | 42.1 ms | 56.1 ms |
| Dense, reranked (the default) | 0.95 | 0.83 | 283.1 ms | 417.5 ms |
| Hybrid, reranked | 0.95 | 0.83 | 330.3 ms | 451.4 ms |

| Agent run | Answered | Grounding | Citation recall | p50 | p95 |
| --------- | -------- | --------- | --------------- | --- | --- |
| Dense | 10/10 | 1.00 | 0.90 | 1003 ms | 9709 ms |
| Reranked | 10/10 | 1.00 | 0.95 | 1026 ms | 12252 ms |

The fresh clone reproduced the default configuration at Recall@5 0.95, MRR 0.83, and a p50 of
267 ms, and the agent at grounding 1.00 and citation recall 0.95. Matching numbers from an empty
database are what make the saved runs evidence rather than anecdote.

## Presenting it

Why it matters: the work only counts if it can be explained in the time available, in the order
that makes the measurements land.

The project's own order is the wrong order to present it in. What a listener needs first is the
shape of the system and the one measurement that justifies each part.

- The system in three sentences: markdown documents are split at their headings, embedded, and
  stored in Postgres with pgvector; a question is answered by a bounded LangGraph agent that
  reaches retrieval only through an MCP tool and returns an answer citing the chunks it was shown;
  every change is measured against ten questions labeled by document and section.
- Each part with its number: reranking, Recall@5 0.90 to 0.95 for 255 ms; hybrid search, no change
  on this corpus and off by default, with the reason; the bounded agent, two searches and two model
  requests as the known worst case, grounding 1.00; the checkpoint, no retrieval cost, one saved
  state per step.
- The negative results are the strongest material. A larger embedding model that found nothing more
  and a hybrid mode that changed no ranking are both decisions backed by a measurement, and both
  shipped as the cheaper option.
- The mistake worth telling: an agent run saved as "reranked" when the setting had never reached the
  separate server process. An impossible latency gave it away, and the rule that came out of it is
  to prove a mode ran by a value only that mode produces, before quoting any number.

## Interview questions

Why it matters: the questions this stage invites, with answers short enough to say out loud.

What does a code freeze accomplish that CI does not?
: CI runs in an environment the repository already controls, from a checkout it already trusts. A
  fresh clone tests the instructions, which is the part no test covers. The real failure here was a
  bind mount that only worked where the repository happened to sit, and it surfaced as 114
  connection errors with no mention of a mount.

How do you keep documentation honest as code changes?
: By checking each claim against the code at a fixed point and recording the drift rather than
  quietly fixing the text. Of thirteen decision records, one described a graph the code no longer
  had; it was amended with the current diagram and the reason the original sentence was wrong. The
  directory tree had drifted both ways, so it is now labeled as the target layout with unbuilt
  entries marked.

Which result would you present first, and why?
: Reranking, because it is the clearest trade: Recall@5 from 0.90 to 0.95 and the agent's citation
  recall from 0.90 to 0.95, for about 255 ms per search. It shows a measured gain, a measured cost,
  and a default chosen from both. Hybrid search comes next, as the opposite case: built, measured,
  no gain on this corpus, and shipped off with the reason recorded.

What would you do next on this project?
: Measure hybrid search on a corpus large enough that an answer can fall outside the dense
  candidates, which is the only place it should help, and record the query prefix, chunk size, and
  commit in each saved run so two runs can be compared without trusting the file name. After that,
  remembering which sources a person rejected, so a rewritten query is not free to return them
  again.
