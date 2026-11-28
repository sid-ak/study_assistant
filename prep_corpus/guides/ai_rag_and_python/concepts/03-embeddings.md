# 03. Embeddings

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

An embedding model turns a piece of text into a vector: a fixed-length list of numbers, placed so
that texts with similar meaning end up close together. Retrieval depends on that placement. A
question and the passage that answers it share few exact words, but a good embedding model maps
them to nearby vectors, so a nearest-vector search finds the passage.
[Vector Space and Similarity](02-vector-space-and-similarity.md) covers how "close" is measured.
This page covers how the vectors are produced and what decides their quality.

| Property | What it means | Why it matters for retrieval |
| -------- | ------------- | ---------------------------- |
| Dimension | The length of every vector the model outputs | Fixed per model, so stored vectors and indexes are tied to one model |
| Input limit | The most tokens the model reads from one text | Text past the limit is silently cut off and never influences the vector |
| Model size | The number of learned parameters | Larger models usually rank better, and cost more memory and time per text |
| Training objective | What the model was trained to place close together | A model trained on question and passage pairs suits search |
| Query instruction | Text some models expect in front of a query | Encoding queries differently from passages can improve ranking |

## From text to tokens

Why it matters: a token is the unit a model actually reads and the unit every size limit is
counted in, so a limit that looks generous in words can be tight in code. The project's chunk size
was chosen from a measured token-to-word ratio for exactly this reason.

A model does not read characters or whole words. A tokenizer first splits text into tokens: common
words become one token, and rare words, identifiers, and symbols are split into several pieces from
a fixed vocabulary.

```text
"the build failed"                     ->  the | build | failed                                   (3 tokens)
"AddressSanitizer"                     ->  address | ##san | ##iti | ##zer                         (4 tokens)
"--remote_upload_local_results=false"  ->  - | - | remote | _ | up | ##load | _ | local | _ |
                                           results | = | false                                    (12 tokens)
```

These splits come from the tokenizer of `bge-small-en-v1.5`, where `##` marks a piece that
continues the previous one. Each tokenizer has its own vocabulary, so the pieces differ between
models.

- Subwords: splitting rare words into known pieces lets a fixed vocabulary of tens of thousands of
  entries represent any text.
- Token counts are not word counts: a paragraph of plain English prose measured 1.1 tokens per
  word with that tokenizer, while the command-line flag above is one word and 12 tokens. Code,
  flags, paths, and log lines split into many pieces each. A size limit stated in tokens
  therefore holds far fewer words of code than of prose.
- Input limit: a model reads at most a fixed number of tokens, often 512. Most libraries truncate
  longer input without an error, so the end of a long passage contributes nothing to its vector.

## From tokens to one vector

Why it matters: retrieval compares one vector per passage, so something has to reduce a passage's
many token vectors to one. How that is done is a property of the model, and getting it wrong by
hand is a way to produce vectors that compare badly against the stored ones.

Most text embedding models are transformer encoders. An encoder reads all tokens at once and
outputs one vector per token, where each token's vector has been adjusted by every other token
around it. "Cache" in "remote cache endpoint" and in "CPU cache line" gets different vectors,
because the surrounding tokens differ.

One vector for the whole text is then taken from the per-token vectors, a step called pooling:

- CLS pooling: the tokenizer adds a special first token, and the model is trained so that this
  token's output vector summarizes the whole input. The BGE family of models uses this.
- Mean pooling: average the output vectors of all tokens. Many sentence-transformer models use
  this.

The pooled vector is usually normalized to length 1, so the dot product of two embeddings equals
their cosine similarity.

## Bi-encoders

Why it matters: this is the property that makes vector search fast enough to use. Because a passage
is embedded once, ahead of time, answering a question costs one embedding and one search no matter
how large the collection is. It is also the reason a second, slower kind of model is worth adding
later, covered in [Reranking](06-reranking.md).

A bi-encoder embeds the query and each document separately, with the same model, and compares the
two vectors afterward.

study_assistant's embedder is a bi-encoder, and the split shows in its two methods. Passages go
through one that takes a list and batches them, used once at ingestion. A query goes through a
second that embeds a single string, used per question. The query method is a one-line wrapper
around the passage one, which is what keeps the two sides in the same vector space by construction.

??? example "embed_documents and embed_query"

    ```python
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages, returning one unit-length vector per text, in order.

        Inputs longer than the model's limit (512 tokens for the bge models) are truncated.
        """
        if not texts:
            return []
        model = self.load()
        vectors: list[list[float]] = []
        for vector in model.embed(texts, batch_size=BATCH_SIZE):
            vectors.append(vector.tolist())
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed ``query_prefix`` followed by ``text``."""
        return self.embed_documents([self.query_prefix + text])[0]
    ```

