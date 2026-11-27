# 12. Bounded Agent over MCP

- Status: Accepted
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
