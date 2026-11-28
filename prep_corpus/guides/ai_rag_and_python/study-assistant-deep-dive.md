# Study Assistant: deep dive answers for the DriveOS interview

> Part of [AI, RAG & Python](README.md)

## The numbers, from `evals/results/`

| Run | Recall@5 | MRR | p50 | p95 |
| --- | --- | --- | --- | --- |
| Dense, `bge-small` (real) | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| Dense, `bge-base` (real) | 0.90 | 0.85 | 42.1 ms | 56.1 ms |
| Dense + rerank | 0.95 | 0.83 | 283.1 ms | 417.5 ms |
| Hybrid (RRF) + rerank | 0.95 | 0.83 | 330.3 ms | 451.4 ms |

The agent numbers, from `agent-qwen3.8-27b` and `agent-qwen3.8-27b-rerank`:

| Run | Grounding | Citation recall | p50 | p95 |
| --- | --- | --- | --- | --- |
| Agent, dense | 1.00 | 0.90 | 1.0 s | 9.7 s |
| Agent, dense + rerank | 1.00 | 0.95 | 1.0 s | 12.3 s |

And the three single figures worth having ready:

- `error-e1050` ranks first under dense + rerank and under hybrid + rerank alike. Reranking is what moved it, not hybrid search.
- The agent used exactly 1.0 hops on average: all ten questions were answered from the first search in both runs, so the rewrite path never fired.
- Tokens per golden-set generation pass is not known. The adapter never reads `usage` off the response, so ADR 0011's estimate of 40K to 80K stands unmeasured. Say that rather than quoting the estimate as a result.

## Overview

### Pitch

> My project is an agentic RAG system, retrieval-augmented generation, over release engineering documentation: build guides, release notes, and CI failure write-ups. It's built for the question a release engineer asks all the time: "I've seen this failure before, what fixed it?" That question comes from my time on build and CI tooling for a safety-relevant ADAS stack. Failures downstream were often confusing, and the cause turned out to be something that had drifted out of sync upstream, so engineers spent time rediscovering things instead of fixing them. Working there also taught me not to ask anyone to trust a tool's output: the tools I built had to prove they were right, or the build failed. So I held this project to the same rule: every part of it had to prove it was helping.
>
> It has three pieces. First, the retrieval pipeline: documents are chunked by section and embedded into pgvector in Postgres, so a query pulls back the most relevant chunks. Second, an agent built in LangGraph, which reaches that search only through an MCP tool and writes an answer with citations. And third, an evaluation harness: ten questions where I know exactly which document sections hold the answer, so I can score any version of the system.
>
> What sets it apart from most RAG projects is the order I built it in, and the limits I put on it. I wrote the evaluation harness before the agent, so every component had to beat a measured baseline to stay in. For example, I tried BGE-base, a larger embedding model, against my default BGE-small, and it found exactly the same sections while making every query 16 milliseconds slower, so it didn't ship. The Jina tiny cross-encoder reranker did beat the baseline, so it did. And the agent is bounded on purpose. It searches at most twice, it can only cite sections it was actually shown, and it can pause before answering so a person approves its sources. That pause is saved in Postgres, so the approval can come hours later, from another process.
>
> Measuring first taught me things I wouldn't have guessed. Dense retrieval was already good, but it ranked an exact error code only third, because the tokenizer splits codes like E1050 and E1013 into nearly the same pieces. A bigger embedding model didn't fix that; it only made queries slower. A cross-encoder reranker did fix it. And hybrid search with BM25-style keyword matching, which I expected to be the answer for error codes, changed nothing here, because the reranker's candidates already held everything the keyword side would have added.
>
> So each change got its own verdict. The small embedding model stays. The reranker is on by default, because it took recall from 0.90 to 0.95 for about a quarter of a second. Hybrid search is built and measured, but switched off until the corpus grows. And the agent answered all ten questions with every citation grounded. That's the shape I'd want in a release pipeline: measured, bounded, and approved by a person before anything final.

### Short Pitch

> I built an agentic RAG system over release engineering docs, for the question "I've seen this failure before, what fixed it?" I wrote the evaluation harness before the agent, so every component had to beat a measured baseline. A reranker earned its place and a bigger embedding model and hybrid search didn't. The agent searches at most twice, can only cite what it was shown, and can pause for a person to approve its sources. Measured, bounded, and gated by a person.

