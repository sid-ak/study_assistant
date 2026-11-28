# 04. Chunking

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

Chunking splits each document into passages before they are embedded and stored. The passage, not
the document, is the unit that retrieval ranks and that generation reads, so how documents are
split decides what a search can find and what context a language model receives. This page covers
why documents are split, the main ways to split them, and how chunk size trades precision against
context.

| Strategy | Splits at | Strength | Weakness |
| -------- | --------- | -------- | -------- |
| Fixed-size | Every N characters or tokens | Simple, predictable sizes, works on any text | Cuts through sentences, tables, and code |
| Fixed-size with overlap | Every N tokens, repeating the last M | A sentence on a boundary appears whole in at least one chunk | Stores repeated text, and near-duplicate chunks can crowd results |
| Structure-aware | Headings, paragraphs, code blocks | Chunks match units an author wrote, and carry their section names | Uneven sizes, and needs a parser per format |
| Semantic | Where the meaning between sentences changes | Boundaries follow topic shifts | Costs an embedding per sentence while indexing, and its thresholds need tuning |

## Why documents are split

Why it matters: chunking decides what a retrieval system can return, so it quietly sets a limit on
every answer. A chunk is the smallest thing that can be found and the smallest thing that can be
cited, and no later stage can recover a boundary drawn in the wrong place.

Three limits force the split:

- Embedding input limit: an embedding model reads a fixed number of tokens, often 512, and drops
  the rest. A whole document embedded at once is represented only by its first few hundred tokens.
- Precision of one vector: one vector summarizes everything in its text. A vector for a long
  document that covers ten topics sits between all ten, close to none of them, so a question about
  one topic finds it poorly.
- Generation budget: a language model's context window has room for a limited amount of retrieved
  text. Returning five focused passages uses that room better than returning one long document.

## Fixed-size chunking and overlap

Why it matters: this is the default in most tutorials and libraries, so it is the approach to be
able to compare against. Knowing why it was not used here is more useful than knowing how it
works.

The simplest splitter takes every N tokens, or words, as one chunk. Overlap repeats the last few of
each chunk at the start of the next.

Splitting "the linker failed because libpthread was not linked on the oldest image" into windows of
five words, each sharing two with the one before, gives:

```text
the linker failed because libpthread
because libpthread was not linked
not linked on the oldest
the oldest image
```


- Mechanism: each window starts `size - overlap` words after the previous one, so neighboring
  windows share `overlap` words.
- Why overlap helps: without it, "because libpthread was not linked" would be cut in half, and
  neither half alone says what failed. With it, the phrase appears whole in the second chunk.
- What it costs: an overlap of 20 percent stores and embeds about 20 percent more text, and two
  neighboring chunks can both rank in the top results while saying nearly the same thing.
- Where it fails: a fixed window ignores structure. It can split a code block, a table row, or a
  list from the sentence that introduces it.

study_assistant does not chunk this way, and the reason is that its corpus is markdown with
headings. Fixed-size splitting throws away a boundary the author already wrote, and the overlap
needed to repair that is duplicated text in the index. With real structure available there was
nothing to recover, so no overlap is used anywhere in the project.

## Structure-aware chunking

Why it matters: a document's author already marked where the topics change, by writing headings.
Using those boundaries is cheaper than inferring them and produces chunks a person would recognise,
which is also what makes them citable.

Documents written by people already have boundaries: headings, paragraphs, list items, and code
blocks. A structure-aware chunker splits at those boundaries.

- Sections first: each heading starts a new section, and a chunk never crosses into the next
  section. Short sections become one chunk each.
- Then the largest boundary that fits: a section over the size budget is split between paragraphs
  or code blocks first, then between lines, and only as a last resort between words.
- Code blocks stay whole: a fenced code block is one unit, and a `#` line inside it is a shell
  comment, not a heading. A parser that tracks fences avoids both mistakes.
- Heading paths as context: a chunk taken from "Bazel > Remote cache > Troubleshooting" means more
  with that path than without it. Putting the heading path at the start of the chunk's text lets
  the embedding and any keyword index see it. Storing it as metadata lets a citation point to the
  section.

> A runbook has a section per incident, each with the same subsections: Symptom, Cause, Fix. A
> fixed-size splitter mixes the end of one incident with the start of the next. A structure-aware
> splitter keeps each Fix with its own incident, and the heading path says which incident it is.

This is what study_assistant does, and the parts of it worth explaining are the breadcrumb and the
fallback.

- Every chunk stays inside one section. A section short enough to fit the budget becomes a single
  chunk.
- Each chunk begins with its heading path, joined into one breadcrumb line, so the text that gets
  embedded says where in the document it sits. A chunk about a flag inside a release note carries
  the release's name, which a bare paragraph would not.
