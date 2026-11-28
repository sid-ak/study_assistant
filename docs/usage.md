# Usage guide and CLI reference

The study assistant is used through five console scripts. Two of them are the everyday tools:

- `study` loads a folder of markdown into the database and searches it.
- `study-ask` answers a question from what was loaded, citing the sections it used.

The other three measure the system or serve it to other programs:

- `study-eval` scores retrieval on the golden question set.
- `study-eval-agent` checks the agent's answers and citations on the same set.
- `study-mcp` exposes search as a Model Context Protocol (MCP) tool. `study-ask` starts it on its
  own, so it is rarely run by hand.

The first half of this page is the workflow, in the order the commands are used. The second half
is a reference for each command, the settings they read, and common failures. The design behind
the commands is in [the architecture](architecture.md), and the measured results are in
[the walkthrough](walkthrough.md).

## Setup

These steps run once per clone, from the repository root:

1. `uv sync`: installs every workspace package into one `.venv`.
2. `cp .env.example .env`: creates the settings file. To answer questions, set
   `GENERATION_API_KEY` to a key from the generation provider (Groq's free plan by default, see
   [ADR 0011](decisions/0011-free-hosted-generation.md)). Search works without a key.
3. `docker compose up -d`: starts PostgreSQL with pgvector. On macOS with Colima, `colima start`
   comes first.

