# 09. Evaluation

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

Evaluation measures how well a retrieval system finds the passages that answer a question, and how
long it takes, on a fixed set of questions whose answers are known in advance. Without it, a change
to chunking, the embedding model, or the search method can only be judged by trying a few queries
by hand, which neither covers enough cases nor gives a number to compare. This page covers golden
sets, the retrieval metrics Recall@K and MRR, latency percentiles, and grounding checks for
generated answers.

| Measure | Question it answers | Range | Sensitive to |
| ------- | ------------------- | ----- | ------------ |
| Recall@K | Did the answer reach the top K results? | 0 to 1 | Whether the right passage is found at all |
| MRR | How high was the first correct result? | 0 to 1 | The order of the top results |
| p50 latency | How long does a typical query take? | Milliseconds | The common case |
| p95 latency | How long do the slowest queries take? | Milliseconds | Slow outliers, which users notice |
| Grounding pass rate | Do the answer's citations name passages it was given? | 0 to 1 | Invented or misattributed citations |
| Citation recall | Do the citations point at the labeled answer? | 0 to 1 | Correct-looking citations of the wrong passage |

## Golden sets

Why it matters: without a fixed set of questions with known answers, every change to a retrieval
pipeline is judged by trying a few queries and forming an impression. The golden set is what turns
"this feels better" into a number that can be compared, and it is the single thing that made every
decision in this project arguable rather than asserted.

A golden set is a list of questions, each labeled with the passages that answer it. It is written
by hand once, kept under version control, and run against every version of the system, so each
change is measured on the same questions.

study_assistant labels each question with a document and a section heading, for the reason above,
and the matching rule is where that choice pays off. A retrieved chunk counts for a label when it
comes from the same document and the label's heading appears anywhere in the chunk's heading path,
so chunks from a labelled section's subsections match too, and re-chunking does not invalidate the
label.

??? example "chunk_matches"

    ```python
    def chunk_matches(metadata: dict[str, Any], expected: ExpectedSection) -> bool:
        """Whether a chunk comes from ``expected``'s document and lies inside its section.

        A chunk lies inside a section when the section's heading is anywhere in the chunk's heading
        path, so chunks from its subsections match too.
        """
        if metadata.get("source") != expected.document:
            return False
        return expected.section in metadata.get("headings", [])
    ```