Source: [`packages/rag_core/src/rag_core/embed/fastembed_embedder.py:78-93`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/embed/fastembed_embedder.py#L78-L93)

- Precomputation: documents are embedded once, when they are indexed. A question costs one
  embedding plus a vector search, however large the collection.
- Independence: because the two texts never see each other inside the model, the model cannot
  compare them word by word. All it can do is place each text in the vector space on its own.
  Subtle relevance, such as which of two similar passages actually answers the question, can be
  lost.
- Cross-encoders are the alternative: they read the query and one passage together and output a
  relevance score directly. They are more accurate and far slower, because nothing can be
  precomputed, so they are used to re-score a short candidate list that a bi-encoder retrieved.

## How the placement is learned

Why it matters: it explains what an embedding model is actually good at, and therefore where it
fails. A model learned the kinds of similarity its training pairs contained, which is why it can
match a paraphrase and miss an error code.

Embedding models for search are trained with contrastive learning. Training data is a large set of
pairs that belong together, such as a question and the passage that answers it, or a title and its
article.

- Objective: for each pair, the model is rewarded for placing the two vectors close together and
  for placing the query far from the passages of other pairs in the same training batch, which
  serve as negatives.
- Hard negatives: passages that look relevant but are not, added on purpose, teach the model finer
  distinctions than random negatives do.
- What this implies: a model learns the kinds of similarity its training pairs contained. A model
  trained mostly on web questions and answers may place two error codes that differ by one digit
  almost on top of each other, because nothing in its training rewarded separating them.

## Model size against quality

Why it matters: picking a model is the one decision that costs storage, latency and memory all at
once, and the honest answer about whether a bigger model helps can only come from measuring it on
the collection in hand. The project measured exactly this and kept the smaller model.

| Model | Dimension | Parameters | Relative cost |
| ----- | --------- | ---------- | ------------- |
| `bge-small-en-v1.5` | 384 | about 33 million | Baseline |
| `bge-base-en-v1.5` | 768 | about 110 million | About three times the compute per text, twice the storage per vector |
| `bge-large-en-v1.5` | 1024 | about 335 million | About ten times the compute per text |

- Quality: larger models usually score higher on public retrieval benchmarks, by a margin that is
  often small for English search tasks. Whether the gain holds on a specific collection is a
  question for that collection's own evaluation, not for a public leaderboard.
- Storage: each stored vector costs its dimension times 4 bytes as 32-bit floats, plus index
  overhead. Doubling the dimension doubles that.
- Latency and memory: compute per text grows with the parameter count. On a laptop CPU a small
  model embeds a short query in a few milliseconds.
- Quantization: storing a model's weights in fewer bits (for example 8-bit integers instead of
  32-bit floats) shrinks the model file and speeds up inference on CPUs, at a small cost in
  accuracy.

study_assistant ran this comparison rather than reasoning about it. The 768-dimension model was
registered beside the 384-dimension one, the stored chunks were embedded with both, and the same
questions were measured against each. Recall came out identical and the ranking was slightly worse,
while embedding a query took about three times as long, so the smaller model stayed the default.
The useful claim from that is not that small models are better, but that on an 83-chunk corpus the
difference was not measurable, and the measurement is what settled it.

The model is also loaded lazily: constructing the embedder only checks the model name, and the
first call downloads and loads it. This keeps importing the library and starting a process cheap,
which matters because a tool server is started per run.

??? example "load"

    ```python
    def load(self) -> TextEmbedding:
        """Return the model, downloading and loading it the first time it is needed."""
        if self._model is None:
            self._model = TextEmbedding(model_name=self._info.model_id)
        return self._model
    ```

Source: [`packages/rag_core/src/rag_core/embed/fastembed_embedder.py:72-76`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/embed/fastembed_embedder.py#L72-L76)

## Query and document prefixes

Why it matters: a prefix the model was trained with is part of the input, so getting it wrong
changes every query vector. It is a small detail that silently degrades retrieval, which is why it
is worth checking against the model card rather than assumed.

Search is asymmetric: queries are short questions and passages are longer statements. Some models
are trained with a fixed instruction in front of one side, and expect the same at search time.

```text
query:    "Represent this sentence for searching relevant passages: Which flag enables ASan?"
passage:  "Bazel: pass --config=asan to build and test with AddressSanitizer."
```

- Model-specific: E5 models expect `query: ` and `passage: ` prefixes on every input. BGE v1.5
  models recommend an instruction on short queries and none on passages, and state that leaving
  it out costs little.
- Consistency: the prefix is part of the input, so a query embedded with it and one embedded
  without it produce different vectors. Every query must be embedded the same way, and the choice
  should be measured on the collection rather than assumed.
- Libraries differ: some embedding libraries add a model's prefix automatically and some do not,
  so the actual behavior is worth checking against the model card.

In study_assistant the prefix is a configured string that defaults to empty, prepended to the query
and never to a passage, which is visible in `embed_query` above. With the BGE models that is the
documented choice, since their own guidance is that the instruction helps short queries a little
and omitting it costs little. Nothing here measured the difference, so the honest statement is that
the mechanism is in place and the value is unset.

## One model per vector space

Why it matters: it is the constraint that shapes storage. Because two models' vectors cannot be
compared, adding or changing a model is a re-embedding job, and whether that is painful depends on
a schema decision made long before.

Vectors from two different models are not comparable, even when their dimensions match, because
each model learned its own placement. Changing models therefore means re-embedding every stored
passage with the new model. Storage that keeps each model's vectors separate lets the old and new
models run side by side during that migration.

That is the schema study_assistant chose: one column and one index per registered model, so the
comparison in the previous section was an addition rather than a migration, and both models were
queryable at once while it ran. The pairing is also checked in code. Both the ingestion and the
retrieval entry points verify that the store and the embedder name the same model before doing any
work, because the failure they prevent is silent: comparing a query against another model's vectors
returns results, just meaningless ones.

The practical rule is to pick the smallest model that ranks well enough on the actual collection,
keep every input under the model's token limit, and embed queries exactly the way the model's
authors trained it to see them.
