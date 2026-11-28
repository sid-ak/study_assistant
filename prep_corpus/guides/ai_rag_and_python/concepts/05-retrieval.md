# 05. Retrieval

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

Retrieval finds the stored passages most relevant to a question. Dense retrieval does this with
vectors: the question is embedded with the same model as the passages, and the passages whose
vectors are nearest to the question's vector are returned. Lexical retrieval matches the words
themselves. This page covers dense search, how a nearest-neighbor search can be exact or
approximate, how the HNSW index makes approximate search fast and what its `ef_search` setting
trades, lexical search with TF-IDF and BM25, and hybrid search with Reciprocal Rank Fusion.

Every mechanism here is shown as [study_assistant](https://github.com/sid-ak/study_assistant)
implements it, with a link to the source, and each section closes with what the project actually
does. Where the project's description and its code disagree, the section says so: those gaps are
the ones an interviewer finds, and the accurate claim is stated alongside.

Code links are pinned to commit
[`cb54a4b`](https://github.com/sid-ak/study_assistant/tree/cb54a4b8647d9477c3cd242856ede811db46019c),
so the line numbers stay correct.

| Approach | How it finds the nearest vectors | Cost per query | Result |
| -------- | -------------------------------- | -------------- | ------ |
| Exact (flat) search | Compares the query with every stored vector | Grows linearly with the number of vectors | Always the true nearest vectors |
| Approximate search (HNSW) | Walks a graph of vectors toward the query | Grows roughly with the logarithm of the number of vectors | Usually the true nearest, occasionally misses one |
| Lexical search (BM25) | Looks up the query's words in an inverted index | Grows with how many passages contain the words | Exact words and identifiers, no synonyms |
| Hybrid search | Runs both and fuses the ranked lists | The sum of both searches | Meaning and exact words |

## Dense search

Why it matters: retrieval decides what the model is allowed to see. The model answers only from
the passages it is handed, so a passage retrieval misses is one the answer cannot use.

Matching the question's words against the documents is the obvious approach, and it fails often,
because a question and its answer are usually written in different words. "How do I turn on
AddressSanitizer?" and "enable ASan with `-fsanitize=address`" share no useful word. Dense search
works anyway, because it compares meaning rather than spelling. That is why it is the first stage
in most RAG systems, and the first thing study_assistant built.

It works in three steps:

1. Embed the question with the embedding model used for the passages, giving a query vector.
2. Score every candidate passage by its distance to the query vector, usually cosine distance.
3. Return the `k` passages with the smallest distance, nearest first.

- Dense: the vectors are long lists of numbers, almost all non-zero. The alternative, covered
  later on this page, represents text by which words it contains, which leaves mostly zeros.
- Strength: meaning matches even without shared words, as in the AddressSanitizer example above.
- Weakness: exact identifiers. Two error codes that differ by one digit get nearly the same vector,
  because the model was never trained to keep them apart, so a search for one can return passages
  about the other first.

In study_assistant the scoring step is not Python at all. The Python side does three small things:
embed the question, pass the vector to the store, and turn each distance into a relevance. Postgres
does the rest.

- `<=>` is pgvector's cosine distance operator, so the database compares the vectors itself and
  returns only the few rows asked for, instead of sending every stored vector back to Python.
- `relevance` is `1 - distance`, so a relevance near 1 means the two vectors point almost the same
  way. Later stages read that one number and never the raw distance.
- The store sits behind an interface rather than being called directly, so an in-memory version can
  stand in for Postgres in tests.

The Python entry point embeds the question, asks the store for the nearest rows, and wraps each row
so the caller gets a relevance instead of a raw distance.

??? example "search"

    ```python
    def search(
        query: str,
        *,
        embedder: EmbedderProtocol,
        store: StoreProtocol,
        limit: int,
        ef_search: int | None = None,
    ) -> list[RetrievedChunk]:
        """The first step: embed ``query`` and return the ``limit`` nearest chunks, nearest first.

        Each chunk's relevance is its cosine similarity to the query, 1 minus its distance.
        """
        query_embedding = embedder.embed_query(query)
        rows = store.search_dense(query_embedding, limit=limit, ef_search=ef_search)
    ```

Source: [`packages/rag_core/src/rag_core/retrieve/dense.py:52-78`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/retrieve/dense.py#L52-L78)

The SQL query asks for each chunk's columns plus its distance from the query vector, skips chunks
the current model has not embedded, sorts by that distance, and stops at the limit. The vector is
wrapped in `Vector(...)` because a plain Python list has no `<=>` operator.

??? example "query"

    ```python
    query = sql.SQL(
        "SELECT id, document_id, content, metadata, {column} <=> %(query)s AS distance "
        "FROM chunks WHERE {column} IS NOT NULL "
        "ORDER BY {column} <=> %(query)s LIMIT %(limit)s"
    ).format(column=column)
    # A plain list binds as double precision[], which has no <=> operator; Vector binds as
    # pgvector's own type.
    parameters = {"query": Vector(list(query_embedding)), "limit": limit}
    ```

Source: [`packages/rag_core/src/rag_core/store/client.py:217-243`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/store/client.py#L217-L243)

## Exact nearest-neighbor search

Why it matters: this is the baseline every faster method is judged against. Knowing the true
nearest passages is the only way to tell whether a quicker search quietly dropped one, and at a
small collection size it is also fast enough to use on its own, so it tells a project when it does
not need an index at all.

The method is the obvious one: compute the distance from the query to every stored vector and keep
the smallest few. Cost is one distance computation per stored vector, each touching every number in
it, so a million 384-number vectors is about 384 million multiply-adds for a single question.
Below tens of thousands of vectors that still finishes in milliseconds, and there is nothing to
build or tune.

study_assistant has exactly this, but not in the database. It is the in-memory store the tests run
against, and it exists so one set of tests can check both stores.

- Postgres reaches its answer through an index; the in-memory store compares against every chunk,
  so it always returns the true nearest.
- Because the two reach ties differently, those shared tests check which chunks come back rather
  than the order they come back in.

The scan sorts `(distance, position, chunk)` tuples rather than the chunk dictionaries. Sorting by
distance first and falling back to insertion position keeps the result stable, and means two
dictionaries are never compared against each other.

??? example "search_dense (in-memory store)"

    ```python
    # Each entry is (distance, insertion position, chunk). Sorting the tuples orders by
    # distance first and breaks ties by position, so the chunk dicts are never compared.
    scored: list[tuple[float, int, dict[str, Any]]] = []
    position = 0
    for chunk in self.chunks.values():
        embedding = chunk["embeddings"].get(self.embedder.model_id)
        if embedding is not None:
            distance = cosine_distance(query_embedding, embedding)
            scored.append((distance, position, chunk))
        position += 1
    scored.sort()
    ```

Source: [`packages/rag_core_testing/src/rag_core_testing/store.py:271-303`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core_testing/src/rag_core_testing/store.py#L271-L303)

## Approximate nearest-neighbor search

Why it matters: the cost of comparing against every vector grows with the collection, so on a large
corpus the search becomes the slowest part of answering a question. Approximate search is how
retrieval stays fast as a corpus grows, and it is the reason vector databases exist at all. The
price is that it can miss a passage it should have found, which is a real risk to answer quality
and has to be measured rather than assumed.

Approximate search compares the query against a small, well-chosen subset of the stored vectors
instead of all of them. Quality is measured as recall against an exact search: the share of the
truly nearest passages that the approximate search also returned.

In study_assistant that measurement came out at 1.000 at every setting tried, at about half a
millisecond per query. The honest reading is not that the index is well tuned, but that a
collection of 83 chunks is too small to have any approximation error to lose.

## HNSW

Why it matters: this is the index nearly every vector database uses, pgvector included, so a
question about how vector search works is in practice a question about what HNSW does. It is also
the thing whose settings appear in the next section, and they only make sense once the shape of the
index is clear.

Enough of the mechanism to discuss it:

- The graph: each stored vector is a node linked to its near neighbors plus a few far ones. A walk
  that always steps to whichever neighbor is closest to the query reaches the query's neighborhood
  in a few steps, rather than scanning everything.
- The layers: nodes sit on stacked layers, every node on the bottom one and exponentially fewer on
  each layer above, like the express lanes of a skip list. A search enters at the top, walks until
  it cannot get closer, drops a layer, and repeats. On the bottom layer it widens the search to
  collect the candidates it returns.

That is the depth this project needs, because it builds the index and changes nothing inside it.

Registering an embedding model adds that model's column and builds its index in the same step, one
index per model. The index is told to use cosine distance, which is what makes it able to serve the
dense query from earlier on this page.

??? example "register"

    ```python
    conn.execute(
        sql.SQL("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS {} vector({})").format(
            sql.Identifier(column), sql.Literal(dimension)
        )
    )
    conn.execute(
        sql.SQL(
            "CREATE INDEX IF NOT EXISTS {} ON chunks USING hnsw ({} vector_cosine_ops)"
        ).format(sql.Identifier(embedding_index(column)), sql.Identifier(column))
    )
    ```

Source: [`packages/rag_core/src/rag_core/store/embedders/client.py:52-61`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/store/embedders/client.py#L52-L61)

This is also the sharpest gap between how the project is described and what actually runs. The
index exists, and it is the right kind of index, but Postgres does not use it: at 83 chunks the
planner decides scanning the table is cheaper, so dense search is exact in practice and the index
only gets exercised when a query forces it.

- Accurate about the schema: an HNSW index is built per embedding column, with cosine distance.
- Not accurate about the query: at this size nothing goes through it.
- So the claim to make is that the index is in place and earns nothing yet, and that the recall
  figure in the previous section was measured with it forced.

## HNSW parameters: m, ef_construction, and ef_search

Why it matters: these are the only real knobs on vector search, and the useful distinction is which
of them can change per query and which requires rebuilding the whole index. Mixing those up turns
a one-line experiment into an afternoon of re-indexing.

| Parameter | Set when | Controls | Raising it |
| --------- | -------- | -------- | ---------- |
| `m` | The index is built | How many links each node keeps per layer | Better recall, a larger index, slower inserts |
| `ef_construction` | The index is built | How many candidates are considered when linking a new node | A better-connected graph, slower inserts |
| `ef_search` | Per query | How many candidates the bottom-layer search keeps | Better recall, slower queries |

- `m` and `ef_construction` shape the graph itself, so changing either means building the index
  again. pgvector's defaults are 16 and 64.
- `ef_search` is the one that matters in practice, because it changes per query and needs no
  rebuild. A longer candidate list explores more of the graph before stopping, so it misses a true
  neighbor less often and takes longer. pgvector defaults it to 40.
- It also caps the results: the search can only return candidates it kept, so asking for five
  results needs an `ef_search` of at least five.
- A small collection hides all of this, because even a short candidate list covers most of the
  graph.

In study_assistant, `m` and `ef_construction` are left alone, and that is worth saying as a choice
rather than an oversight: with the planner skipping the index at this size, a rebuild could not
have been measured. `ef_search` is wired from the command line down into the query, and sweeping it
from 5 to 100 moved neither recall nor latency.

The cap on results is enforced in code rather than left as a note, so a search that could not
possibly return enough results fails before it runs.

??? example "check_search"

    ```python
    check_limit(limit)
    if ef_search is not None:
        if ef_search < 1 or ef_search > MAX_EF_SEARCH:
            raise ValueError(f"ef_search must be 1 to {MAX_EF_SEARCH}, not {ef_search}.")
        if ef_search < limit:
            raise ValueError(
                f"ef_search ({ef_search}) must be at least limit ({limit}), "
                "or the search returns fewer results than asked for."
            )
    ```

Source: [`packages/rag_core/src/rag_core/store/validation.py:46-67`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/store/validation.py#L46-L67)

Setting the value per query uses `set_config` rather than `SET`, because only `set_config` accepts
a bound parameter. Its third argument limits the setting to the current transaction, which is the
detail worth volunteering: a session-wide setting would leak into the next search that reuses the
same pooled connection.

??? example "search_dense (ef_search)"

    ```python
    if ef_search is not None:
        # SET cannot take a bind parameter; set_config can. The third argument, true,
        # makes the setting local to the current transaction.
        conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(ef_search),))
    ```

Source: [`packages/rag_core/src/rag_core/store/client.py:217-243`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/store/client.py#L217-L243)

## Where vector indexes constrain a design

Why it matters: a vector index is not a general-purpose index. It serves one shape of query, and a
schema designed without knowing that ends up with an index the database silently ignores. These
three constraints are the ones that shape real decisions.

- Fixed size: an index is built for one vector length, so one index serves one embedding model.
  Changing models means building a new one.
- Filters: a query that also filters, say by document type, can come back short, because the index
  hands over a fixed number of candidates and the filter then throws most of them away.
- Ordering: the index can only order by distance. Asking the database to sort by a second column as
  well can stop it using the index at all.

Two of the three shaped this schema directly. The fixed size is why every model gets its own column
and its own index, which is what made adding a second embedding model an addition rather than a
migration. The ordering constraint is why the dense query sorts by distance and nothing else,
recorded in the method's own docstring:

> `ORDER BY <column> <=> query LIMIT n` is the shape the column's HNSW index serves, so the search
> is approximate once the planner uses the index. No tie-breaking column is added to the
> `ORDER BY`: a second sort key stops Postgres from using the index.

Source: [`packages/rag_core/src/rag_core/store/client.py:217-243`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/store/client.py#L217-L243)

The filter constraint is the one never met, and the reason is simply that nothing filters yet. The
`WHERE ... IS NOT NULL` clause in that query is not a user filter but a guard for chunks a newly
added model has not embedded, and it costs nothing. A per-user or per-document filter was never
needed because the tool serves one person from a command line; adding one would bring the problem
above back into play.

## Lexical search

Why it matters: this is the answer to why a system would use more than one kind of search. Dense
search compares meaning, which is exactly why it is careless about spelling, and a technical corpus
is full of strings where the spelling is the whole point. Error codes, build flags and function
names differ from each other by a character or two, and a model that was never trained to tell them
apart will treat them as near-identical. Lexical search has the opposite profile: it matches those
strings exactly and understands nothing, so a system that runs both covers both failures.

It ranks passages by the words they share with the query, and needs no model at all. An inverted
index maps each word to the passages containing it, so finding every passage with a given word is a
lookup rather than a scan.

- Normalizing: text is split into words, lowercased, and usually stemmed, cutting words to a common
  root so that "caching" and "cached" both become "cach". Very common words such as "the" and
  "what" are dropped, since nearly every passage has them.
- Strength: exact strings, matched character for character.
- Weakness: no sense of meaning. "How do I turn on AddressSanitizer?" will not match a passage that
  says "enable ASan" unless they happen to share a word.

In study_assistant, Postgres supplies all three parts: the inverted index, the stemming and the
stop-word list. So the whole of lexical search is one statement.

- Each chunk has a generated column holding its stemmed words, indexed, and it was already in the
  schema, so nothing had to be migrated when lexical search was added.
- Stemming also splits a flag into its parts, which is why `--config=asan` can be matched on
  `config` and `asan`.

The one part worth explaining unprompted is the rewrite in the middle of it. The query parser joins
the question's words with AND, which a full sentence almost never satisfies, so each AND is
replaced with OR. The query then matches a passage containing any of the words, and the ranking
function still puts passages containing more of them higher.

??? example "search_lexical"

    ```python
    def search_lexical(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` chunks containing words of ``query``, best ``ts_rank`` first.

        ``plainto_tsquery`` stems the query and drops stop words, joining the rest with AND, which a
        full question rarely satisfies. Replacing each ``&`` with ``|`` makes it match any of the
        words; ``ts_rank`` then scores chunks that contain more of them, more often, higher. The
        ``tsv`` column and its GIN index hold each chunk's stemmed words.
        """
        check_limit(limit)
        query_sql = (
            "SELECT id, document_id, content, metadata, ts_rank(tsv, q) AS score "
            "FROM chunks, "
            "CAST(replace(plainto_tsquery('english', %(query)s)::text, ' & ', ' | ') AS tsquery) q "
            "WHERE tsv @@ q ORDER BY score DESC LIMIT %(limit)s"
        )
    ```

Source: [`packages/rag_core/src/rag_core/store/client.py:199-215`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/store/client.py#L199-L215)

## TF-IDF and BM25

Why it matters: BM25 is the standard way to score lexical search, so claiming lexical search
invites questions about it. The project implements neither TF-IDF nor BM25, and the resume says
BM25, which makes this the gap to get right before anything else on this page.

BM25 scores a passage from three parts:

- Term frequency: how often a query word appears in the passage.
- Inverse document frequency: a weight that is high for words few passages contain, so a rare error
  code identifies a passage far better than a word like "build". TF-IDF is these two multiplied,
  summed over the query's words.
- Two corrections, which are what make it BM25 rather than TF-IDF: repeated words stop helping
  after a while, so the tenth occurrence counts for much less than the second, and scores are
  adjusted for passage length, so a long passage cannot win just by containing more words.

What study_assistant has instead is `ts_rank`, Postgres's own ranking function, and the three
differences are:

- It weighs term frequency, and a related function would add word proximity.
- It has no inverse document frequency, so a rare error code counts no more than a common word.
- It makes no adjustment for repetition or passage length.

Why real BM25 was not built:

- The stemmed-word column and its index were already in the schema, so lexical search cost one
  query and no migration at all. Real BM25 in Postgres needs an extension, or scoring in the
  application, against a corpus of 83 chunks.
- At that size almost every word is rare, so the missing inverse document frequency changes very
  little. It is what would matter first on a larger corpus, since it is exactly the part that makes
  an error code outrank a common word.

So the accurate claim is BM25-style lexical search through Postgres full-text search. Saying BM25
without that qualifier invites a question whose honest answer undercuts it.

## Hybrid search and Reciprocal Rank Fusion

Why it matters: the two kinds of search fail in opposite ways, so running both covers more
questions than either alone. The obstacle is that their scores cannot be compared. One returns a
distance between vectors and the other a relevance score of its own, on different scales, so adding
them is meaningless. Reciprocal Rank Fusion is the standard way around it: ignore the scores and
use only each passage's position in each list.

- Each list contributes `1 / (60 + rank)` for every passage it ranked, and the contributions are
  summed. The 60 is the convention.
- Rank 1 scores 1/61 and rank 10 scores 1/70, so a passage both lists place moderately high beats
  one that only a single list puts first. Agreement is rewarded.
- Positions need no calibration, so any two searches can be fused, and a list whose scores happen
  to be large cannot dominate.
- The alternative, a weighted sum of the two scores, would need the scores normalized per query and
  a weight to tune. Fusion by rank has one constant and needs no tuning, which matters when a
  ten-question test set cannot justify tuning more.

study_assistant fuses by rank for exactly that reason. Its fusion also tracks the order in which
passages were first seen, so that passages with equal sums keep a stable order and two runs never
disagree.

??? example "fuse"

    ```python
    def fuse(rankings: list[list[RetrievedChunk]], *, limit: int) -> list[RetrievedChunk]:
        """Merge ranked lists by Reciprocal Rank Fusion and keep the ``limit`` best.

        Each chunk scores ``1 / (RRF_K + rank)`` in every list it appears in, with ranks counted from 1,
        and the sums are its fused relevance. Only positions are used, so lists scored on different
        scales, such as cosine distances and ``ts_rank``, never need to be compared. A chunk keeps the
        first dense distance it was found with. Equal sums keep the order of first appearance.
        """
        fused_score: dict[UUID, float] = {}
        first_seen: dict[UUID, int] = {}
        chunk_by_id: dict[UUID, RetrievedChunk] = {}
        for ranking in rankings:
            for rank, chunk in enumerate(ranking, start=1):
                fused_score[chunk.id] = fused_score.get(chunk.id, 0.0) + 1.0 / (RRF_K + rank)
                if chunk.id not in first_seen:
                    first_seen[chunk.id] = len(first_seen)
    ```

Source: [`packages/rag_core/src/rag_core/retrieve/dense.py:101-128`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/retrieve/dense.py#L101-L128)

Retrieval runs as three steps, and only the first always happens. Dense search fetches a pool of
candidates, fusion merges a lexical pool into it when hybrid search is on, and a reranking model,
when there is one, picks and orders the handful finally returned. Reranking is a topic of its own,
covered in [Reranking](06-reranking.md). Each pool holds 20, fusion keeps
20, and 5 come back. Because the last step can only choose among candidates it was handed, the
pool size sets the ceiling on everything it could possibly find.

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

Source: [`packages/rag_core/src/rag_core/retrieve/dense.py:152-205`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/retrieve/dense.py#L152-L205)

Hybrid search is built, measured, and switched off by default. The measurement is the interesting
part rather than a disappointment. The columns below are retrieval quality, then latency at the
median and at the slow tail; all four are defined in [Evaluation](09-evaluation.md).

| Run | Recall@5 | MRR | p50 | p95 |
| --- | -------- | --- | --- | --- |
| Dense | 0.90 | 0.88 | 26.0 ms | 41.6 ms |
| Dense, reranked | 0.95 | 0.83 | 283.1 ms | 417.5 ms |
| Hybrid, reranked | 0.95 | 0.83 | 330.3 ms | 451.4 ms |

- Fusion changed nothing once reranking was on, for about 47 ms more at the median. Every expected
  section came back at the same position, and only one unlabeled fifth result moved.
- The reason is the pool. Twenty dense candidates out of 83 chunks is about a quarter of the whole
  corpus, so they already contained everything lexical search would have added.
- It does work in isolation. With reranking off, searching for a bare error code misses its
  defining section in the dense top three and finds it second under hybrid search, at a fused score
  of exactly 1/61, which only a first place in the lexical list can produce.
- So the claim to make is that it is built, behind a setting, measured, and shipped off because it
  bought nothing at this corpus size. On a larger corpus, where the answer can fall outside the
  dense pool, lexical search becomes the only way it reaches the final step at all.

The order of the work follows from all of this: start with exact search while the collection is
small, add an index when exact search gets slow, leave the build-time settings alone, and tune the
per-query one against measured recall and latency. Add lexical search when questions contain exact
strings, fuse by rank, and measure whether fusion changes the final results before leaving it on.
Here the measurement is what decided it, and the answer was no.
