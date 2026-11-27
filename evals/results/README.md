# Saved evaluation runs

Each run is one JSON file written by `uv run study-eval <name>`. It holds the settings, every
question's retrieved sections with their distances, and the totals below. All runs use the ten
questions in `../golden/questions.toml` over `corpus/release_engineering/` (17 documents, 83
chunks), with `k = 5` and 5 timed retrievals per question.

| Run | Embedding model | Recall@5 | MRR | p50 latency | p95 latency |
| --- | --- | --- | --- | --- | --- |
| `dense-bge-small` | `BAAI/bge-small-en-v1.5`, 384 dimensions | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| `dense-bge-base` | `BAAI/bge-base-en-v1.5`, 768 dimensions | 0.90 | 0.85 | 42.1 ms | 56.1 ms |
| `dense-bge-small-rerank` | `BAAI/bge-small-en-v1.5`, reranked by `jina-reranker-v1-tiny-en` from 20 candidates | 0.95 | 0.83 | 283.1 ms | 417.5 ms |
| `hybrid-bge-small-rerank` | `BAAI/bge-small-en-v1.5` and full-text search fused by RRF, reranked from 20 candidates | 0.95 | 0.83 | 330.3 ms | 451.4 ms |

Latency covers embedding the query and the database search, on an Apple M1 with 8 GB of memory and
Postgres in Docker. It varies by several milliseconds between runs of the same configuration, so
small latency differences between runs are noise.

Reproduced on 2026-11-27 from a fresh clone with an empty database, following the README: the
default configuration (dense, reranked) scored the same Recall@5 of 0.95 and MRR of 0.83, at a p50
of 267 ms, and the agent scored the same grounding of 1.00 and citation recall of 0.95 over all ten
questions. Those two runs were not saved here, because they repeat `dense-bge-small-rerank` and
`agent-qwen3.8-27b-rerank` rather than record a new configuration.

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
| `agent-qwen3.8-27b-rerank` | `qwen/qwen3.8-27b` on Groq, search reranked | 10 of 10 | 1.00 | 0.95 | 1.0 s | 12.3 s |

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

## Reranking

`dense-bge-small-rerank` repeats the dense baseline with reranking on: dense search fetches 20
candidates and `jina-reranker-v1-tiny-en` rescores them and keeps the top five.
`agent-qwen3.8-27b-rerank` repeats the agent run the same way, with the agent grading on the
reranker's score.

- Recall@5 rises from 0.90 to 0.95. `cmake-minimum-5-0` now finds both labeled sections, with
  Orbit 5.0's Breaking changes first, where dense search ranked Orbit 4.0's first and missed 5.0's.
  `error-e1050` moves from third to first.
- MRR falls from 0.88 to 0.83. For `linker-out-of-memory` the write-up's Cause, which explains the
  out-of-memory kill, ranks above its Fix, which limits parallel links. For
  `workers-flag-replacement` Orbit 5.0's Upgrade notes, which name `--orbit-workers` but not its
  replacement, rank above its Breaking changes. In both, the reranker prefers a section of the right
  document that is about the question's subject over the one that answers it.
- `remote-cache-outage` still finds only the Bazel guide's section. The CI write-up's Cause section
  is among the 20 dense candidates (ninth), and the reranker scores the write-up's title, Symptom,
  and Fix sections above it, so it stays outside the top five.
- Latency rises from a 26.0 ms to a 283.1 ms median, and from 41.6 ms to 417.5 ms at p95: scoring 20
  query and passage pairs costs about 255 ms on this machine. The model adds 3.7 s to load and
  324 MB of memory, once per process.
- In the agent run, citation recall rises from 0.90 to 0.95, with `cmake-minimum-5-0` now citing
  both sections, and every answer stays grounded. The median per question stays about 1 s, since
  generation dominates. One question again took over 9 s; the adapter does not log rate-limit
  waits, so the cause is not known.
- The reranker separates answerable from off-topic questions far more clearly than dense
  similarity: the golden questions' top hits score 0.821 to 0.948 and off-topic questions at most
  0.489, against 0.668 to 0.884 and up to 0.64 by cosine similarity.

Reranking is therefore on by default (`RERANK_ENABLED`). It buys recall, citation recall, and a
reliable relevance grade, for about a quarter of a second per search.

## Hybrid retrieval

`hybrid-bge-small-rerank` adds Postgres full-text search beside dense search: each fetches 20
candidates, Reciprocal Rank Fusion merges the two lists, and the reranker keeps the top five.

| Run | Recall@5 | MRR | p50 latency | p95 latency |
| --- | --- | --- | --- | --- |
| `dense-bge-small` | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| `dense-bge-small-rerank` | 0.95 | 0.83 | 283.1 ms | 417.5 ms |
| `hybrid-bge-small-rerank` | 0.95 | 0.83 | 330.3 ms | 451.4 ms |

- Same scores as reranked dense search: every labeled section is found at the same rank for every
  question. The only retrieved section that changes is an unlabeled fifth result for
  `linker-out-of-memory` (the no-space write-up's Symptom gives way to the sanitizer guide's
  overview). The cost is about 47 ms more at the median, for the second search and the fusion.
- Why no gain: the reranker can only choose among the candidates, and on this corpus the 20 dense
  candidates already hold every section hybrid search would add. For "What does error E1050 mean?"
  and the bare query `E1050`, the defining section is third and fifth among the dense candidates,
  and the reranker moves it to first with or without hybrid search. Twenty candidates cover about a
  quarter of the 83 chunks.
- Where hybrid search does help: with reranking off, the bare query `E1050` misses its defining
  section in the dense top three and finds it second with hybrid search. Its fused relevance of
  exactly 1/61 shows lexical search alone ranked it.
- The remaining miss, `remote-cache-outage`, is unchanged: its second section is a candidate in
  both modes, and the reranker keeps it outside the top five.

Hybrid search therefore stays off by default (`HYBRID_ENABLED`). Its benefit should grow with the
corpus, once an answer can fall outside the dense candidates, so the run is worth repeating on a
larger collection. No agent run was made with hybrid search: nine questions retrieve exactly the
same five sections as the reranked agent run, so their prompts would repeat ones already answered,
and the tenth differs only in an unlabeled fifth section.

