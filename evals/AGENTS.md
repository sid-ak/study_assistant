# evals — Agent Context

`evals` is the golden-set evaluation harness. It measures how well retrieval finds the sections
that answer a fixed set of questions, and how long it takes, so every later change to retrieval is
measured against the same baseline. See the root [`AGENTS.md`](../AGENTS.md) for project-wide
context and [`docs/architecture.md`](../docs/architecture.md) for where it sits. The ADRs that bind
it are the local retrieval stack with an owned eval loop (0002, models in 0010) and the MVP corpus
(0009).

## Layout

- `golden/questions.toml`: the golden set, ten questions over `corpus/release_engineering/`.
- `results/`: saved runs, one file per run, kept in git so runs can be compared across changes.
- `src/evals/`: the harness.
  - `golden.py`: the golden-set format, its loader, and `check_labels`, which confirms every
    label names a heading that a chunk can carry.
  - `metrics.py`: label matching, recall, reciprocal rank, and nearest-rank percentiles.
  - `runner.py`: `run_eval`, which retrieves and scores every question, and `write_run`.
  - `main.py`: the `study-eval` console script, and the input checks both commands share.
  - `agent.py`: `run_agent_eval`, which runs the golden set through the agent and checks its
    citations.
  - `agent_main.py`: the `study-eval-agent` console script.
- `tests/`: unit tests, run by the root `pytest`.

## Conventions

- A consumer of `rag_core` and `api`, never a reimplementer. Retrieval evaluation calls the same
  `retrieve` the CLI and the MCP server use, and agent evaluation runs the same graph `study-ask`
  runs, so each measures the real path.
- Labels name a document and a section heading, never a chunk id. A chunk counts as a match when it
  comes from the labeled document and lies inside the labeled section, so labels survive
  re-chunking and re-embedding. `document` is the path relative to the ingested folder
  (`corpus/release_engineering/`), as ingestion records it in each chunk's `source`.
- The loader rejects anything it does not understand, including unknown keys, and a unit test runs
  `check_labels` over the committed golden set and corpus. A typo in a label, or a corpus edit that
  renames a heading, fails CI instead of silently never matching.
- A question lists every section that answers it, so one answer spread over two documents, for
  example a release note and a CI write-up, is two labels.

## Running an evaluation

`uv run study-eval <name>` scores the golden set against the ingested corpus with the configured
embedding model and saves the run as `evals/results/<name>.json`. It needs the database and an
ingested corpus (`uv run study ingest corpus/release_engineering`).

- Metrics: Recall@k is the share of a question's labeled sections found in its top `k` chunks,
  averaged over questions. MRR averages one over the rank of the first matching chunk. Latency is
  the p50 and p95, by nearest rank, over `repeats` timed retrievals per question, each covering
  query embedding and search. One untimed retrieval first absorbs the model load.
- Inputs are checked before any retrieval: a taken run name, a malformed golden set, a label that
  names no heading, or a model with stored chunks it has no vector for exits with status 2. The
  last would otherwise save a run that scores those chunks as misses.
- Saved runs are never overwritten. A new measurement gets a new name.

## Evaluating the agent

`uv run study-eval-agent <name>` runs every golden question through the agent (the MCP server over
stdio and the configured generation model) and saves the run beside the retrieval runs. It spends
free-plan quota, about one or two model requests per question; cached replies make an unchanged
rerun free.

- Grounding: an answered question is grounded when it cites at least one chunk and every cited id
  was in the context the model was shown. The pass rate is over answered questions only, and is
  `null` when nothing was answered.
- Citation recall: the share of a question's labeled sections that a cited chunk lies in, averaged
  over all questions, with an unanswered question counting as 0. Grounding says the citations are
  real; citation recall says they point at the right place.
- The agent run is passed to `run_agent_eval` as an async function from question to answer, so
  tests use prepared answers and need no model, server, or database.

