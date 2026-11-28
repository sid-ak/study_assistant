# 06. Reranking

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

Reranking is a second ranking pass over a short list of retrieved candidates. A fast first stage,
such as dense vector search, finds a few dozen candidates out of a large collection. A slower and
more accurate model then reads the question together with each candidate, scores how well the
candidate answers it, and reorders the list. Only the best few go on to generation. This page covers
cross-encoders and how they differ from bi-encoders, why reranking a short list works, and what it
costs in latency.

| Stage | Model | Reads | Cost per query | Strength |
| ----- | ----- | ----- | -------------- | -------- |
| First-stage retrieval | Bi-encoder | Query and passage separately | One embedding plus an index search | Searches millions of passages in milliseconds |
| Reranking | Cross-encoder | Query and passage together | One model pass per candidate | Judges fine relevance, such as which of two similar passages answers the question |

## Bi-encoders and cross-encoders

Why it matters: these are the two ways a model can compare a question with a passage, and the whole
design of a retrieval pipeline follows from the fact that one is fast and precomputable while the
other is accurate and cannot be. Reranking exists to use both.

A bi-encoder embeds the query and each passage separately, as described in
[Embeddings](03-embeddings.md). Passage vectors are computed ahead of time, so a search needs only
the query's vector and a nearest-neighbor lookup.

A cross-encoder takes the query and one passage as a single input and outputs one relevance score.

```text
bi-encoder:     embed("Which flag enables ASan?")  ->  vector   } compared afterwards
                embed("bazel test --config=asan")  ->  vector   }

cross-encoder:  score("[CLS] Which flag enables ASan? [SEP] bazel test --config=asan [SEP]")  ->  2.52
```

- Attention across both texts: inside a cross-encoder, every query token is compared with every
  passage token. The model can notice that the question asks about a flag and that this passage
  names one, which separate vectors summarize away.
- No precomputation: the score depends on the query, so nothing can be computed before the question
  arrives. Scoring every passage in a large collection per query would be far too slow.
- The output: a single number, usually a logit, an unbounded score where larger means more
  relevant. Applying the sigmoid function, `1 / (1 + e^-x)`, turns it into a value between 0 and 1,
  which keeps the order and gives thresholds a fixed range.

## Retrieve, then rerank

Why it matters: this is the pattern that makes an accurate model affordable. Running the slow model
over a short list, chosen by the fast one, costs a fixed amount per question rather than growing
with the collection.

The two models are combined in stages: the bi-encoder narrows the collection to a candidate list,
and the cross-encoder orders that list.

study_assistant keeps the two stages as separate functions, so fusion of a second search can sit
between them. The reranking step rescores the candidates it is handed and keeps the best few. Two
details in it are deliberate. Sorting `(-score, position, chunk)` tuples means equal scores keep
the order dense search gave them, and the chunks themselves are never compared. And each kept chunk
has its relevance replaced by the reranker's score while its original distance is left untouched,
so what the caller reads is the better judgment without losing where it came from.

??? example "rerank"

    ```python
    def rerank(
        query: str, chunks: list[RetrievedChunk], *, reranker: RerankerProtocol, limit: int
    ) -> list[RetrievedChunk]:
        """The second step: rescore ``chunks`` with ``reranker`` and keep the ``limit`` best.

        Each kept chunk's relevance is the reranker's score; its distance is still the dense one.
        Chunks with equal scores keep their order from ``chunks``.
        """
        scores = reranker.score(query, [chunk.content for chunk in chunks])
        scored: list[tuple[float, int, RetrievedChunk]] = []
        for position, (chunk, score) in enumerate(zip(chunks, scores, strict=True)):
            # The position breaks ties, so equal scores keep the dense order and the chunks
            # themselves are never compared.
            scored.append((-score, position, chunk))
        scored.sort()
        reranked: list[RetrievedChunk] = []
        for negative_score, _, chunk in scored[:limit]:
            reranked.append(replace(chunk, relevance=-negative_score))
        return reranked
    ```