- Each chunk records its source, its section, its full heading path and its position, which is what
  makes a result citable and lets a document's chunks be matched against a label later.
- A section too long for the budget is split at the largest boundary that fits: between paragraphs
  or code blocks first, then between lines, then between words. The split never crosses into
  another section.

The chunker walks the parsed sections and emits chunks per section, taking the last heading as the
section's name and prepending the whole path to the body.

??? example "HeadingChunker.chunk"

    ```python
    def chunk(self, markdown: str, source: str) -> list[TextChunk]:
        """Split ``markdown`` into chunks that each stay inside one section."""
        chunks: list[TextChunk] = []
        for section in parse_sections(markdown):
            headings = list(section.headings)
            if headings:
                section_name = headings[-1]
            else:
                section_name = ""
            for body in self.split_section(section.text):
                if headings:
                    content = BREADCRUMB_SEPARATOR.join(headings) + "\n\n" + body
                else:
                    content = body
                metadata = {
                    "source": source,
                    "section": section_name,
                    "headings": headings,
                    "chunk_index": len(chunks),
                }
                chunks.append(TextChunk(content=content, metadata=metadata))
        return chunks
    ```

Source: [`packages/rag_core/src/rag_core/ingest/chunking.py:104-126`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/ingest/chunking.py#L104-L126)

The packing step is where the word budget is enforced. It adds whole units to a group until the
next one would overflow, then starts a new group. A single unit larger than the budget still
becomes a group of its own, because the alternative is dropping text.

??? example "pack"

    ```python
    def pack(units: list[str], separator: str, max_words: int) -> list[str]:
        """Join consecutive ``units`` with ``separator`` into groups of at most ``max_words`` words.

        Units are added to the current group until the next one would overflow it. A unit that is over
        the budget on its own still becomes a group of its own.
        """
        groups: list[str] = []
        current: list[str] = []
        current_words = 0
        for unit in units:
            words = count_words(unit)
            if current and current_words + words > max_words:
                groups.append(separator.join(current))
                current = []
                current_words = 0
            current.append(unit)
            current_words += words
        if current:
            groups.append(separator.join(current))
        return groups
    ```

Source: [`packages/rag_core/src/rag_core/ingest/chunking.py:47-66`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/ingest/chunking.py#L47-L66)

## Semantic chunking

Why it matters: it is the sophisticated-sounding option, so it tends to come up, and the useful
answer is about what it costs rather than what it does.

A semantic chunker embeds each sentence and starts a new chunk where the similarity between
consecutive sentences drops, on the assumption that a drop marks a change of topic.

- Benefit: boundaries follow meaning even in text with no headings, such as transcripts.
- Cost: indexing embeds every sentence once to find boundaries, and again for the chunks
  themselves. The similarity threshold has to be tuned on the collection.
- Combination: it is often applied only inside sections that a structure-aware pass found too
  long.

Not done here, and the reason is the cost against the alternative. The corpus has headings, so the
boundaries were already available for free, and a threshold tuned on 17 documents would not be
evidence of anything. The fallback splitting described above handles the long-section case that
semantic chunking would otherwise be brought in for.

## Choosing a chunk size

Why it matters: the size is the one number in chunking that has to be chosen, and the trap is that
the model's limit is counted in tokens while a budget is naturally written in words. For technical
text those two differ by more than people expect.

| Smaller chunks | Larger chunks |
| -------------- | ------------- |
| Each vector is about one point, so matching is precise | Each chunk carries more surrounding context |
| More chunks to store, embed, and search | Fewer chunks, cheaper indexing |
| A retrieved chunk may lack the context needed to answer | A relevant sentence is diluted by the rest of the chunk |
| More results fit in a generation prompt | Fewer results fit in a generation prompt |

- Measure in tokens, not words: the embedding model's limit is in tokens, and technical text
  produces more tokens per word than prose. A word budget needs headroom for the most token-dense
  text in the collection, such as code and log excerpts.
- Common range: 100 to 400 tokens per chunk is a typical starting point for question answering.
  The right size for a collection is the one its retrieval evaluation favors.
- Keep provenance: each chunk should record its source document, its section, and its position, so
  results can be cited and a document's chunks can be replaced together when it changes.

study_assistant's budget is 120 words, and the number came from a measurement rather than a guess.
Across the corpus the median chunk is about 1.8 tokens per word, but code and log excerpts reach
4.1. At that ratio a 200-word budget would exceed the model's 512-token limit and be truncated
silently, so the budget is set low enough that even the densest chunk fits. The resulting chunks
measure 79 tokens at the median and 221 at the largest.

The practical rule is to split at the structure the author already wrote, keep every chunk under
the embedding model's token limit with headroom for dense text, and record where each chunk came
from.