## Hybrid retrieval: BM25-style and RRF

**What's built.** Each chunk has a generated `tsvector` column with a GIN index. A lexical query on `StoreProtocol` ranks chunks with `ts_rank`. Dense and lexical lists are fused with Reciprocal Rank Fusion inside `rag_core.retrieve`, between search and reranking, behind a setting so runs can be dense-only or hybrid.

**Result.** Hybrid + rerank scored Recall@5 0.95 and MRR 0.83, which is exactly what reranked dense search scored, for about 47 ms more at the median. Every labeled section came back at the same rank for every question; the only result that changed at all was an unlabeled fifth hit on `linker-out-of-memory`.

So hybrid search stays off by default (`HYBRID_ENABLED`), and the interesting part is why it bought nothing. The reranker can only choose among the candidates it is given, and at 83 chunks the 20 dense candidates already contain every section hybrid search would have added. Twenty candidates are about a quarter of the whole corpus.

Where it does help is with reranking off: the bare query `E1050` misses its defining section in the dense top three and finds it second with hybrid search, at a fused relevance of exactly 1/61, which shows lexical search alone ranked it. That is the result to lead with, because it is the mechanism working in isolation.

Of the two two-document misses, `cmake-minimum-5-0` is fixed, by the reranker. `remote-cache-outage` is still partial in every configuration.

**Likely follow-ups**

