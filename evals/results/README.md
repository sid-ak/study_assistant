# Saved evaluation runs

Each run is one JSON file written by `uv run study-eval <name>`. It holds the settings, every
question's retrieved sections with their distances, and the totals below. All runs use the ten
questions in `../golden/questions.toml` over `corpus/release_engineering/` (17 documents, 83
chunks), with `k = 5` and 5 timed retrievals per question.

| Run | Embedding model | Recall@5 | MRR | p50 latency | p95 latency |
| --- | --- | --- | --- | --- | --- |
| `dense-bge-small` | `BAAI/bge-small-en-v1.5`, 384 dimensions | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| `dense-bge-base` | `BAAI/bge-base-en-v1.5`, 768 dimensions | 0.90 | 0.85 | 42.1 ms | 56.1 ms |

Latency covers embedding the query and the database search, on an Apple M1 with 8 GB of memory and
Postgres in Docker. It varies by several milliseconds between runs of the same configuration, so
small latency differences between runs are noise.

## Dense baseline

`dense-bge-small` is dense retrieval with the default embedder and the HNSW index's default
`ef_search` of 40. Seven questions found every labeled section, with a matching chunk ranked first.
The other three:

- `error-e1050`, an exact error code: the defining section, Orbit 5.0's New features, ranked
  third, behind two Fixed issues sections that list other error codes. The model's tokenizer
  splits `E1050` into `e`, `##10`, and `##50`, and `E1013` into `e`, `##10`, and `##13`, so the
  codes share most of their input to the model.
- `cmake-minimum-5-0`: Orbit 4.0's Breaking changes ranked first, ahead of the CI write-up about
  the 5.0 upgrade, and Orbit 5.0's own Breaking changes did not reach the top 5. Both release
  notes state a CMake minimum, and as model input "Orbit 5.0" and "Orbit 4.0" differ in a
  single token.
- `remote-cache-outage`: the Bazel guide's section ranked first, but the CI write-up's Cause
  section did not reach the top 5. The write-up's title chunk and other sections filled those
  places instead.

## Embedding model comparison

`dense-bge-base` repeats the baseline with `bge-base-en-v1.5`, registered beside the default model
and given vectors for the same 83 chunks with `study embed`. Only the embedding model differs.

- Recall@5 is the same, 0.90. Both models find exactly the same labeled sections for every
  question, and miss the same two.
- MRR moves within the noise of ten questions. `bge-base` ranks the first matching chunk higher for
  `error-e1050` (second instead of third) and `cmake-minimum-5-0` (first instead of second), and
  lower for `linker-out-of-memory` and `openssl-homebrew` (second instead of first, behind another
  section of the same CI write-up).
- Median latency is 16 ms higher. ADR 0010's probe measured query embedding at 12 ms for
  `bge-base-en-v1.5` against 4 ms for `bge-small-en-v1.5`, which accounts for most of the gap.

`bge-small-en-v1.5` therefore stays the default embedder. On this golden set the larger model
buys no recall, and its cost is a slower query, twice the vector storage (768 dimensions against
384), and about twice the memory to load (a 1,233 MB peak against 621 MB in ADR 0010's probe).

## Agent runs

Agent runs send each golden question through the full agent: searches through the MCP server and
requests to the generation model. Each question is asked once.

| Run | Generation model | Answered | Grounding pass rate | Citation recall | p50 latency | p95 latency |
| --- | --- | --- | --- | --- | --- | --- |
| `agent-qwen3.8-27b` | `qwen/qwen3.8-27b` on Groq | 10 of 10 | 1.00 | 0.90 | 1.0 s | 9.7 s |

- Every answer cites only chunks it was shown, as the answer schema's `enum` of context ids
  requires, and no answer text contains a chunk id.
- All ten were answered from the first search; no question needed a rewrite.
- Citation recall misses are the two multi-document questions, `remote-cache-outage` and
  `cmake-minimum-5-0`, each citing one of its two labeled sections. In both, the uncited section
  was not among the five chunks retrieval returned, so the model never saw it: the misses come from
  retrieval, not generation.
- For `cmake-minimum-5-0`, retrieval ranked Orbit 4.0's breaking changes first, and the answer
  still cited the CI write-up about the 5.0 upgrade and gave the correct version, 3.28.
- One question took 9.7 s against about 1 s for the rest. The adapter does not log rate-limit
  waits, so whether that was a wait on the per-minute token budget or a slow reply is not known.

