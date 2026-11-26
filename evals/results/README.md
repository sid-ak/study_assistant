# Saved evaluation runs

Each run is one JSON file written by `uv run study-eval <name>`. It holds the settings, every
question's retrieved sections with their distances, and the totals below. All runs use the ten
questions in `../golden/questions.toml` over `corpus/release_engineering/` (17 documents, 83
chunks), with `k = 5` and 5 timed retrievals per question.

| Run | Embedding model | Recall@5 | MRR | p50 latency | p95 latency |
| --- | --- | --- | --- | --- | --- |
| `dense-bge-small` | `BAAI/bge-small-en-v1.5`, 384 dimensions | 0.90 | 0.88 | 26.0 ms | 41.6 ms |

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
