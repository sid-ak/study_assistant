# AI, RAG & Python

This guide covers retrieval-augmented generation (RAG): a way of answering questions with a language
model by first retrieving relevant passages from a document collection and then asking the model to
answer from those passages. It is written alongside
[study_assistant](https://github.com/sid-ak/study_assistant), a local RAG system built in stages, and
it has three sections, two interview-prep pages, and an appendix:

- Project: one page per stage of that system, in build order. Each page explains what the stage
  built and why, using the repository's real code, its design records, and its measured results.
- Concepts: the general theory those stages rely on, written independently of any one system. Each
  page explains a concept from first principles, so it holds for any RAG pipeline.
- Gaps: the subjects this guide's other sections do not reach, written for the DriveOS interview:
  applying RAG and agents to a release pipeline, large logs and tool permissions, LLM failure
  modes and trust, and everyday Python.
- Interview prep: spoken answers and stories for the DriveOS interview, drawn from this project and
  from past work.
- Appendices: every term and technology the guide uses, split by how it is used. Appendix A holds
  what is worth explaining without a reference; Appendix B holds the mechanism detail, exact API
  names, and tooling to look up while reading.

A project page links to the concept pages it depends on instead of re-explaining them. A suggested
reading order is a concept page first, then the project page that applies it.

---

## Sections

| Section | What it covers |
| ------- | -------------- |
| [Project](project/README.md) | What each stage of study_assistant built, the Python it used, its design trade-offs, and its measurements |
| [Concepts](concepts/README.md) | Retrieval-augmented generation, vectors and similarity, and the pipeline stages, explained independently of any codebase |
| [Gaps](gaps/README.md) | Release-workflow assistant design, large logs and tool permissions, LLM failure modes and trust, and Python scripting and fundamentals |

---

## Interview prep

| Page | What it covers |
| ---- | -------------- |
| [Behavioral](behavioral.md) | Behavioral answers reframed for NVIDIA, with the core points, a spoken paragraph and the likeliest follow-up for each, plus what DriveOS is and its compute, virtualization, safety and tooling pillars |
| [Study Assistant Deep Dive](study-assistant-deep-dive.md) | Deep-dive answers on hybrid retrieval and RRF, cross-encoder reranking, the LangGraph agent with Postgres-checkpointed human-in-the-loop, pgvector and HNSW trade-offs, MCP tool contracts, and the eval harness |
| [DriveOS Interview Scripts](driveos-interview-scripts.md) | Timed spoken stories organized by standards pillar, the ISO 26262 and ISO/SAE 21434 links for each, the NVIDIA and DriveOS answer, and questions for the interviewer |

---

## Appendices

| Page | What it covers |
| ---- | -------------- |
| [Appendix A: Core Terminology](appendix-a-core-terminology.md) | The concepts behind each pipeline stage, the vocabulary of tool design, and the Python the project is written in, plus the related topics this guide does not teach |
| [Appendix B: Implementation Reference](appendix-b-implementation-reference.md) | How each mechanism works inside, the exact names the libraries and the database use, the test tooling, and the project's file layout |