- *Why hybrid?* Dense and lexical fail differently. Dense handles paraphrase ("runs out of memory while linking" finds the exit code 137 write-up). Lexical handles exact identifiers: error codes, flags like `--config=asan`, symbols like `pthread_create`. Release text is full of identifiers. `bge-small` tokenizes `E1050` as `e ##10 ##50` and `E1013` as `e ##10 ##13`, so the two codes look nearly identical to it. That miss was measured before hybrid existed.
- *How does RRF work?* For each chunk, sum `1 / (k + rank)` over every list it appears in, with `k = 60` by convention. It uses only rank positions, so a cosine distance and a `ts_rank` score never have to be put on the same scale. A larger `k` flattens the advantage of being ranked first.
- *Why not a weighted sum of scores?* The two scores have different, query-dependent scales, so you'd need per-query normalization plus a tuned weight. RRF has one parameter and works without tuning, which matters when a 10-question golden set can't justify tuning more than that.
- *How deep is each list before fusion?* 20 per list, fused to 20, reranked down to 5. Fusion can't bring back a chunk that neither list returned, so depth sets the recall ceiling for the reranker.
- *Is `ts_rank` really BM25?* No, and say so first. `ts_rank` weighs term frequency (`ts_rank_cd` adds proximity) but has no inverse document frequency and no BM25 document-length saturation. It's BM25-style. Real BM25 in Postgres needs an extension such as ParadeDB's `pg_search`, or scoring in the app. At 83 chunks the gap is small, and the code documents it as an approximation (#12).
- *Did the contract tests change?* Yes. The in-memory fake's lexical scorer and `ts_rank` rank differently, so the tests check which chunks come back, not their order.
- *Where does RRF hurt?* A chunk that one list ranks first and the other misses can lose to a chunk both lists rank in the middle. On this golden set no question got worse: no labeled section changed rank under hybrid search, so the fusion neither helped nor hurt.

**DriveOS bridge.** Build and regression logs are full of identifiers: error codes, test names, file paths. An assistant that searches past failures needs exact-match retrieval, not only semantic similarity.

## Cross-encoder reranking

**What's built.** A `Reranker` protocol, a fastembed implementation of `jina-reranker-v1-tiny-en` with lazy loading, and a fake in `rag_core_testing`. It reranks the top 20 candidates, as its own step after search, behind a setting.

**Result.** Dense against dense + rerank: Recall@5 rose 0.90 → 0.95, MRR fell 0.88 → 0.83, p50 rose 26.0 → 283.1 ms and p95 41.6 → 417.5 ms. Scoring 20 query and passage pairs costs about 255 ms on this machine, and the model costs 3.7 s to load and 324 MB of memory, once per process.

Lead with the fact that recall went up and MRR went down, and then explain it, because the explanation is specific:

- The recall win is `cmake-minimum-5-0`, which now finds both of its labeled sections with Orbit 5.0's Breaking changes first, where dense search had ranked 4.0's first and missed 5.0's. `error-e1050` moved from third to first.
- The MRR loss is two questions where the reranker prefers a section that is about the question's subject over the section that answers it. On `linker-out-of-memory` the write-up's Cause outranks its Fix; on `workers-flag-replacement` Orbit 5.0's Upgrade notes, which name `--orbit-workers` but not its replacement, outrank its Breaking changes.
- `remote-cache-outage` is the one question reranking makes worse in a way that matters. Its second labeled section is the ninth of the 20 dense candidates, and the reranker scores three other sections of the same write-up above it, so it falls out of the top five.

**Likely follow-ups**

- *Bi-encoder vs cross-encoder?* A bi-encoder embeds query and document separately, so document vectors are precomputed and search is a nearest-neighbor lookup. A cross-encoder reads query and document together through full attention and outputs a single relevance score. It's more accurate because it sees how the words interact, but nothing can be precomputed, so it only runs on a short candidate list.
- *Why that model?* ADR 0010. An 8 GB M1 and a zero budget ruled out the PyTorch `bge-reranker-v2-m3`. Of the two ONNX options, jina-tiny was faster with a tighter spread (558 vs 749 ms p50 for 20 candidates) and has a stated Apache-2.0 license.
- *Why 20 candidates and not 50?* Cost grows linearly, about 28 ms per candidate here, so 20 keeps reranking near half a second. The trade-off is that reranking can't raise recall above what the top 20 already contain.
- *How do you know it helped, and not just moved things around?* Reranking mostly changes MRR, how high the right section ranks, which is why MRR sits beside Recall@5. Recall@20 of the first stage is the ceiling it can reach, and here that ceiling is 1.00: every labeled section is somewhere in the 20 dense candidates, including the one `remote-cache-outage` misses at rank nine. So on this corpus retrieval is not the bottleneck. The reranker is.
- *Was it worth the latency?* Yes, and it's on by default, but the trade is real and worth naming. It bought recall (0.90 → 0.95), citation recall in the agent (0.90 → 0.95), and a relevance gate that no longer costs a model call. It cost MRR (0.88 → 0.83) and about 255 ms per search. Recall and grounded citations matter more here than rank order, because the human checkpoint shows five sources either way.
- *What else uses the score?* The agent's relevance gate switched from the dense similarity score to the cross-encoder score, so "is this context good enough to answer from" is deterministic and free instead of an LLM call (ADR 0011). The threshold is 0.65 on the top hit's score (`AGENT_RELEVANCE_THRESHOLD`), and the measurement behind it is the best argument for the switch: by reranker score the golden questions' top hits land between 0.821 and 0.948 and off-topic questions reach at most 0.489, so 0.65 sits in a wide empty gap. By cosine similarity the same split is 0.668 to 0.884 against up to 0.64, where 0.65 would sit directly on the off-topic ceiling. The reranker didn't just reorder results; it made the gate separable.

## LangGraph agent with Postgres-checkpointed human-in-the-loop

**What's built.** A state graph: `retrieve -> grade_relevance -> generate`, or `rewrite_query -> retrieve`, capped at two hops. After grading, the graph interrupts and shows the retrieved sources. Approve continues to generation, and reject routes to a query rewrite within the hop limit. LangGraph's Postgres checkpointer is passed in at compile time and saves state per thread id. Tests use the in-memory checkpointer. A CLI command starts a question, prints the pending sources, and resumes by thread id with approve or reject. An integration test pauses a run, resumes it from a new process against Postgres, and gets a cited answer.

**Result.** All ten questions answered, grounding 1.00, citation recall 0.95 with reranking and 0.90 without, p50 1.0 s and p95 12.3 s end to end, and 1.0 hops on average.

- Every answer cites only chunks it was shown, which the answer schema enforces by making `cited_ids` an `enum` of the context ids, and no answer text contains a chunk id.
- The two citation-recall misses are the two-document questions, and both are retrieval misses rather than generation misses: the uncited section was never among the five chunks the tool returned, so the model never saw it.
- The gap between a 1.0 s median and a 12.3 s p95 is one question, and the cause is not known. The adapter doesn't log its rate-limit waits, so whether that was a wait on Groq's per-minute token budget or just a slow reply is an open question. Say so plainly; it is the one loose end in the numbers.
- Tokens per pass was never recorded, so ADR 0011's 40K to 80K estimate is still an estimate.

**Likely follow-ups**

- *Why pause before generation and not after?* Steering is cheapest before tokens are spent and before a wrong answer exists for anyone to anchor on. A person can see "these sources are about Orbit 4.0, I asked about 5.0" in two seconds.
- *What does checkpointing buy you?* Without it, a graph run lives in memory and dies on restart. The checkpointer saves state after each step under a thread id, so a run waiting for approval survives a crash or a reviewer who answers tomorrow. Name the calls, because this is where a vague answer shows. The pause is `interrupt(payload)` inside the node. The resume reads the saved state with `graph.aget_state(config)`, checks `saved.interrupts` to confirm a run is actually waiting, then continues it with `graph.ainvoke(Command(resume=decision), config=config)`, where `config` carries the thread id. `Command(resume=...)` is the counterpart to `interrupt`: its value becomes that call's return value, and the node re-runs from its first line, so no earlier step repeats. Starting a run is the same `ainvoke` with an initial state instead of the `Command`.
- *What's in the state?* `question`, the current `query`, every `queries` searched so far, `hops`, the latest `hits`, whether they were `relevant`, the `context` the answer step was shown, whether it was `approved`, a `status`, the `answer`, and `cited_chunk_ids`. It's a `TypedDict` with `total=False`, so each step returns only the keys it changes and the graph merges them. Keep it serializable, because the checkpointer stores it.
- *Why a hop limit?* It bounds cost and latency. An unbounded rewrite loop is the classic agent failure. After two hops the graph returns the best grounded answer, or says it couldn't find one.
- *Why grade with a threshold instead of asking the LLM?* It's deterministic, free, and testable. On Groq's free plan (30 requests per minute, 200K tokens per day) every model call costs budget. The price is flexibility. What the generation evals showed is that the price was never paid on this set: the threshold passed all ten questions on the first search, nothing was wrongly rejected, and nothing was wrongly let through, since all ten answers came back grounded. The set is too small to have found the edge where a fixed threshold is wrong, and that's the honest caveat.
- *Why one model request per graph step?* Groq can't combine strict JSON-schema output and tool calling in one request, so tool selection, rewriting, and answering are separate calls. That also makes each step testable on its own.
- *What model is it?* An OpenAI-compatible `Generator` adapter pointed at Groq's free plan, default `qwen/qwen3.8-27b` (ADR 0011). No vendor SDK, so a local runtime is a config change. The adapter waits on HTTP 429 using the `x-ratelimit-reset-*` headers, sends its own User-Agent (a probe showed Cloudflare returns 403 to Python's default one), and caches responses by model, prompt, question, and context, so rerunning the evals with nothing changed costs nothing.
- *What does HITL cost?* Latency, a human in the critical path, and complexity: state has to be durable and serializable, and resume has to be idempotent. Worth it where a wrong answer is expensive. For a quick lookup, you'd make the gate optional.