Source: [`evals/src/evals/metrics.py:13-21`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/evals/src/evals/metrics.py#L13-L21)

The labels are also validated against the corpus before a run. A label naming a section that does
not exist can never match and would quietly lower every score, so a typo is an error rather than a
bad result. The set is ten questions, which is small enough to write carefully and coarse enough
that one question changing moves an average by a tenth.

- Label by document and section, not by chunk: chunk ids and boundaries change whenever the
  chunker or its size changes. A label that names a document and a section heading still applies
  after re-chunking, because the chunks retrieved can be checked against it by their source and
  heading path.
- More than one correct answer: when two documents both answer a question, for example a release
  note and the incident report about the same change, both are labeled. Labeling only one would
  count the other as a wrong answer.
- Coverage of failure modes: a useful golden set includes questions phrased differently from their
  answer, questions about exact identifiers such as error codes, and questions whose answer spans
  documents. A set of easy questions scores well and says nothing.
- Validation: a label that names a section which does not exist can never match, and silently
  lowers every score. Checking each label against the documents before a run turns a typo into an
  error.
- Size: a small set is fast to write and run, and coarse. With ten questions, one question
  changing its result moves an average by a tenth, so small differences between two runs are not
  evidence either way.

## Recall@K

Why it matters: this is the measure that says whether the answer was available at all. A passage
below the cutoff is a passage the model never sees, so this number is the ceiling on the whole
system's accuracy.

Recall@K is the share of a question's labeled passages that appear among the top K retrieved
results, averaged over the questions.

The project computes it over sections rather than chunk ids, and stops at the first matching chunk
per label, since a second chunk from the same section adds nothing. An empty label list is an error
rather than a score of zero, because there would be nothing to find.

??? example "section_recall"

    ```python
    if not expected:
        raise ValueError("Recall needs at least one expected section.")
    found = 0
    for section in expected:
        for metadata in ranked:
            if chunk_matches(metadata, section):
                found += 1
                # One matching chunk is enough; more chunks from the same section add nothing.
                break
    return found / len(expected)
    ```

Source: [`evals/src/evals/metrics.py:24-38`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/evals/src/evals/metrics.py#L24-L38)

- Why a fixed K: a later stage reads only the top K results, for example the passages a language
  model receives as context. A correct passage at rank 30 is never read, so it counts as missed.
- What it ignores: order inside the top K. A correct passage at rank 1 and at rank 5 score the
  same, which is why it is reported beside a rank-sensitive measure.
- Precision@K is the companion measure: the share of the top K that is relevant. It is less useful
  for question answering, where a question usually has one or two relevant passages and the rest
  of the top K is unavoidably irrelevant.

## Mean Reciprocal Rank

Why it matters: recall ignores order, but order is what a reranker changes. This is the measure
that moves when results are reordered, and reporting it beside recall is what makes a reranking
result honest.

The reciprocal rank of one question is 1 divided by the rank of the first relevant result, or 0
when none is retrieved. Mean Reciprocal Rank (MRR) averages it over the questions.

??? example "reciprocal_rank"

    ```python
    def reciprocal_rank(ranked: list[dict[str, Any]], expected: tuple[ExpectedSection, ...]) -> float:
        """One over the rank of the first chunk matching any ``expected`` section, or 0 if none does.

        Ranks count from 1, so a match in first place scores 1.0 and in second place 0.5.
        """
        for rank, metadata in enumerate(ranked, start=1):
            for section in expected:
                if chunk_matches(metadata, section):
                    return 1.0 / rank
        return 0.0
    ```

Source: [`evals/src/evals/metrics.py:41-50`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/evals/src/evals/metrics.py#L41-L50)

This is the measure that caught the cost of reranking in this project: recall rose from 0.90 to
0.95 while this fell from 0.88 to 0.83, because the reranker put a chunk discussing the subject
above the labelled chunk that answers it.

- What it rewards: putting a correct answer first. Moving it from rank 2 to rank 1 adds 0.5 for
  that question, while moving it from rank 5 to rank 4 adds 0.05.
- What it ignores: every relevant result after the first. A question with two labeled passages
  scores the same whether the second is found or not, which Recall@K captures instead.
- Where it matters: reranking leaves the set of candidates unchanged and only reorders it, so its
  effect shows in MRR while Recall@K over the same candidates stays the same.

## Latency percentiles

Why it matters: a retrieval pipeline's cost is felt in the slow requests, not the typical one, and
an average hides them. Percentiles are also how the cost of each optional stage in this project was
priced.

The p-th percentile of a set of latencies is the value that p percent of the measurements are at
or below. p50 is the median, and p95 is exceeded by only the slowest 5 percent.

The project uses the nearest-rank method, so a reported percentile is always a value that was
actually measured. The comment on the arithmetic is the detail worth keeping: multiplying before
dividing keeps whole-number cases exact.

??? example "percentile"

    ```python
    if not values:
        raise ValueError("A percentile needs at least one value.")
    if percent <= 0 or percent > 100:
        raise ValueError(f"percent must be above 0 and at most 100, not {percent}.")
    ordered = sorted(values)
    # The rank, counting from 1, of the smallest value with percent% of the values at or below it.
    # Multiplying before dividing keeps whole-number cases exact: 95 * 20 / 100 is exactly 19.
    rank = math.ceil(percent * len(ordered) / 100)
    return ordered[rank - 1]
    ```

Source: [`evals/src/evals/metrics.py:53-68`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/evals/src/evals/metrics.py#L53-L68)

- Why not the mean: one slow request pulls the mean up without describing any real request. In
  the list above the mean is 32 ms, slower than nine of the ten measurements.
- Why p95: users notice the slow requests, not the typical one. A system with a fast median and a
  slow p95 feels unreliable, and the cause of the slow tail, such as a cold cache or a new
  connection, is often different from the cause of the median.
- Enough samples: with ten measurements, p95 is simply the slowest one. Repeating each query
  several times gives enough samples for the tail to mean something.
- Warm-up: the first query in a process may load a model or fill a cache. Running one untimed
  query first keeps that one-time cost out of the percentiles, and it is measured separately if it
  matters.
- Methods differ: nearest rank returns a measured value. Interpolating methods return a value
  between two measurements. Both are valid, and comparing runs needs the same method in each.

## Comparing runs

Why it matters: a measurement only means something against another measurement taken the same way.
Most of the value of an evaluation harness is in the discipline of changing one thing at a time and
keeping the old numbers.

An evaluation is useful when two runs differ in exactly one thing.

- Fixed inputs: the same golden set, the same documents, and the same K for both runs. A changed
  golden set or corpus makes the numbers incomparable.
- Saved results: each run is saved with its settings and every question's results, never
  overwritten, so a later change is compared against the actual earlier numbers rather than a
  remembered figure.
- Per-question results: two runs with the same average can differ on individual questions, one
  better and one worse. Reading which questions changed shows what the change did.
- Noise: latency varies between runs of the same configuration by a few milliseconds, and a small
  golden set moves in steps of one question. A difference smaller than either is not a result.

All four rules were followed literally when the two embedding models here were compared, and the
comparison is the clearest example of the discipline paying off. The second model was registered
alongside the first, the same stored chunks were embedded with both, and the same ten questions ran
against each. Recall was identical, the ranking measure was slightly worse, and queries took about
three times longer to embed, so the smaller model stayed. Runs are written to files that are never
overwritten, so that conclusion can still be checked against the numbers it came from.

> Two embedding models are compared on the same golden set. Both reach Recall@5 of 0.9, and the
> larger model's MRR is lower by 0.03, from one question moving down a rank and another moving up.
> Its queries take 16 ms longer. The larger model buys nothing measurable on this set, so the
> smaller one stays.

## Grounding checks for generated answers

Why it matters: retrieval metrics say nothing about whether the answer used what it was given. A
system can retrieve perfectly and still invent, which is the failure a RAG system exists to
prevent, so it needs its own check.

Retrieval metrics judge the passages found. Generation needs its own checks, because a model can
receive the right passages and still answer from elsewhere, or cite a passage it was never given.

study_assistant runs this as a separate harness from the retrieval one, and the schema does most
of the work before the check does any: the allowed citation ids are an `enum` built from the
retrieved chunks, so an invented id cannot be produced in the first place, as
[Generation](07-generation.md) describes. The check then confirms that an answer cites something
and that what it cites was in the context, and questions the system declined are excluded, since
they have no citations to judge.

- Grounding pass rate: the share of answered questions whose citations all name passages that were
  in the model's context. It catches invented ids and answers that cite nothing. Questions the
  system declined to answer are left out of this rate, since they have no citations to check.
- Citation recall: the share of a question's labeled sections that the cited passages lie in. A
  citation can be valid, naming a real context passage, and still point at the wrong section.
- Separating the two stages: when citation recall is low, checking whether the labeled section was
  in the context at all tells which stage failed. If it was never retrieved, the fix is in
  retrieval. If it was retrieved and not cited, the fix is in generation.
- Unanswerable questions: a golden set that includes questions the documents cannot answer tests
  whether the system declines them. Declining is the correct result there, and answering is the
  failure.
- What a mechanical check cannot see: a valid citation does not prove the passage supports the
  sentence that cites it. Judging support needs a human reviewer or a second model acting as a
  judge, which costs more and is itself imperfect.
- Quota: each question in a generation eval spends model requests, unlike a retrieval eval. Caching
  replies keyed by the whole request makes an unchanged rerun free.

The practical rule is to write the golden set before changing the system, label it by document and
section, report Recall@K and MRR together with p50 and p95 latency, check every generated citation
against the context and the labels, save every run, and treat any difference smaller than one
question or a few milliseconds as noise.
