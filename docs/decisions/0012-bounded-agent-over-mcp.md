# 12. Bounded Agent over MCP

- Status: Accepted, extended by the amendment below (the approval checkpoint)
- Date: 2026-11-26

## Context

The generation lane answers a question from the corpus with citations. Three earlier records shape
it:

- [ADR 0001](0001-rag-retrieval-boundary.md): retrieval lives in `rag_core`, and the agent reaches it
  through the MCP server rather than importing it.
- [ADR 0007](0007-generation-backend.md): generation goes through a vendor-neutral `Generator` that
  speaks the OpenAI-compatible protocol.
- [ADR 0011](0011-free-hosted-generation.md): the MVP model runs on a free plan of 30 requests per
  minute and 8,000 tokens per minute, which cannot combine strict structured output with tool calling
  in one request.

An agent built as an open loop, in which the model decides on each turn whether to call a tool,
search again, or answer, has no fixed bound on its requests, and its behavior varies with the model.
On a free plan, an unbounded loop can exhaust the per-minute budget on one question, and a run that
never ends is hard to evaluate.

Two measurements informed the decision:

- Top-1 cosine similarity with `bge-small-en-v1.5`, the default embedder ([ADR 0010](0010-lightweight-embedding-and-reranking-models.md)):
  the ten golden questions scored 0.668 to 0.884. Off-topic questions scored 0.45 to 0.64.
  Questions close to the corpus that it cannot answer scored up to 0.738, for example "What is the
  release date of Orbit 6.0?".
- A strict JSON-schema request to `qwen/qwen3.8-27b` on Groq with `cited_chunk_ids` restricted to an
  `enum` of the context's chunk ids was accepted. The model cited only those ids, and for an
  unanswerable question it returned `answerable: false` with no citations.

## Decision

The agent is a fixed state machine in LangGraph with a hard hop limit, not a tool-calling loop.

```text
retrieve -> grade_relevance -> generate                      (relevant)
                            -> rewrite_query -> retrieve     (not relevant, hops left)
                            -> insufficient_context          (not relevant, no hops left)
```

- Retrieval through MCP: `retrieve` calls the MCP server's `search` tool. The graph decides when to
  search, so the model is never offered the tool.
- Hop limit: at most two searches per question, so at most one rewrite. The limit is a setting.
- Score-based grading: `grade_relevance` compares the top hit's cosine similarity with a threshold of
  0.65, with no model request. The threshold sits below every golden question and above the
  off-topic ones. It does not separate questions near the corpus, so it screens out clearly
  irrelevant context and leaves the final call to the answer step. The reranker's score replaces the
  dense similarity once the reranker exists.
- One model request per step: `rewrite_query` makes one free-text request, and `generate` makes one
  strict-schema request.
- Cited structured output: the answer is `{answerable, answer, cited_chunk_ids}` under a strict JSON
  schema, with `cited_chunk_ids` an `enum` of the chunk ids shown to the model. The instructions keep
  ids out of the answer text. `answerable: false` ends the run as insufficient context.
- Ending: every run ends as `answered`, with its citations, or `insufficient_context`, after at most
  two searches and two model requests.
- Checkpointing: the graph compiles with an optional checkpointer, none by default, so a later stage
  can pause a run without changing the graph.

## Consequences

- Every question costs at most two searches and two model requests, and the cost is known before
  the run. On the golden set, all ten questions were answered from the first search with one model
  request each.
- Runs are reproducible: the path depends only on the retrieval scores and the model's replies, and
  cached replies make an unchanged rerun free.
- The model cannot cite a chunk it was not shown. The grounding check in the agent evaluation still
  verifies it, since the guarantee rests on the provider enforcing the schema.
- Unanswerable questions end cleanly. Off-topic questions stop at the score threshold after one
  rewrite and never reach the answer step. Questions near the corpus reach it, and the model declines
  through `answerable`.
- The agent cannot decide to search for a sub-question or to use another tool. Adding tools means
  adding steps to the graph, which keeps each one visible and bounded.
- The threshold is tied to the embedding model's similarity scale. A different embedder, or the
  reranker's score, needs the threshold measured again.
- One rewrite is the only recovery from a poor first search. A question whose answer retrieval does
  not return in the top five cannot be fully answered, which the citation-recall misses on the two
  multi-document golden questions show.

## Amendment, 2026-11-27: the approval checkpoint

The record above said a later stage could pause a run "without changing the graph", because the
graph already compiled with an optional checkpointer. That turned out to be half right: the
checkpointer needed no change, but the pause itself is a step, so the graph gained one.

```text
retrieve -> grade_relevance -> review_sources -> generate    (relevant, approved)
                            -> rewrite_query -> retrieve     (not relevant, hops left)
                            -> insufficient_context          (nothing left to try)

review_sources -> rewrite_query -> retrieve                  (rejected, hops left)
               -> insufficient_context                       (rejected, no hops left)
```

- One graph, one setting. `review_sources` is always in the graph. With `require_approval` it calls
  LangGraph's `interrupt` with the retrieved sources and the run stops there; without it the step
  approves them itself, so the one-shot path keeps its behavior and gains a pass-through node. A
  second graph shape built only for approval was rejected: one state machine is easier to reason
  about and to test.
- The pause sits after the relevance grade and before the answer. That is the last point where a
  decision can still change the outcome without the answer having been paid for. Irrelevant context
  never reaches the checkpoint, because there is nothing to approve and the graph already rewrites.
- A rejection costs a hop. It routes to `rewrite_query` while hops remain and to
  `insufficient_context` otherwise, so the bound on searches bounds rejections too and a person
  cannot extend a run indefinitely.
- Paused runs are saved by LangGraph's Postgres checkpointer in the `DATABASE_URL` database, in its
  own tables. This is not a retrieval path: the corpus is still read only through the MCP search
  tool, as [ADR 0001](0001-rag-retrieval-boundary.md) requires, and a test fails on any `rag_core`
  import in the generation lane.
- What a pause carries is plain data (the question, the query, the hop, and each source's id,
  document, section, and relevance), because the process that resumes a run may have none of the
  lane's classes loaded. The saver's serializer is told about the types the state carries, since an
  unlisted type is restored as a plain dictionary rather than refused.
- Before the API exists, the checkpoint is driven from the command line: `study-ask --review`
  prints the pending sources and a thread id, and `study-ask --resume <thread-id> --approve` or
  `--reject` carries the decision. The HTTP surface stays in Phase 7.

Consequences: a run's latency is now a person's when approval is required, and each run writes one
saved state per step. Nothing else about the agent's cost changes, since the checkpoint adds no
search and no model request.