**DriveOS bridge.** In a safety-certified release flow, the human checkpoint is the gate before anything irreversible: tagging a release, waiving a failing test, merging a patch. Durable state means the approval can happen hours later, by the right person, with an audit trail of what they were shown.

## pgvector and HNSW trade-offs

**What's built.** Each embedding model gets its own `vector(N)` column and HNSW index (ADR 0008). Changing embedders is additive: register, backfill with `study embed`, validate in the harness, flip the "current" marker, then drop the old column. The `bge-base` comparison went through exactly that path. Search is `ORDER BY col <=> query LIMIT k`, the shape the HNSW index serves. `ef_search` can be set per query with a transaction-local `set_config`, so it never carries over to another connection.

**Likely follow-ups**

- *HNSW or IVFFlat?* HNSW has a better recall/speed curve, needs no training step, and works on an empty table as rows are added. It costs a slower build and more memory. IVFFlat has to train its lists on data that's already there and degrades as the data shifts. For a corpus that grows, HNSW.
- *What are `m`, `ef_construction`, and `ef_search`?* `m` is links per node (default 16), `ef_construction` is the candidate list size during the build (64), and `ef_search` is the candidate list size at query time (40). Only `ef_search` is per-query, and experiments varied only that one.
- *What did you measure?* At 83 chunks, forcing the index gave recall@5 of 1.000 against exact search for every `ef_search` from 5 to 100. Postgres doesn't even pick the index on its own at that size: `EXPLAIN` shows a sequential scan. The honest takeaway is that the approximation trade-off doesn't show yet. Say that, and don't claim a tuning result.
- *Gotchas you hit?* (1) HNSW returns at most `ef_search` rows, so `ef_search = 1` with `LIMIT 5` returned one row. The store now requires `ef_search >= limit`. (2) A tie-break column in `ORDER BY` makes Postgres drop the index for a sort, so there's no tie-breaker. (3) pgvector returns NaN cosine distance for a zero vector, so zero embeddings are refused on write and on query.
- *Filtering?* A `WHERE` filter is applied after the HNSW scan, so a selective filter can return fewer than `k` rows. Newer pgvector versions add iterative scans for this.
- *Why not a vector database?* ADR 0000. One Postgres holds chunk text, vectors, the full-text index, and now the agent's checkpoints. There's no second store to keep in sync. A dedicated engine wins at a much larger scale.
- *Where does the latency actually go?* In Chunk 1, opening a new Postgres connection took about 15 ms of a 22 ms p50, and the SQL took 0.5 ms. The fix is a connection pool, not index tuning. No pool was added: `Store.get_connection` still opens a fresh `psycopg` connection per search, so those 15 ms are still there. What changed is that they stopped being the headline. Reranking moved the median to 283 ms, so connection setup is now about 5% of a search rather than two thirds of it. A pool is still the right next optimization, and it is the first thing to do if reranking ever moves off the request path.

