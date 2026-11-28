# 05. Hybrid Retrieval

> Part of the [Project](README.md) section of [AI, RAG & Python](../README.md). Built in
> [study_assistant#69](https://github.com/sid-ak/study_assistant/issues/69), pull request
> [study_assistant#75](https://github.com/sid-ak/study_assistant/pull/75).

Chunk 5 added keyword search beside vector search. Postgres full-text search finds chunks that
contain the question's exact words, Reciprocal Rank Fusion merges its list with the dense list, and
the reranker then picks the final five. The harness showed no change on the golden set once
reranking was on, so hybrid search ships off by default, and the reason it showed no change is the
main lesson of the chunk.

| Piece | Module | What it does |
| ----- | ------ | ------------ |
| Lexical search | `rag_core/store/` | `search_lexical` over the generated `tsv` column and its GIN index, ranked by `ts_rank` |
| Fake | `rag_core_testing` | Counts shared words outside a stop-word list |
| Fusion | `rag_core/retrieve/` | `lexical_search` and `fuse`, between `search` and `rerank` |
| Setting | `rag_core.config` | `HYBRID_ENABLED`, off by default |

The general theory is in [Retrieval](../concepts/05-retrieval.md), under Lexical search,
TF-IDF and BM25, and Hybrid search and Reciprocal Rank Fusion.

## Lexical search in Postgres

Why it matters: dense search compares meaning, so it is careless about exact strings, and a
release-notes corpus is full of error codes and flags. Lexical search is the opposite, which is
the whole reason for running both.

```sql
SELECT id, document_id, content, metadata, ts_rank(tsv, q) AS score
FROM chunks,
     CAST(replace(plainto_tsquery('english', %(query)s)::text, ' & ', ' | ') AS tsquery) q
WHERE tsv @@ q
ORDER BY score DESC
LIMIT %(limit)s
```

- The column: `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`, with a
  GIN index. It was already in the Phase 1 schema, so nothing had to be migrated, and the dev
  database's 83 chunks already had it populated.
- AND to OR: `plainto_tsquery` stems the query, drops stop words, and joins the rest with AND. "What
  does error E1050 mean?" becomes `'error' & 'e1050' & 'mean'`, which no chunk contains. Replacing
  each `&` with `|` matches any of the words, and `ts_rank` ranks chunks containing more of them
  higher. With OR, that question ranks Orbit 5.0's New features first.
- Tokens: `E1050` becomes `e1050`, `--config=asan` becomes `config` and `asan`, and
  `--orbit-workers` becomes `orbit-work`, `orbit`, and `worker`, so flags match by their parts.
- `ts_rank` is not BM25: it uses no inverse document frequency, so a rare error code counts no more
  than a common word, and by default it ignores chunk length.

## Fusion between search and rerank

Why it matters: the two searches return scores on different scales, so they cannot simply be
added. Where the merge happens also decides what the reranker gets to choose among.

??? example "retrieve"

    ```python
    found = search(query, embedder=embedder, store=store, limit=pool, ef_search=ef_search)
    if hybrid:
        lexical = lexical_search(query, store=store, limit=pool)
        found = fuse([found, lexical], limit=pool)
    if reranker is None:
        chunks = found[:limit]
    else:
        chunks = rerank(query, found, reranker=reranker, limit=limit)
    ```

Source: [`packages/rag_core/src/rag_core/retrieve/dense.py:185-195`](https://github.com/sid-ak/study_assistant/blob/3d2fa07/packages/rag_core/src/rag_core/retrieve/dense.py#L185-L195)

??? example "fuse"

    ```python
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            fused_score[chunk.id] = fused_score.get(chunk.id, 0.0) + 1.0 / (RRF_K + rank)
            if chunk.id not in first_seen:
                first_seen[chunk.id] = len(first_seen)
    ```

Source: [`packages/rag_core/src/rag_core/retrieve/dense.py:112-116`](https://github.com/sid-ak/study_assistant/blob/3d2fa07/packages/rag_core/src/rag_core/retrieve/dense.py#L112-L116)

- Same-size pools: each search fetches the reranker's 20 candidates (or the limit without a
  reranker), and fusion keeps the best 20 of the union.
- Ties: equal fused scores keep the order of first appearance, dense list first, so the result is
  deterministic.
- No distance for lexical-only chunks: `RetrievedChunk.distance` became optional, which mypy then
  traced through the MCP server, the client, and the eval runner.
- Relevance after fusion: without a reranker it is the RRF score, about 0.016 to 0.033, so the
  agent's 0-to-1 threshold assumes reranking is on whenever hybrid is on.
- The setting reaches the MCP server: `HYBRID_*` was added to the server's environment in the same
  change, with a test, after Chunk 4's reranking setting had silently not reached it. A server test
  proves fusion ran by its signature: a relevance of exactly 2/61.

## Python used

Why it matters: these are the language features this stage leans on, listed so the page can be
read as Python practice as well as design.

| Feature | Where it appears | What it does here |
| ------- | ---------------- | ----------------- |
| `dict.get(key, 0.0)` | `fuse` | Starts a sum at zero the first time a chunk is seen |
| `float \| None` field | `RetrievedChunk.distance` | Marks a value that only some producers can supply |
| Subclassing a fake | `LexicalStubStore(InMemoryStore)` | Fixes lexical results so fusion is tested apart from either scorer |
| Sets of contents | Lexical contract tests | Compares which chunks come back, not their order |
| `psycopg` named parameters | `search_lexical` | `%(query)s` binds the text safely; only `&` and `\|` are rewritten in SQL |

## Design trade-offs

Why it matters: each row is a decision that could have gone the other way, with the record that
settled it and the alternative it rejected.

| Decision | Chosen | Rejected alternative | Record |
| -------- | ------ | -------------------- | ------ |
| Lexical ranking | Postgres `ts_rank` | `pg_bm25`, an extension, adopted only if the harness shows a gap | Issue #12 |
| Query form | OR of stemmed words | `plainto_tsquery`'s AND, which a full question rarely matches | Pull request #75 |
| Fusion | Reciprocal Rank Fusion, k = 60 | A weighted sum of scores on different scales | Pull request #75 |
| Default | Off | On, at about 47 ms per search for no measured gain | Pull request #75 |
| Schema | The existing Phase 1 column | Recreating the database, which would have deleted both models' vectors | Pull request #75 |

## Measured results

Why it matters: these are the numbers this stage produced, and they are what any claim about it
rests on.

| Run | Recall@5 | MRR | p50 | p95 |
| --- | -------- | --- | --- | --- |
| Dense | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| Dense, reranked | 0.95 | 0.83 | 283.1 ms | 417.5 ms |
| Hybrid, reranked | 0.95 | 0.83 | 330.3 ms | 451.4 ms |

- No change with reranking on: every labeled section is found at the same rank. One unlabeled
  fifth result changed.
- Why: the reranker chooses among the candidates, and the 20 dense candidates already held what
  lexical search would add. For "What does error E1050 mean?" the defining section is third among
  them, and for the bare query `E1050` it is fifth; the reranker moves it to first either way.
  Twenty candidates are about a quarter of an 83-chunk corpus.
- Where it helps: with reranking off, the bare query `E1050` misses its section in dense search's
  top three and finds it second with hybrid search, at a relevance of exactly 1/61, which only
  lexical search's first place produces.
- What it should do on a larger corpus: once an answer can fall outside the dense candidates,
  lexical search is the only way it reaches the reranker.

## Interview questions

Why it matters: the questions this stage invites, with answers short enough to say out loud.

Why combine lexical and dense search?
: They fail differently. Dense search matches meaning and misses exact identifiers, because a small
  embedding model represents an error code as a few generic word pieces. Lexical search matches the
  identifier exactly and misses paraphrases. Fusing the two gives a candidate list with both.

Why Reciprocal Rank Fusion rather than adding the scores?
: Cosine distance and `ts_rank` are on unrelated scales, and either could dominate a sum. RRF uses
  only ranks, 1 / (60 + rank) per list, so no calibration is needed and agreement between the lists
  is rewarded.

How does Postgres full-text search differ from BM25?
: Both reward frequent query words in a passage, but `ts_rank` has no inverse document frequency,
  so a rare code counts like a common word, and by default it ignores passage length. BM25 also
  saturates term frequency. The project documents `ts_rank` as an approximation and would adopt a
  BM25 extension only if the evaluation showed a gap.

Hybrid search changed nothing on your eval. Was it worth building?
: The measurement showed why: with a reranker over 20 candidates in an 83-chunk corpus, the dense
  candidates already contained the exact-match sections. That is a property of the corpus size, so
  the setting stays off by default and the run is worth repeating on a larger collection. Without
  the reranker it already fixes the exact-code case.

How did you make sure hybrid mode actually ran in the agent's server?
: The setting is passed to the MCP server's environment and tested, and a server test checks a value
  only fusion produces, a relevance of exactly 2/61, rather than trusting the flag.
