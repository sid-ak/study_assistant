# 01. RAG Overview

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

Why it matters: this is the page that says what the rest of the guide is building. Every later
page is one stage of the pipeline described here, so the shape of the whole thing is worth holding
before any single stage makes sense.

A language model answers from what it learned during training. That knowledge stops at a fixed date,
never includes private documents, and cannot be traced back to a source. Retrieval-augmented
generation (RAG) addresses all three limits with one change: before the model answers, the system
searches a document collection for passages relevant to the question and places them in the model's
input, with an instruction to answer from them. The model then works as a reader of supplied
evidence instead of as the only source of facts.

| Approach | Where the knowledge comes from | Updating the knowledge | Citations | Main cost |
| -------- | ------------------------------ | ---------------------- | --------- | --------- |
| Model alone | Training data, fixed at a cutoff date | Retrain or fine-tune the model | Not possible | Answers can be outdated or invented |
| Fine-tuning | Training data plus a custom training set | Run another training job | Not possible | Training compute, and facts blur into the model's weights |
| Long context | The whole document collection pasted into every request | Edit the documents | Possible | Every request pays for every token, and collections larger than the context window do not fit |
| RAG | A search over the collection, run per question | Re-index the changed documents | Each claim maps to a retrieved passage | A retrieval pipeline that must find the right passages |

## The problem RAG solves

Why it matters: these three limits are the reason the rest of the guide exists. Each stage in the
pipeline is there to address one of them, so naming them first makes the later work legible.

A language model is a function from input text to output text, with its parameters fixed after
training. Three limits follow from that:

- Knowledge cutoff: the model knows nothing written after its training data was collected.
- No private data: documents that were never public, such as internal runbooks or a course's lecture
  notes, were never in the training data.
- No provenance: an answer is generated from patterns in the model's weights, so there is no record
  of which source a statement came from. When the model has no relevant knowledge, it can still
  produce fluent text that is false. This is called a hallucination.

RAG changes where the facts come from. The model receives the relevant passages as part of its input
at question time, so the facts can be current, private, and traced to a specific passage.

> A support assistant for a software product answers questions about a release published last
> week. The model was trained before that release existed, but the release notes are in the indexed
> collection, so retrieval finds the relevant section and the answer cites it.

## The pipeline stages

Why it matters: this table is the map for the whole guide. Every other concept page is one row of
it, and the split between work done ahead of time and work done per question is what makes the
costs of a RAG system predictable.

A RAG system runs in two phases. Indexing happens ahead of time, once per document. Answering
happens per question.

| Phase | Stage | Input | Output |
| ----- | ----- | ----- | ------ |
| Indexing | Parsing | Files (markdown, PDF, slides) | Plain text with its structure, such as headings |
| Indexing | Chunking | Plain text | Passages small enough to retrieve and to fit in a prompt |
| Indexing | Embedding | Each passage | A vector of numbers representing the passage's meaning |
| Indexing | Storing | Passages and vectors | An index that can be searched by similarity |
| Answering | Query embedding | The question | A vector in the same space as the passages |
| Answering | Retrieval | The question's vector | The passages whose vectors are nearest to it |
| Answering | Reranking (optional) | The question and each candidate passage | The candidates re-ordered by a more precise relevance model |
| Answering | Generation | The question and the top passages | An answer that cites the passages it used |

- Parsing: extracts text from each file format and keeps structure that helps later, such as section
  headings and page numbers.
- Chunking: splits documents into passages. A passage that is too long dilutes its meaning and
  wastes space in the prompt. One that is too short loses the context needed to understand it.
- Embedding: an embedding model maps text to a vector, a fixed-length list of numbers, so that texts
  with similar meaning map to nearby vectors. [Vector Space and Similarity](02-vector-space-and-similarity.md)
  explains what "nearby" means.
- Storing: keeps each passage with its vector and its source, in an index built for finding the
  nearest vectors quickly.
- Query embedding: the question goes through the same embedding model as the passages. Vectors from
  different models are not comparable, so the question and the passages must share one model.
- Retrieval: finds the passages whose vectors are closest to the question's vector. Lexical search,
  which matches exact words, can run beside it and the two result lists can be combined.