## MCP tool contracts

**What's built.** `services/mcp_server` exposes one tool, `search`, that calls `rag_core.retrieve`. The agent reaches retrieval only through `services/api/.../mcp_client`. Never through a direct import, which ADR 0001 forbids.

**The contract, from the code**:

- **Input:** `query: str`, which must contain non-whitespace text, and `limit: int`, 1 to 20, defaulting to 5.
- **Output:** a list of `{id, document, section, content, distance, relevance}`. `id` is what citations point at, `section` is the chunk's heading path, `distance` is the cosine distance and is null for a chunk only lexical search found, and `relevance` is the reranker's score from 0 to 1 when the server reranks, otherwise the cosine similarity.
- **Answer contract:** the model returns strict JSON, `{answer, cited_ids}`. The app checks that every cited id is one the tool actually returned, so a hallucinated citation is caught mechanically. That's the citation grounding metric. The prompt keeps ids out of the answer text, because `qwen` copied them there in the probe (ADR 0011).
- **Errors** come back as structured tool results rather than exceptions, so the agent can rewrite the query instead of crashing.

**Likely follow-ups**

- *Why MCP and not plain function calling?* It separates tools from the model and the framework. The same server can serve this agent, Claude Code, or any other client, and `rag_core` stays the only implementation. The server is a thin consumer, and `AGENTS.md` enforces that as a rule.
- *What does the indirection cost?* The transport is a stdio subprocess (`StdioServerParameters`), with an in-process server object substituted in tests so the agent's tests need no subprocess. The per-call overhead was never measured, so don't claim a figure. What can be said is the bound: the agent's p50 is about 1.0 s and generation dominates it, so whatever stdio costs is inside the noise of a single model call. Measuring it properly means timing the tool call against a direct `retrieve` in the same process.
- *How would you design tools for a release pipeline?* This is the recruiter's "LLM tool design" area, so have it ready. Separate read-only tools (`search_failures`, `get_build_log`) from mutating ones (`retry_job`, `propose_patch`). Give mutating tools a dry-run mode and route them through a human checkpoint like the one in this graph. Truncate and paginate large logs with a cursor instead of returning megabytes. Keep outputs typed and deterministic so they can be tested. Evaluate tools on accuracy, false-positive rate, latency, and tokens.

## Eval harness

**What's built.** This is your strongest topic. Lead with it whenever you can.

