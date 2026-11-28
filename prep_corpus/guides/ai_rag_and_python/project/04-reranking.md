# 04. Reranking

> Part of the [Project](README.md) section of [AI, RAG & Python](../README.md). Built in
> [study_assistant#49](https://github.com/sid-ak/study_assistant/issues/49), pull request
> [study_assistant#74](https://github.com/sid-ak/study_assistant/pull/74).

Chunk 4 added a cross-encoder reranker to retrieval. Dense search now fetches 20 candidates, and
`jina-reranker-v1-tiny-en` reads the question together with each one and keeps the best five. The
agent grades its context on the reranker's score instead of cosine similarity. The Chunk 2 harness
measured the effect with and without it, and reranking is on by default.

| Piece | Module | What it does |
| ----- | ------ | ------------ |
| Reranker | `rag_core/rerank/` | `RerankerProtocol`, a lazily loaded fastembed cross-encoder, and `build_reranker(settings)` |
| Fake | `rag_core_testing` | `OverlapReranker` scores the share of query words a passage contains |
| Retrieval | `rag_core/retrieve/` | `search`, then an optional `rerank`, composed by `retrieve` |
| Settings | `rag_core.config` | `RERANK_ENABLED` (on), `RERANKER_MODEL`, `RERANK_CANDIDATES` (20) |
| Agent | `services/api` | Grades the top hit's `relevance` as the MCP server reports it |

The general theory is in [Reranking](../concepts/06-reranking.md).

## The reranker

Why it matters: a cross-encoder is the first component here that reads a question and a passage
together, which is why it judges relevance better than vector distance. It is also the most
expensive step in the pipeline, so it has to earn its place.

??? example "FastembedReranker"

    ```python
    class FastembedReranker:
        def score(self, query: str, documents: list[str]) -> list[float]:
            if not documents:
                return []
            scores: list[float] = []
            for logit in self.load().rerank(query, documents):
                scores.append(sigmoid(float(logit)))
            return scores
    ```

Source: [`packages/rag_core/src/rag_core/rerank/fastembed_reranker.py:28-73`](https://github.com/sid-ak/study_assistant/blob/cbd4e7b/packages/rag_core/src/rag_core/rerank/fastembed_reranker.py#L28-L73)

- Protocol: `RerankerProtocol.score(query, documents)` returns relevance from 0 to 1, one per
  document in order. The fake and the real model satisfy one contract suite.
- Sigmoid: a probe showed raw scores from about -1.5 to 2.6 (2.52 for the passage that answered,
  -1.49 for an unrelated one). The sigmoid keeps the order and fixes the range, so a threshold means
  the same thing for any reranker.
- Lazy loading: building the reranker only checks the model id against fastembed's list; the first
  `score` downloads and loads it. Measured: 130 MB on disk, 3.7 s to load, 324 MB peak memory.

## Search and rerank as separate steps

Why it matters: keeping the two as separate functions is what later let fusion sit between them. A
combined function would have had to be taken apart first.

??? example "retrieve"

    ```python
    if reranker is None:
        chunks = search(query, embedder=embedder, store=store, limit=limit, ef_search=ef_search)
    else:
        found = search(query, embedder=embedder, store=store, limit=candidates, ef_search=ef_search)
        rerank_started = time.perf_counter()
        chunks = rerank(query, found, reranker=reranker, limit=limit)
        rerank_latency_ms = (time.perf_counter() - rerank_started) * 1000.0
    ```

Source: [`packages/rag_core/src/rag_core/retrieve/dense.py:124-131`](https://github.com/sid-ak/study_assistant/blob/cbd4e7b/packages/rag_core/src/rag_core/retrieve/dense.py#L124-L131)

- Two public functions: `search` returns the dense ranking, and `rerank` reorders any list of
  chunks. Hybrid search in Chunk 5 sits between them.
- Relevance on every chunk: `RetrievedChunk.relevance` is the reranker's score, or the cosine
  similarity without one, and `rerank_latency_ms` times the reranking step on its own.
- Stable ties: `rerank` sorts `(-score, position, chunk)` tuples, so equal scores keep their dense
  order and the chunks themselves are never compared.
- One builder: `build_reranker(settings)` returns the reranker or `None`, and `study query`,
  `study-eval`, and the MCP server all build it this way.

## A setting that never reached the server

Why it matters: this is the failure worth knowing about, because nothing broke. A setting that
silently never arrived produced plausible results, which is the kind of bug a measurement catches
and a test prevents.

The agent searches through the MCP server, a separate process that receives only the environment
variables the client passes to it. Those were `DATABASE_*`, `EMBEDDING_*`, `FASTEMBED_*`, and
`TMPDIR`, so `RERANK_ENABLED=true` never reached the server.

- How it showed: the first agent evaluation "with reranking" reported a median of 26 ms per
  question. The server had searched dense-only, so every prompt matched Chunk 3's and every reply
  came from the cache. Reranking alone costs about 280 ms.
- The fix: pass the `RERANK` prefix, which covers `RERANK_ENABLED`, `RERANK_CANDIDATES`, and
  `RERANKER_MODEL`, with a test. A probe then showed the server returning reranker scores, 0.821
  instead of a cosine similarity of 0.611 for the same chunk.
- The guard: agent runs now record the reranker the server used, so a saved run states how its
  retrieval ranked.
- The general lesson: a setting that crosses a process boundary is not in effect until a value
  only that mode produces appears in the output.

## Grading on the reranker's score

Why it matters: a score that means something on its own is what lets the agent decide whether to
answer at all, rather than only which passage to prefer.

The agent's `grade_relevance` compares the top hit's `relevance` with 0.65.

| Top-hit relevance | Golden questions | Off-topic questions | Near-domain, unanswerable |
| ----------------- | ---------------- | ------------------- | ------------------------- |
| Cosine similarity | 0.668 to 0.884 | 0.45 to 0.64 | up to 0.738 |
| Reranker score | 0.821 to 0.948 | 0.21 to 0.49 | up to 0.829 |

- The margin: by cosine similarity, the lowest golden question beat the highest off-topic one by
  0.028. By reranker score the gap is 0.33, and 0.65 sits near its middle.
- What still gets through: questions near the corpus that it cannot answer, such as "What is the
  release date of Orbit 6.0?", score as high as answerable ones. The model's `answerable` field
  declines them.

## Python used

Why it matters: these are the language features this stage leans on, listed so the page can be
read as Python practice as well as design.

| Feature | Where it appears | What it does here |
| ------- | ---------------- | ----------------- |
| `math.exp` | `sigmoid` | Turns a logit into a probability between 0 and 1 |
| `dataclasses.replace` | `rerank` | A copy of a frozen `RetrievedChunk` with a new `relevance` |
| Tuples sorted with a position | `rerank` | Sorting by score, ties broken by original position |
| `zip(..., strict=True)` | `rerank` | Raises if the reranker returns a different number of scores |
| `X \| None` return type | `build_reranker` | The caller handles "no reranker" explicitly |
| pytest `params` with `marks` | Reranker contract | The real model runs only in the integration set |

## Design trade-offs

Why it matters: each row is a decision that could have gone the other way, with the record that
settled it and the alternative it rejected.

| Decision | Chosen | Rejected alternative | Record |
| -------- | ------ | -------------------- | ------ |
| Reranker model | `jina-reranker-v1-tiny-en` on fastembed | `bge-reranker-v2-m3` on PyTorch, too large for the machine; `ms-marco-MiniLM-L-6-v2`, slower and without a stated license | [ADR 0010](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0010-lightweight-embedding-and-reranking-models.md) |
| Candidates | 20 | 50, as first planned, at more than twice the cost | ADR 0010 |
| Score range | Sigmoid of the logit, 0 to 1 | Raw logits, which change scale per model | Pull request #74 |
| Default | On | Off, keeping retrieval at 26 ms | Pull request #74 |
| Agent grading | The reranker's score | Cosine similarity, with a 0.028 margin | [ADR 0011](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0011-free-hosted-generation.md), [ADR 0012](https://github.com/sid-ak/study_assistant/blob/main/docs/decisions/0012-bounded-agent-over-mcp.md) |

## Measured results

Why it matters: these are the numbers this stage produced, and they are what any claim about it
rests on.

| Run | Recall@5 | MRR | p50 | p95 |
| --- | -------- | --- | --- | --- |
| Dense | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| Reranked from 20 | 0.95 | 0.83 | 283.1 ms | 417.5 ms |

| Agent run | Grounding | Citation recall | p50 | p95 |
| --------- | --------- | --------------- | --- | --- |
| Dense search | 1.00 | 0.90 | 1.0 s | 9.7 s |
| Reranked search | 1.00 | 0.95 | 1.0 s | 12.3 s |

- Gains: "What does error E1050 mean?" moves its answer from third to first. "What CMake version
  does Orbit 5.0 require?" now finds both labeled sections with Orbit 5.0's first, where dense search
  ranked Orbit 4.0's first. The agent then cites both.
- The MRR drop: for two questions the reranker ranks a section of the right document that is about
  the subject above the one that answers it: the linker write-up's Cause above its Fix, and Orbit
  5.0's Upgrade notes, which name `--orbit-workers`, above its Breaking changes, which give the
  replacement.
- Still missed: the CI write-up's Cause section for the remote-cache question is ninth of the 20
  candidates, and the reranker scores three other sections of the same write-up above it.
- Cost: about 255 ms per search, nearly the same at p50 and p95, since every query scores 20 pairs.
  In the agent, generation's roughly 1 s per question dominates, so the median barely moves.

## Interview questions

Why it matters: the questions this stage invites, with answers short enough to say out loud.

What does a cross-encoder do that the embedding model cannot?
: It reads the query and the passage as one input, so attention compares every query token with
  every passage token. The embedding model compresses each text into a vector separately, which
  loses details such as whether the passage answers this particular question. The cost is that
  nothing can be precomputed, so it only runs on a short candidate list.

Why rerank 20 candidates to keep 5?
: The reranker can only promote passages the first stage found. A candidate list four times the
  final size gives it room to move a relevant passage up from below the cutoff, while keeping the
  cost to about a quarter of a second on this machine.

Recall went up but MRR went down. Is the reranker worse?
: No. Per question, the reranker found more labeled sections (recall 0.95) and fixed the two worst
  rankings, but for two questions it put a neighbouring section of the right document first. Those
  sections discuss the subject without stating the answer, which lowers the reciprocal rank without
  hiding the answer from the top five.

How did you choose the relevance threshold after adding the reranker?
: By measuring the top-hit score on the ten golden questions and on off-topic questions. Reranker
  scores separated them by 0.33, against 0.028 for cosine similarity, so 0.65 sits safely in the
  gap. Questions near the corpus that it cannot answer still pass, and the model declines them.

How do you know the agent actually used the reranker?
: Its first evaluation did not: the setting never reached the MCP server's process, and the run
  answered from the cache in 26 ms. Now the client passes the reranking settings to the server, a
  probe confirms reranker scores come back, and each saved run records the reranker it used.