- Reranking: a slower, more accurate model reads the question and each candidate passage together
  and scores their relevance. It runs only over a short candidate list because of its cost.
- Generation: the language model receives an instruction, the question, and the top passages, and
  writes an answer that cites the passages it relied on.

In study_assistant the two phases are two entry points. Indexing is one function over a folder, and
answering is a separate one per question, covered in [Retrieval](05-retrieval.md).

- Nothing is shared between them at run time except the database and the choice of embedding model,
  which both sides have to agree on.
- That agreement is checked rather than assumed: both entry points verify that the store and the
  embedding model refer to the same model before doing any work, because vectors from two models
  cannot be compared.

The indexing function walks the folder, and for each file decides whether there is anything to do
before spending time on it. It hashes the file's bytes and skips the file when a document with that
hash is already stored with its chunks, which is what makes re-running it over an unchanged folder
free. A file that cannot be decoded is recorded and skipped rather than stopping the run.

??? example "ingest_folder"

    ```python
    check_same_model(embedder, store)
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} is not a folder.")
    if chunker is None:
        chunker = HeadingChunker()

    report = IngestReport()
    for source, path in markdown_files(folder):
        data = path.read_bytes()
        file_hash = hashlib.sha256(data).hexdigest()

        stored = store.get_document_by_hash(file_hash)
        if stored is not None and store.get_chunks_by_document(stored["id"]):
            report.unchanged.append(source)
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # One file in another encoding must not stop the rest of the folder.
            report.unreadable.append(source)
            continue
        chunks = chunker.chunk(text, source=source)
    ```

Source: [`packages/rag_core/src/rag_core/ingest/pipeline.py:64-133`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/packages/rag_core/src/rag_core/ingest/pipeline.py#L64-L133)

## Retrieval is separate from generation

Why it matters: this is the single most useful idea for working on a RAG system, because it tells
you where to spend effort. The two halves fail differently, and a fix aimed at the wrong half
changes nothing.

The two halves of the pipeline fail in different ways, and they are measured separately:

- Retrieval failure: the passage that contains the answer is not among the retrieved passages. No
  model can then answer correctly from the supplied evidence. Retrieval quality is measured against
  a set of questions whose correct passages are known in advance.
- Generation failure: the right passage was retrieved, but the answer ignores it, misreads it, or
  adds claims it does not support. Generation quality is measured by checking each claim and
  citation against the passages that were supplied.

Measuring them separately shows where to spend effort. A pipeline that retrieves the right passage
for nine questions in ten but answers only six correctly has a generation problem, and a larger
retrieval model would not fix it.

study_assistant follows that split literally: it has one measurement harness for retrieval and a
separate one for the answers, described in [Evaluation](09-evaluation.md). Every tuning decision in
this guide was made on the retrieval numbers, which is the practical consequence of treating
retrieval as the part that sets the ceiling.

## Grounding and citations

Why it matters: grounding is what distinguishes a RAG answer from a confident guess, and citations
are what make that claim checkable by someone who was not there. Without them a system asks to be
trusted rather than verified.

An answer is grounded when every claim in it is supported by a retrieved passage. Citations make
grounding checkable: each answer lists which passages it used, so a reader, or an automated check,
can confirm that the cited passage exists in what was retrieved and says what the answer claims.
A citation is only as precise as the stored provenance. A system that records the source file and
section heading of every passage can cite a section. One that also records page numbers can cite a
page.

## Where RAG reaches its limits

Why it matters: knowing what retrieval cannot do prevents promising it. These are the question
shapes that a handful of retrieved passages cannot serve, however good the search is.

- Questions that need the whole collection: "summarize every change across all release notes" needs
  far more passages than fit in one prompt. Retrieval returns a handful of passages, not a corpus.
- Questions whose answer is spread across many passages: when each passage holds a fragment, the
  retriever has to find all of them, and missing one leaves the answer incomplete.
- Exact identifiers: dense embeddings capture meaning well but can miss exact strings such as error
  codes and command-line flags. Lexical search handles those, which is why many systems combine the
  two.
- Stale indexes: an answer is only as current as the last time the changed documents were
  re-indexed.

The practical rule is to treat RAG as a search system with a language model at the end. Most answer
quality is decided by whether retrieval finds the right passage, so a RAG system is built and
measured retrieval-first.
