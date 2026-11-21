# 9. MVP Corpus: Release-Engineering Markdown

- Status: Accepted
- Date: 2026-11-21

## Context

The [architecture](../architecture.md) defines the corpus as course materials: lecture slides,
papers, and notes, in pptx, pdf, and md, with citations back to the exact source slide or page.
Ingesting that corpus needs a parser per format. The [MVP plan](../MVP.md) builds the first runnable
version of the system, and it builds only the markdown parser, because markdown is the one format
that needs no extraction library and already carries its structure in headings.

A markdown-only course-materials corpus is not a representative sample of that corpus: slides and
papers are the bulk of it. The MVP therefore needs a corpus that is natively markdown, large enough
to evaluate retrieval against, and rich in the content that separates retrieval strategies, such as
exact symbols, flags, and error codes that dense vector search tends to miss.

## Decision

The MVP indexes a markdown-only release-engineering corpus instead of course materials:

- Build-system documentation (CMake, Bazel).
- Release notes.
- CI failure write-ups, each recording a failing log excerpt, its cause, and its fix.

Citations point to a markdown section: the source document plus the section heading, stored in each
chunk's `metadata`. This replaces slide- and page-level citations for the duration of the MVP.

The decision is temporary. The architecture's corpus definition is unchanged, and this record is
superseded once the pptx and pdf parsers land and course materials are ingested.

## Consequences

- No pipeline code is specific to either corpus. Parsing, chunking, embedding, storage, retrieval,
  and generation are the same for both, so reverting is a matter of ingesting different documents
  with `study ingest`.
- Citation granularity is coarser: a section heading rather than a slide or page. The chunk
  `metadata` column already holds arbitrary provenance, so neither granularity needs a schema change.
- The golden set written for the MVP covers this corpus only. Returning to course materials needs a
  new or extended golden set, labeled the same way by document and section.
- Until this record is superseded, the product description in the README (course materials, slide-
  and page-level citations) describes the target system, not the MVP's running corpus.