Source: [`packages/rag_core/src/rag_core/retrieve/dense.py:131-149`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/retrieve/dense.py#L131-L149)
- Candidate count: the reranker can only return passages the first stage found. Fetching 20 to 100
  candidates for a final 5 gives it room to promote a relevant passage that dense search ranked
  low.
- What improves: recall at the final cutoff, when a relevant passage was among the candidates but
  below the cutoff, and the order of the final list.
- What cannot improve: a relevant passage the first stage missed entirely. Widening the candidate
  list or improving the first stage, for example with hybrid search, addresses that.
- Separate steps: keeping search and reranking as separate functions lets another step, such as
  merging dense and keyword results, sit between them.

## Latency cost

Why it matters: reranking is the single most expensive step in this project's retrieval path, by an
order of magnitude. Knowing what it costs, and what the cost buys, is what makes it a defensible
choice rather than an added dependency.

A cross-encoder runs one model pass per candidate, so its cost grows with the candidate count.

- Scale: a small cross-encoder on a laptop CPU scores a query against 20 short passages in a few
  hundred milliseconds. That is often ten times the cost of the dense search before it.
- Reading the cost: compare p50 and p95 latency with and without reranking, as described in
  [Evaluation](09-evaluation.md). The added time is nearly constant per query, so both percentiles
  rise by about the same amount.
- Loading: the model is loaded once per process, which adds seconds to the first query. Loading it
  at startup keeps that out of the first user's wait.
- Trade-off controls: fewer candidates, a smaller model, or reranking only when the first stage's
  top score is uncertain all reduce the cost.
- Context: in a system that also calls a language model, generation often takes a second or more,
  so a few hundred milliseconds of reranking may be a small share of the total.

Measured here, reranking took the median query from 26 ms to 283 ms, about eleven times the cost,
and raised recall from 0.90 to 0.95. That is the trade in one line: a tenfold latency increase for
one more correct answer in twenty, on a corpus where the answer was usually already in the
candidates. It is worth paying in this project because the model call that follows takes longer
still, so the user-visible share is small.

The model is loaded lazily, as the embedder is, so constructing the reranker only validates the
model name and the first query pays the load.

## Reranker scores as relevance grades

Why it matters: a score that means something on its own, rather than only relative to other scores,
is what lets a system decide whether to answer at all. That is what the project's agent uses to
avoid answering from irrelevant context.

Because a cross-encoder reads the query and the passage together, its score is a better estimate of
"does this passage answer this question" than vector similarity is.

- Thresholds: an agent can decide whether its retrieved context is good enough by comparing the top
  reranker score with a threshold, without asking a language model. A calibrated score separates
  relevant from irrelevant results more widely than cosine similarity does, which makes the
  threshold less fragile.
- Calibration: the threshold must be measured on questions with known answers and questions the
  collection cannot answer. A threshold chosen for one model's scores does not carry over to
  another's.
- Limits: a question about a subject the collection covers, but asking for a fact it does not
  contain, can still score high. The final judgment belongs to the step that reads the passage and
  answers, which can decline.

study_assistant converts every cross-encoder output through a sigmoid for exactly this reason. The
model returns a logit, unbounded in either direction, and a threshold against a raw logit would
mean something different for every model. Passing it through a sigmoid gives a 0-to-1 probability,
so the agent's threshold is a number that survives changing the reranker.

??? example "score"

    ```python
    def score(self, query: str, documents: list[str]) -> list[float]:
        """The sigmoid of the cross-encoder's logit for each document, from 0 to 1.

        The model outputs a logit per pair, unbounded in either direction; the sigmoid turns it into
        a probability of relevance, so a threshold means the same thing for any cross-encoder.
        """
        if not documents:
            return []
        scores: list[float] = []
        for logit in self.load().rerank(query, documents):
            scores.append(sigmoid(float(logit)))
        return scores
    ```

Source: [`packages/rag_core/src/rag_core/rerank/fastembed_reranker.py:62-73`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/rerank/fastembed_reranker.py#L62-L73)

The threshold itself is the part that is not calibrated, and that is the honest caveat. It was
chosen by looking at the scores ten known questions and a few unanswerable ones produced, which is
enough to screen out clearly irrelevant context and not enough to separate a question the corpus
nearly answers from one it does. The step that writes the answer carries the rest of that
judgment.

## What reranking changes in the metrics

Why it matters: reranking moves two measurements in different directions, and reading only the
headline number hides that. This is the section that explains a result the project actually
produced.

- Recall@K usually rises, because relevant passages from lower in the candidate list move into the
  top K.
- MRR can rise or fall. A reranker may rank a passage from the right document that discusses the
  subject above the labeled passage that answers the question, which lowers the reciprocal rank
  without making the results worse to a reader.
- Reading per-question changes, not only averages, shows which effect dominates.

This is not hypothetical here: reranking raised recall from 0.90 to 0.95 and lowered the ranking
measure from 0.88 to 0.83. The cause was visible only per question. The reranker promoted a chunk
from the right document that discusses the subject above the labeled chunk that answers it, which
costs the ranking measure without making the result worse to read. Reporting both numbers, and
saying which moved and why, is more defensible than quoting the one that improved.

> A course assistant retrieves 30 passages by vector search and reranks them before answering.
> "What is the time complexity of Dijkstra's algorithm with a binary heap?" first retrieves several
> passages about shortest paths. The reranker promotes the one stating the complexity, which vector
> search had ranked eighth, into the top three that the language model reads.

The practical rule is to keep a fast first stage for breadth, rerank a candidate list several times
larger than the final cutoff, measure the latency it adds at p50 and p95, and recalibrate any
threshold on the reranker's own scores.