Every command reads `.env` from the current folder, so every command runs from the repository
root. [Running from another folder](#running-from-another-folder) covers the alternative.

The first command that embeds text downloads the embedding and reranking models into fastembed's
cache. Later runs reuse them.

## Workflow

### Loading documents

```bash
uv run study ingest corpus/release_engineering
```

Ingestion reads every `*.md` file under the folder and its subfolders, splits each one at its
headings, embeds the pieces (chunks), and stores them. The first run on a new database also creates
the tables. Running it again only processes files whose content changed. Each file is identified by
its path relative to the folder, and that path is how sources are named in every later answer.

### Searching

```bash
uv run study query "Which Bazel flag turns on AddressSanitizer?"
```

Search prints the best-matching chunks with their scores and no generated answer. It is the
quickest way to check that a document was loaded and that a question finds it.

### Asking

```bash
uv run study-ask "Which Bazel flag turns on AddressSanitizer?"
```

The agent searches, checks that the best result is relevant enough, and either answers, rewrites
the question and searches once more, or reports that the documents do not answer it. The answer
lists the sections it is drawn from, and the model may only cite sections it was shown.

### Reviewing sources before answering

```bash
uv run study-ask "Which Bazel flag turns on AddressSanitizer?" --review
```

With `--review`, the run stops after searching and lists the sources it would answer from. It
prints a thread id and the two commands that continue it:

```bash
uv run study-ask --resume <thread-id> --approve
```

```bash
uv run study-ask --resume <thread-id> --reject
```

`--approve` answers from the listed sources. `--reject` rewrites the question, searches again, and
stops at the same checkpoint. A rejection with no searches left ends with "No answer". The paused
run is saved in the database, so the decision can come from another terminal or after a restart.

### Measuring

```bash
uv run study-eval dense-bge-small
```

```bash
uv run study-eval-agent agent-default
```

Both score the golden set in `evals/golden/questions.toml` against the release-engineering corpus,
and save the run under the given name in `evals/results/`. They need that corpus to be the one
loaded.

## A second corpus

Search and the agent look at every document stored in the database. To keep another set of notes apart from the release-engineering corpus, which the
evaluations depend on, load it into its own database.

1. Create the database and enable pgvector in it:

   ```bash
   docker compose exec -T db psql -U study -d postgres -c 'CREATE DATABASE study_notes'
   ```

   ```bash
   docker compose exec -T db psql -U study -d study_notes -c 'CREATE EXTENSION IF NOT EXISTS vector'
   ```

2. Point the commands at it for the current shell. A variable set in the environment takes
   precedence over `.env`:

   ```bash
   export DATABASE_URL=postgresql://study:change-me@localhost:5432/study_notes
   ```

3. Load the folder, then search or ask as usual:

   ```bash
   uv run study ingest ~/notes
   ```

`study-ask` passes `DATABASE_URL` on to the search server it starts, so the agent searches the same
database. `unset DATABASE_URL` returns the shell to the default database.

### Leaving out part of a folder

`study ingest` takes one folder and has no exclude option. To load a folder without one of its
subfolders, ingest a mirror of it that links to each wanted file. Source paths stay the same as in
the original, and edits to the original files are picked up on the next ingest. New files need the
mirror rebuilt. For example, the whole of `~/notes` except `~/notes/drafts`:

```bash
SRC=~/notes; DST=~/.cache/study_assistant/notes; rm -rf "$DST"; cd "$SRC" && find . -name '*.md' -not -path './drafts/*' | while read -r f; do mkdir -p "$DST/$(dirname "$f")"; ln -s "$SRC/${f#./}" "$DST/${f#./}"; done
```

### Running from another folder

Three things are resolved relative to the current folder:

- The `.env` file.
- The folder the agent starts the search server in.
- The cache of model replies, `.cache/generation`.

A command run from elsewhere would miss the settings and write its cache there. A small script on
the `PATH` can change to the repository first. This one is installed as `study`, with `study-ask`
linked to it, and picks the command by the name it was called by. It reads the database from
`STUDY_DATABASE_URL` and sets `DATABASE_URL` for that one command only, so commands run inside the
repository keep using `.env`:

```sh
#!/bin/sh
# Runs a study_assistant command from any folder, against the database in STUDY_DATABASE_URL.
command_name=$(basename "$0")
repo="$HOME/repos/study_assistant"

# A folder given to `study ingest` is made absolute before changing folder.
if [ "$command_name" = "study" ] && [ "$1" = "ingest" ] && [ -n "$2" ]; then
    folder=$(cd "$2" && pwd) || exit 2
    shift 2
    set -- ingest "$folder" "$@"
fi

cd "$repo" || exit 1
DATABASE_URL="${STUDY_DATABASE_URL:?Set STUDY_DATABASE_URL in the shell profile.}"
export DATABASE_URL
exec uv run --quiet "$command_name" "$@"
```

## Command reference

Every command is run as `uv run <command>` from the repository root, and every one accepts `-h` for
its help text. Exit status 0 means success, 2 means the arguments or settings could not be acted on,
and 1 means a service the command depends on failed.

### `study ingest`

```text
study ingest <folder>
```

| Argument | Meaning |
| --- | --- |
| `folder` | Folder whose `*.md` files are loaded, subfolders included. |

Prints one line per file added (`added <path>`), replaced (`replaced <path>`, the content changed),
or empty (`empty <path>`, no text). Files that are not valid UTF-8 are reported as `unreadable` on
standard error and skipped. The last line counts each kind and the chunks written. Exits 2 if
`folder` is not a folder.

Not reconciled:

- A file deleted from the folder stays in the database.
- A file moved to a new path with the same content keeps its old path.

### `study embed`

```text
study embed
```

Embeds every stored chunk that the model named by `EMBEDDING_MODEL` has no vector for yet, and
prints how many. Used after switching to a new embedding model, so the chunks already stored can
be searched with it. Each model has its own vector column
([ADR 0008](decisions/0008-per-model-embedding-columns.md)).

### `study query`

```text
study query <text> [--limit N] [--ef-search N]
```

| Argument | Meaning |
| --- | --- |
| `text` | The question or search text. |
| `--limit N` | How many chunks to show. Default 5. |
| `--ef-search N` | Candidate-list size for the HNSW index on this search, 1 to 1000. Larger is more thorough and slower. Default: the index's own. |

Each result is two lines:

```text
1. 0.7689  a34b707a-0d98-5e84-a17b-5570a0e6a84c  build_systems/bazel-basics.md > Bazel basics > Configs in .bazelrc
   Groups of options are named in the repository's `.bazelrc` and selected with `--config`. Orbit defin...
```

- The number after the rank is the relevance the ranking used: the reranker's score from 0 to 1
  when reranking is on (the default), otherwise the cosine similarity.
- Then the chunk id, the source path, and the heading path.
- The second line is the start of the chunk's text.

The last line gives the latency of embedding the question and searching (model loading excluded),
the embedding model, and whether results were reranked or fused with keyword search. Exits 2 if
the configured model was never registered. If it was registered but nothing is stored, it prints a
reminder to run `study ingest` and exits 0.

### `study-ask`

```text
study-ask <question> [--review [--thread-id ID]]
study-ask --resume <thread-id> (--approve | --reject)
```

| Argument | Meaning |
| --- | --- |
| `question` | The question to answer. |
| `--review` | Stop after searching and list the sources instead of answering. |
| `--thread-id ID` | Name for a run paused by `--review`. Default: a generated id. |
| `--resume ID` | Continue the paused run with this id. Needs `--approve` or `--reject`. |
| `--approve` | Answer from the paused run's sources. |
| `--reject` | Rewrite the question and search again, within the search limit. |

An answered question prints the answer, then `Sources:` with one numbered `document > section`
line per citation, then the number of searches and the text of each. A question the documents do
not answer prints `No answer: the documents found did not answer the question.` and still exits 0.

A paused run prints the searched text, each source with its relevance, the thread id, and the
approve and reject commands.

Exits 2 for:

- A question together with `--resume`.
- `--resume` without a decision.
- `--approve`, `--reject`, or `--thread-id` without the flag they belong to.
- `--review` or `--resume` with no `DATABASE_URL` set.

Exits 1 when the model, the search server, or the database holding paused runs fails.

### `study-eval`

```text
study-eval <name> [--golden FILE] [--corpus FOLDER] [--results FOLDER] [--k K] [--repeats N] [--ef-search N]
```

| Argument | Meaning |
| --- | --- |
| `name` | Name the run is saved under, for example `dense-bge-small`. |
| `--golden FILE` | Golden-set file. Default `evals/golden/questions.toml`. |
| `--corpus FOLDER` | Folder the corpus was loaded from, used to check that every label names a real heading. Default `corpus/release_engineering`. |
| `--results FOLDER` | Where runs are saved. Default `evals/results`. |
| `--k K` | Chunks retrieved per question. Default 5. |
| `--repeats N` | Timed searches per question, for the latency percentiles. Default 5. |
| `--ef-search N` | As for `study query`. |

Prints each question's recall and reciprocal rank, then Recall@k, MRR, and the p50 and p95
latency, then the path of the saved run. Every input is checked before any search runs, and a
problem exits 2.

### `study-eval-agent`

```text
study-eval-agent <name> [--golden FILE] [--corpus FOLDER] [--results FOLDER]
```

The arguments mean the same as for `study-eval`. Runs every golden question through the agent and
prints, per question, whether it was answered, whether every citation was a chunk the model was
shown (grounded), the citation recall, and the number of searches. The totals line gives the
grounding pass rate, the citation recall, the number answered, and the latency. Each question
costs model requests, so all inputs are checked before the first one. Exits 2 for bad input and 1
if the agent fails.

### `study-mcp`

```text
study-mcp
```

Runs the search server over standard input and output. It offers one tool, `search(query, limit)`,
with `limit` from 1 to 20 (default 5). Each hit carries the chunk id, document, heading path, text,
cosine distance, and relevance. `study-ask` and `study-eval-agent` start it themselves. It can also
be registered with any MCP client that starts servers over stdio, with the repository root as its
working folder.

## Settings

Settings come from environment variables or from `.env` in the current folder, and an environment
variable wins over the file. `.env.example` lists them with their defaults.

| Variable | Read by | Controls |
| --- | --- | --- |
| `DATABASE_URL` | all | The database documents are stored in and paused runs are saved in. |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` | all | The embedding model and its vector size ([ADR 0010](decisions/0010-lightweight-embedding-and-reranking-models.md)). |
| `EMBEDDING_QUERY_PREFIX` | all | Text put in front of every question before it is embedded. |
| `FASTEMBED_CACHE_PATH` | all | Where model files are downloaded. Default: a folder under the system temporary folder. |
| `RERANK_ENABLED`, `RERANKER_MODEL`, `RERANK_CANDIDATES` | all | Whether search results are reranked, by which model, and how many candidates it rescores. |
| `HYBRID_ENABLED` | all | Whether keyword search is fused with vector search before reranking. |
| `GENERATION_BASE_URL`, `GENERATION_MODEL`, `GENERATION_API_KEY` | `study-ask`, `study-eval-agent` | The OpenAI-compatible endpoint, model, and key answers come from. |
| `GENERATION_CACHE_DIR` | `study-ask`, `study-eval-agent` | Where model replies are cached, so a repeated request is free. |
| `AGENT_MAX_HOPS` | `study-ask`, `study-eval-agent` | Searches per question. Default 2. |
| `AGENT_RELEVANCE_THRESHOLD` | `study-ask`, `study-eval-agent` | The relevance the best search result needs for the agent to answer from it. Default 0.65. |
| `AGENT_SEARCH_LIMIT` | `study-ask`, `study-eval-agent` | Chunks per search. Default 5. |

The agent passes only the variables starting with `DATABASE_`, `EMBEDDING_`, `FASTEMBED_`,
`RERANK`, and `HYBRID_`, plus `TMPDIR`, to the search server it starts.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `connection refused` on port 5432 | The database is not running. Run `docker compose up -d`, after `colima start` on macOS with Colima. |
| `study query` exits with "nothing has been ingested" | No chunk has a vector from the configured model. Run `study ingest <folder>`, or `study embed` after changing `EMBEDDING_MODEL`. |
| Answers cite documents from the wrong corpus | `DATABASE_URL` points at another database. Check `echo $DATABASE_URL`; an exported value overrides `.env`. |
| `No answer` for a question the notes cover | The best result scored below `AGENT_RELEVANCE_THRESHOLD`. Run `study query` with the same question to see what was found and how it scored. |
| `study-ask` fails with a rate-limit error | The free generation plan allows a fixed number of tokens per minute. The client waits and retries; a failure after that means the limit is still exhausted, so wait a minute. |
| A warning about unauthenticated requests to the HF Hub | Printed when models are checked or downloaded. It does not affect results. |