- **Golden set:** 10 questions in TOML, each labeled by document path and section heading rather than chunk id, so labels survive re-chunking. It includes paraphrases, one exact error code, and five questions whose answer spans two documents. The loader rejects unknown keys, duplicates, and empty labels, and a CI test checks every label against the committed corpus, so a renamed heading fails the build.
- **Runner:** `study-eval <name>` sends each question through the same `retrieve` entry point everything else uses. One untimed warm-up absorbs the model load, then each question is timed 5 times, giving 50 samples. It reports Recall@5, MRR, and p50 and p95 by nearest rank, so p95 is a latency that was actually measured. Saved runs are never overwritten. A pre-flight check refuses a model with no vectors rather than saving a run with recall 0.
- **Separate budgets:** retrieval evals never call the LLM. Only generation evals spend Groq quota.
- **Generation evals:** per run, the number answered, the number refused for insufficient context, the grounding pass rate, citation recall, and p50 and p95 end to end. Per question, the answer, the cited chunk ids and sections, the context ids it was shown, whether it was grounded, its citation recall, its hop count and every query it searched. There is no answer-correctness grade, so correctness is still a human reading the ten answers.

**Likely follow-ups**

- *Is 10 questions enough?* No, so say it first. One question moving one rank shifts MRR by 0.05 or more, so smaller differences aren't evidence. Two runs of the same configuration differed by about 4 ms at p50 and 16 ms at p95, which is the latency noise floor. The harness tells you when a difference is real, and growing the set is the fix.
- *What's missing?* Still the same three. A run file records its name, timestamp, model id, dimension, `k`, `ef_search`, repeats, reranker and candidate count, but not the commit, the chunk size, or the query prefix. So two runs can be compared on configuration but not on the code that produced them, and a real regression gate needs all three in the file. This is the top of the backlog, and saying so is better than being asked.
- *Why not LLM-as-judge?* For retrieval, the labels are exact, so the check is deterministic. For generation, citations are checked mechanically against the retrieved ids. An LLM judge belongs on answer quality, calibrated against human labels.
- *How would this run in CI?* Unit tests run on fakes on every push. The eval needs the database and the model, so it runs as a separate or nightly job, compares against the saved baseline, and fails when recall drops by more than the noise floor.

**DriveOS bridge.** The job description says "analyze and measure how your solution performs and present recommendations." This harness does exactly that: a fixed baseline, a known noise floor, and recommendations backed by measured comparisons: keep the small embedding model, keep the reranker, and leave hybrid search off until the corpus outgrows the candidate pool.

## Where the resume is still ahead of the code

Finishing Phase 1.5 makes most of the resume line true. Four things are still off:

| Resume says | Reality after Phase 1.5 | Say instead |
| --- | --- | --- |
| "LangGraph agent on OpenAI API" | OpenAI-compatible adapter on Groq | "an OpenAI-compatible adapter, currently on Groq's free tier" |
| "BM25" | Postgres `ts_rank`, no IDF | "BM25-style lexical search through Postgres full-text" |
| "hybrid dense + BM25" | Built and measured, but off by default, because it bought nothing at 83 chunks | "It's built and behind a setting. I measured it, it didn't pay at this corpus size, so it ships off." |
| "Dockerized FastAPI backend, and React frontend" | Not in Phase 1.5. It's a CLI plus an MCP server, and only Postgres runs in Docker | "The FastAPI service and React UI are the next phase. Today the agent runs from a CLI." |

Bring up the FastAPI and React gap yourself. Don't wait for them to find it. Something like: "Everything up to the agent and the human checkpoint is built and measured. The FastAPI service with streaming and the React UI are next."

**The eval harness isn't on the resume at all.** If you can still edit it:

> Agentic RAG assistant over release-engineering docs. Dense retrieval with optional BM25-style lexical fusion by RRF, cross-encoder reranking (Recall@5 0.90 to 0.95), and a LangGraph agent over an MCP tool with a Postgres-checkpointed human approval step, grounding every citation it returns. A golden-set eval harness (Recall@5, MRR, p95) gates every change. Python, pgvector (HNSW), Groq via an OpenAI-compatible adapter.

That wording claims the reranker, which paid, and keeps the lexical fusion as optional, which is what it is. Claiming live hybrid BM25 invites a question whose honest answer undercuts the claim.
