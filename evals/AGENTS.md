# evals — Agent Context

`evals` is the golden-set evaluation harness. It measures how well retrieval finds the sections
that answer a fixed set of questions, and how long it takes, so every later change to retrieval is
measured against the same baseline. See the root [`AGENTS.md`](../AGENTS.md) for project-wide
context and [`docs/architecture.md`](../docs/architecture.md) for where it sits. The ADRs that bind
it are the local retrieval stack with an owned eval loop (0002, models in 0010) and the MVP corpus
(0009).

## Layout

- `golden/`: the golden set, as TOML.
- `results/`: saved runs, one file per run, kept in git so runs can be compared across changes.
- `src/evals/`: the harness.
  - `golden.py`: the golden-set format and its loader.
- `tests/`: unit tests, run by the root `pytest`.

## Conventions

- A consumer of `rag_core`, never a reimplementer. Evaluation calls the same retrieval entry point
  the CLI and the agent use, so a run measures the real path.
- Labels name a document and a section heading, never a chunk id. A chunk counts as a match when it
  comes from the labeled document and lies inside the labeled section, so labels survive
  re-chunking and re-embedding. `document` is the path relative to the ingested folder
  (`corpus/release_engineering/`), as ingestion records it in each chunk's `source`.
- The loader rejects anything it does not understand, including unknown keys, so a typo in a label
  fails loudly instead of silently never matching.
