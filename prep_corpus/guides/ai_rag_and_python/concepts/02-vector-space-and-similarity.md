# 02. Vector Space and Similarity

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

Retrieval in a RAG system compares a question with stored passages by comparing lists of numbers.
An embedding model turns each piece of text into a vector, and the passages whose vectors are
closest to the question's vector are treated as the most relevant. This page defines what a vector
is, the ways to measure how close two vectors are, and why one of them is the right choice for text.

| Measure | Formula | Range | More similar means | Sensitive to vector length |
| ------- | ------- | ----- | ------------------ | -------------------------- |
| Dot product | sum of `a[i] * b[i]` | Any real number | Larger | Yes |
| Euclidean distance | square root of the sum of `(a[i] - b[i])²` | 0 and up | Smaller | Yes |
| Cosine similarity | dot product divided by both lengths | -1 to 1 | Larger | No |
| Cosine distance | 1 minus cosine similarity | 0 to 2 | Smaller | No |

Almost none of this arithmetic is written out in study_assistant, and that is worth saying up
front. The database computes it, so the page's job is to explain what the database is doing and why
cosine is the measure asked for. The one place the project does write it by hand is its test store,
which appears below.

## Vectors and dimensions

Why it matters: a vector is the only thing a retrieval system actually compares. Every later idea
on this page, and the size of every database column in the project, follows from what a vector is.

A vector is an ordered, fixed-length list of numbers. Each position is called a dimension, and the
number of positions is the vector's dimension. The project's default embedding model produces 384
numbers per piece of text; its second produces 768.

- Geometric view: a vector of dimension `n` is a point in `n`-dimensional space, or an arrow from
  the origin to that point. Two dimensions can be drawn on paper, and the same arithmetic works
  unchanged in 384.
- Direction and length: an arrow has a direction, where it points, and a length, how far it
  reaches. The measures below differ in whether they look at direction only, or at both.
- Fixed per model: a model always outputs the same dimension, so a database column and its index
  are created for that one size. This is why the project gives each model its own column.
- The numbers are not readable: individual dimensions do not correspond to features a person could
  name, and two models use unrelated coordinate systems, so their vectors cannot be compared with
  each other at all.

## Dot product and Euclidean distance

Why it matters: these are the two obvious ways to compare vectors, and understanding why neither is
used for text is what explains the choice that was made. Both are sensitive to a vector's length,
and length is the part of an embedding that carries the least meaning.

- Dot product: multiply matching positions and add the results. Positions where both vectors are
  large and share a sign add a lot; positions whose signs differ subtract. The total grows when two
  vectors point the same way, and also grows when either vector is simply longer.
- Euclidean distance: the straight-line distance between the two points, the Pythagorean theorem
  extended to any number of dimensions.

The length sensitivity is the problem. `[3, 4]` and `[6, 8]` point in exactly the same direction,
so for retrieval they should count as identical, but their dot product is larger than either
vector's with itself scaled differently, and their Euclidean distance is 5 rather than 0. A measure
that treats "twice as far along the same line" as a difference in meaning will rank by something
that is not meaning.

Neither appears in study_assistant. There was no reason to implement them: the comparison happens
inside the database, and the measure it is asked for is the one below.

## Cosine similarity and cosine distance

Why it matters: this is the measure the project actually uses, the one the database index is built
for, and the one the agent's relevance threshold is expressed in. It is also the answer to the
question of why a vector search uses cosine at all.

Cosine similarity divides the dot product by both lengths, which cancels the lengths out and leaves
only the angle between the two vectors.

- Range: 1 means they point the same way, 0 means they are perpendicular and so unrelated, and -1
  means they point in opposite directions.
- Length independence: `[3, 4]` and `[6, 8]` score exactly 1.0, because only direction is compared.
  This is what suits text, where direction carries the meaning and length carries little.
- Cosine distance is `1 - cosine similarity`, from 0 for the same direction to 2 for opposite.
  Databases rank by distance, where smaller means closer, and ranking by smallest cosine distance
  gives the same order as ranking by largest similarity.

study_assistant uses cosine throughout, and the choice is visible in three places that have to
agree.

- The index on each embedding column is created for cosine distance, so the database can use it.
- The dense query asks for cosine distance with pgvector's `<=>` operator.
- Every component above the database reports `1 - distance`, so what travels through the system is
  a similarity between 0 and 1 rather than a distance.

The one hand-written implementation is in the in-memory store the tests use, where there is no
database to do the work. It computes the dot product and both squared lengths in a single pass and
combines them at the end, and `strict=True` makes mismatched vector lengths an error rather than a
silently truncated comparison.

??? example "cosine_distance"

    ```python
    def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
        """``1 - cosine similarity`` of two non-zero vectors of the same length."""
        dot = 0.0
        a_squares = 0.0
        b_squares = 0.0
        for x, y in zip(a, b, strict=True):
            dot += x * y
            a_squares += x * x
            b_squares += y * y
        return 1.0 - dot / math.sqrt(a_squares * b_squares)
    ```

Source: [`packages/rag_core_testing/src/rag_core_testing/store.py:29-38`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core_testing/src/rag_core_testing/store.py#L29-L38)

## Normalization

Why it matters: it explains why a system can use the cheapest measure and still get the cosine
ranking, and it is the reason the distinction between the three measures mostly disappears in
practice.

Normalizing a vector divides each number by the vector's length, giving a unit vector: the same
direction, length 1. Once every vector has length 1:

- Cosine similarity is the dot product, because the division is by `1 * 1`.
- Euclidean distance follows cosine exactly, since for unit vectors the squared distance is
  `2 - 2 * cosine similarity`. A larger cosine always means a smaller distance, so the ranking is
  the same.
- A search system can therefore score with the dot product, the cheapest of the three, and get the
  cosine ordering for free.

Most text embedding models, including the ones here, already return normalized vectors. In
study_assistant nothing normalizes anything, and that is the correct amount of work: the model
returns unit-length vectors, so the step would be a no-op, and asking the database for cosine
distance is correct whether or not they are normalized.

## High-dimensional space

Why it matters: it is why retrieval is ranked rather than thresholded, and why a large collection
needs an index at all. Both consequences shape how the rest of the guide measures things.

Embedding vectors have hundreds of dimensions, and two properties of that space matter:

- Distances crowd together. As the dimension grows, the distances from a query to randomly spread
  points become similar to one another. Relevance then lives in small differences between scores,
  which is why ranking order matters more than any absolute score.
- Exact search gets expensive. Comparing a query against every stored vector costs the number of
  vectors times the dimension, which is why large collections use an approximate index instead, as
  [Retrieval](05-retrieval.md) describes.

The crowding is also why the project's one score threshold is modest in what it claims. The agent
treats a cosine similarity above a fixed value as "worth answering from", and the value was chosen
by looking at measured scores rather than reasoned about from the geometry, precisely because
absolute scores in high dimensions are hard to reason about.
