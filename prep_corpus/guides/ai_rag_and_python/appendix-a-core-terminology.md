# Appendix A: Core Terminology

> Part of [AI, RAG & Python](README.md)

The terms and technologies this guide uses that are worth being able to explain without looking
them up: the concepts behind each pipeline stage, the vocabulary of tool design, and the Python the
project is written in. Each entry states what the thing is in one or two sentences and links to the
page that explains it in full.

Mechanism detail, exact API names, test tooling, and the project's file layout are in
[Appendix B](appendix-b-implementation-reference.md). The division is by how each entry is used: a
term here answers a question, a term there answers a lookup.

| Section | Covers |
| ------- | ------ |
| [1. What RAG is for](#1-what-rag-is-for) | The problem and its vocabulary |
| [2. The pipeline](#2-the-pipeline) | The stages, named once |
| [3. Similarity](#3-similarity) | How nearness is measured |
| [4. Chunking and embeddings](#4-chunking-and-embeddings) | How text becomes retrievable vectors |
| [5. Retrieval](#5-retrieval) | Dense, lexical, and hybrid search |
| [6. Reranking and generation](#6-reranking-and-generation) | Re-scoring candidates, then answering |
| [7. The agent and human review](#7-the-agent-and-human-review) | Control flow around the model |
| [8. LLM tool design](#8-llm-tool-design) | Contracts, schemas, budgets, failure |
| [9. Python for scripting and clean OOP](#9-python-for-scripting-and-clean-oop) | The language features the project rests on |
| [10. Measurement](#10-measurement) | How any of it is known to work |
| [11. The stack and the resume claims](#11-the-stack-and-the-resume-claims) | What is deployed, and what the resume says |
| [12. Not covered here](#12-not-covered-here) | Related topics this guide does not teach |

---

## 1. What RAG is for

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Retrieval-augmented generation (RAG) | Answering a question by first retrieving relevant passages from a document collection, then asking a language model to answer from those passages | [RAG Overview](concepts/01-rag-overview.md) |
| Parametric knowledge | What a model knows from its training weights alone, fixed at training time and not attributable to a source | [RAG Overview](concepts/01-rag-overview.md) |
| Grounding | Requiring the answer to come from the retrieved passages rather than from the model's own knowledge | [RAG Overview](concepts/01-rag-overview.md), [Generation](concepts/07-generation.md) |
| Hallucination | A fluent, confident answer the sources do not support | [RAG Overview](concepts/01-rag-overview.md) |
| Citation | A reference from a sentence of the answer to the passage it came from, so a reader can check it | [RAG Overview](concepts/01-rag-overview.md), [Generation](concepts/07-generation.md) |
| Corpus | The document collection the system answers from | [RAG Overview](concepts/01-rag-overview.md) |
| Document | One source file in the corpus, before it is split | [Chunking](concepts/04-chunking.md) |
| Chunk, passage | One piece of a document, the unit that is embedded, retrieved, and cited | [Chunking](concepts/04-chunking.md) |
| Context window | The largest number of tokens a model reads in one request, prompt and reply together | [Generation](concepts/07-generation.md) |
| Where RAG reaches its limits | Questions needing the whole corpus at once, or reasoning across many documents, which retrieving a handful of passages cannot serve | [RAG Overview](concepts/01-rag-overview.md) |

## 2. The pipeline

| Stage | What it does | Covered in |
| ----- | ------------ | ---------- |
| Ingestion | Reads the documents, splits them, embeds the pieces, and stores them | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| Chunking | Splits a document into retrievable pieces | [Chunking](concepts/04-chunking.md) |
| Embedding | Turns each piece of text into a vector | [Embeddings](concepts/03-embeddings.md) |
| Indexing | Builds the structure that makes search fast | [Retrieval](concepts/05-retrieval.md), [Storage and Schema](project/00-storage-and-schema.md) |
| Retrieval | Finds the passages most relevant to a question | [Retrieval](concepts/05-retrieval.md) |
| Reranking | Re-scores the retrieved candidates with a more accurate, slower model | [Reranking](concepts/06-reranking.md) |
| Generation | Produces the answer from the question and the retrieved passages | [Generation](concepts/07-generation.md) |
| Evaluation | Measures whether the pipeline retrieves and answers correctly | [Evaluation](concepts/09-evaluation.md) |
| Retrieval is separate from generation | The two halves are measured and changed independently, because a retrieval failure and a generation failure need different fixes | [RAG Overview](concepts/01-rag-overview.md) |

## 3. Similarity

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Vector | An ordered list of numbers, treated as a point or an arrow in space | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |
| Dimension | One position in a vector; a 384-dimension embedding has 384 numbers | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |
| Vector space | The space all embeddings from one model occupy, where nearness is meant to mean similarity of meaning | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |
| Dot product | The sum of the products of matching components; larger when two vectors point the same way | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |
| Cosine similarity | The cosine of the angle between two vectors, from -1 to 1, measuring direction only | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |
| Cosine distance | 1 minus cosine similarity, so that a smaller number means more similar | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |
| Euclidean distance | Straight-line distance between two points, sensitive to vector length as well as direction | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |
| Normalization, unit length, L2 norm | Scaling a vector to length 1, after which the dot product equals cosine similarity | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |

## 4. Chunking and embeddings

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Fixed-size chunking | Splitting on a token or character count, ignoring the document's structure | [Chunking](concepts/04-chunking.md) |
| Overlap | Repeating the end of one chunk at the start of the next, so a sentence split across a boundary still appears whole somewhere | [Chunking](concepts/04-chunking.md) |
| Structure-aware chunking | Splitting on the document's own boundaries, such as headings | [Chunking](concepts/04-chunking.md) |
| Heading-aware chunking | Structure-aware chunking on headings, keeping the heading path with each chunk | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| Chunk size trade-off | Small chunks retrieve precisely but carry little context; large chunks carry context but dilute the match | [Chunking](concepts/04-chunking.md) |
| Section, heading path | The heading a chunk sits under, used both as retrieved context and as the label an eval matches against | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md), [Evaluation](concepts/09-evaluation.md) |
| Token | A piece of text from a model's fixed vocabulary; the unit a model reads and counts | [Embeddings](concepts/03-embeddings.md) |
| Bi-encoder | A model that embeds query and document separately, so documents can be embedded ahead of time and a question costs one embedding plus a search | [Embeddings](concepts/03-embeddings.md), [Reranking](concepts/06-reranking.md) |
| Contrastive learning | Training on pairs that belong together, rewarding closeness for a pair and distance from other pairs' passages, which is what the vector space's meaning comes from | [Embeddings](concepts/03-embeddings.md) |
| One model per vector space | Vectors from two models are not comparable, so switching models means re-embedding the corpus | [Embeddings](concepts/03-embeddings.md), [Storage and Schema](project/00-storage-and-schema.md) |

## 5. Retrieval

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Dense search | Embedding the question and returning the passages whose vectors are nearest | [Retrieval](concepts/05-retrieval.md) |
| Exact search, flat search | Comparing the query with every stored vector; always correct, cost grows linearly | [Retrieval](concepts/05-retrieval.md) |
| Approximate nearest-neighbor search (ANN) | Comparing the query with a well-chosen subset, accepting occasional misses for a large speed gain | [Retrieval](concepts/05-retrieval.md) |
| HNSW (Hierarchical Navigable Small World) | The common ANN index: a layered graph of vectors walked greedily toward the query, with cost growing roughly with the logarithm of the collection size | [Retrieval](concepts/05-retrieval.md) |
| `m` | Build-time HNSW parameter: links kept per node per layer. Raising it improves recall and enlarges the index | [Retrieval](concepts/05-retrieval.md) |
| `ef_construction` | Build-time HNSW parameter: candidates considered when linking a new node | [Retrieval](concepts/05-retrieval.md) |
| `ef_search` | Per-query HNSW parameter: size of the bottom-layer candidate list. It bounds both recall and the number of results, and is the one tunable without a rebuild | [Retrieval](concepts/05-retrieval.md), [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| Lexical search | Ranking passages by the words they share with the query, with no model | [Retrieval](concepts/05-retrieval.md) |
| Term frequency, inverse document frequency (IDF) | How often a query word occurs in a passage, and how rare it is across the corpus, which is what makes a matched identifier count more than a matched common word | [Retrieval](concepts/05-retrieval.md) |
| TF-IDF | Scoring a passage by term frequency weighted by inverse document frequency | [Retrieval](concepts/05-retrieval.md) |
| BM25 | The standard lexical scorer: TF-IDF with term-frequency saturation and a length correction | [Retrieval](concepts/05-retrieval.md) |
| Hybrid search | Running dense and lexical search for one query and merging the two ranked lists, so meaning and exact identifiers both count | [Retrieval](concepts/05-retrieval.md), [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| Reciprocal Rank Fusion (RRF) | Merging ranked lists by rank alone, each list contributing `1 / (k + rank)`, which avoids comparing a cosine distance with a BM25 score | [Retrieval](concepts/05-retrieval.md), [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| `k` (the RRF constant) | The damping constant in that formula, conventionally 60, which limits how much rank 1 outweighs rank 2 | [Retrieval](concepts/05-retrieval.md) |
| Candidate pool | The number of results each search returns for fusion or reranking, larger than the number finally kept | [Reranking](concepts/06-reranking.md), [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| Top-k | The number of results a stage returns | [Retrieval](concepts/05-retrieval.md) |

## 6. Reranking and generation

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Cross-encoder | A model that reads query and passage together and outputs a relevance score; more accurate than a bi-encoder, and not precomputable | [Reranking](concepts/06-reranking.md) |
| Retrieve, then rerank | Fetching a wider candidate pool cheaply, then re-scoring only those candidates with the cross-encoder | [Reranking](concepts/06-reranking.md) |
| Latency cost | The reranker's cost, which grows with the pool size because every candidate is a separate model pass | [Reranking](concepts/06-reranking.md), [Reranking (project)](project/04-reranking.md) |
| Logit | The raw, unbounded score a cross-encoder outputs before any squashing | [Reranking (project)](project/04-reranking.md) |
| Sigmoid | The function mapping a logit to a probability between 0 and 1, which is what makes the score usable as a grade | [Reranking (project)](project/04-reranking.md) |
| Relevance grade | A reranker score read as an absolute judgment of relevance, not just an ordering | [Reranking](concepts/06-reranking.md), [Reranking (project)](project/04-reranking.md) |
| What reranking changes | It reorders a fixed candidate set, so it moves MRR while leaving Recall@K over that set unchanged | [Reranking](concepts/06-reranking.md) |
| Temperature | The setting that sharpens or flattens token probabilities before sampling; 0 makes an answer repeatable, which is why it is used here | [Generation](concepts/07-generation.md) |
| Structured output | Requiring the reply to match a schema rather than be free text | [Generation](concepts/07-generation.md), [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `enum` over context ids | Restricting a citation field to the ids actually supplied, so a citation cannot be invented | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |

## 7. The agent and human review

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Agent | A program that lets a model choose among tools and repeat steps, instead of running one fixed sequence | [Agents and Tools](concepts/08-agents-and-tools.md) |
| Agent loop as a state machine | Modeling those steps as named states with explicit transitions, so every path is enumerable and testable | [Agents and Tools](concepts/08-agents-and-tools.md) |
| State, node, edge, conditional edge | The graph's data, its steps, the fixed transitions, and the transitions a function chooses at run time | [Agents and Tools](concepts/08-agents-and-tools.md), [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Channel | A declared key of the graph's state. Only declared keys are merged, so an undeclared one a step returns is dropped silently | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| LangGraph | The framework the agent is built on: a state machine over a typed state, with checkpointing and interrupts | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md), [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| Tool calling | The model emitting a request to run a named function with arguments, which the program runs and returns | [Agents and Tools](concepts/08-agents-and-tools.md) |
| Model Context Protocol (MCP) | A standard protocol for exposing tools to a model client over a transport, so a tool server is reusable across clients | [Agents and Tools](concepts/08-agents-and-tools.md), [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Bounded loop | A hard cap on hops, so an agent that is not converging stops instead of looping | [Agents and Tools](concepts/08-agents-and-tools.md) |
| Two-hop retrieval | The specific bound used here: retrieve, and on poor relevance rewrite the query and retrieve once more | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Query rewriting | Having the model restate the question before a second retrieval attempt | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Relevance grading | Deciding whether retrieved context is good enough to answer from, here by thresholding the top hit's score rather than asking a model | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Checkpointing | Saving a run's state after each step, so it can be inspected, resumed, or replayed | [Agents and Tools](concepts/08-agents-and-tools.md) |
| Checkpointer, saver | The component writing those checkpoints to a store; here Postgres, so a paused run survives the process | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| Thread id | The identifier a run is saved under, and the only thing needed to resume it from another process | [Agents and Tools](concepts/08-agents-and-tools.md), [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| Human in the loop | Pausing a run for a person's decision before a consequential step, then continuing with it | [Agents and Tools](concepts/08-agents-and-tools.md) |
| Interrupt, resume | The pause that saves the run and hands out a payload, and the later call whose value becomes the paused call's return value | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| Retrieval boundary | The rule that the agent reads documents only through the tool, enforced by a test that rejects any direct import | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |

## 8. LLM tool design

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Tool contract | A tool's name, arguments, and return shape, which is the whole interface the model and the system share | [Agents and Tools](concepts/08-agents-and-tools.md), [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Designing a tool | Keeping a tool narrow, its arguments validated, and its output shaped for a model to cite rather than for a human to read | [Agents and Tools](concepts/08-agents-and-tools.md) |
| Argument validation | Rejecting an empty query or an out-of-range limit at the tool boundary, before any work is done | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| JSON Schema, strict mode | The schema format, and the provider mode that guarantees a reply conforms to it | [Generation](concepts/07-generation.md), [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `ToolError` against a plain exception | An error type the client receives as a message it can act on; any other exception reads as a crash with no detail | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Tool server, `MCPServer`, `add_tool` | Declaring a server and exposing one function on it as a named tool | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| stdio transport | Running the tool server as a subprocess and speaking to it over its standard streams | [Agents and Tools](concepts/08-agents-and-tools.md), [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| JSON-RPC | The request and response format MCP messages take | [Agents and Tools](concepts/08-agents-and-tools.md) |
| Environment boundary | Passing a tool server only the variables it needs, so a generation key never reaches it | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Token budget | How much of the context window the instructions, question, and passages consume, and why a long context is still kept short | [Generation](concepts/07-generation.md) |
| Truncation | What a service does to a prompt exceeding the window, which can silently remove the question or the instructions | [Generation](concepts/07-generation.md), [Embeddings](concepts/03-embeddings.md) |
| Rate limit | A cap on requests or tokens per interval, reported as HTTP 429 | [Generation](concepts/07-generation.md), [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `retry-after`, exponential backoff | The header naming how long to wait, and the doubling fallback when no header is sent; a wait longer than the cap is an error rather than a stall | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Reply cache | Storing replies under a hash of the whole request, so a repeated request costs no tokens and no time | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `SecretStr` | A settings type that keeps an API key out of `repr` and logs | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Idempotency | Running the same operation twice changing nothing the second time, which here rests on deterministic ids and a content hash | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| Refusing what cannot work | Failing at the boundary on a request that would otherwise half-succeed, such as resuming a thread id nothing is waiting on | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |

## 9. Python for scripting and clean OOP

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| `typing.Protocol` | An interface satisfied by shape rather than inheritance, which is how every component is swapped for a fake. Unlike an abstract base class, an implementation never names it | [Storage and Schema](project/00-storage-and-schema.md) |
| `@runtime_checkable` | Allows `isinstance` against a protocol, which the contract tests use on every implementation | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `@dataclass(frozen=True)` | An immutable value object with generated `__init__` and `__eq__`, compared by value | [Storage and Schema](project/00-storage-and-schema.md) |
| `field(default_factory=...)` | Gives each instance its own mutable default. A plain `= []` default is refused outright, because one list would be shared across instances | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `@property` | A read-only attribute computed from private state | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `@classmethod` | An alternative constructor, here building a component from configuration | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| pydantic, pydantic-settings | Typed settings read from the environment or a `.env` file, validated on construction | [Storage and Schema](project/00-storage-and-schema.md) |
| Typed exception hierarchy | Every error a component raises deriving from one project error, so a driver's exceptions never reach callers | [Storage and Schema](project/00-storage-and-schema.md) |
| `pathlib` | Paths as objects, with recursive globbing and sorted results for a stable order | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `re` | Regular expressions with capture groups, here matching a heading and its level | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `subprocess` | Running a child process and reading its output, here to prove a paused run survives the parent | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `argparse` subparsers | A CLI with several commands, each with its own typed options | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `async def`, `await`, `asyncio.run`, event loop | The async syntax and the loop that carries the tool connection and the graph run | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `asyncio.to_thread` | Runs a blocking call in a thread, so the event loop stays free during an HTTP request | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |

## 10. Measurement

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Golden set | Hand-written questions, each labeled with the passages that answer it, kept under version control and run against every version | [Evaluation](concepts/09-evaluation.md), [Evaluation Harness](project/02-evaluation-harness.md) |
| Label by document and section | Labeling a source and heading rather than a chunk id, so labels survive re-chunking | [Evaluation](concepts/09-evaluation.md) |
| Recall@K | The share of a question's labeled passages appearing in the top K, averaged over questions; ignores order within the top K | [Evaluation](concepts/09-evaluation.md) |
| Precision@K | The share of the top K that is relevant, the complement of a false-positive rate | [Evaluation](concepts/09-evaluation.md) |
| Reciprocal rank, Mean Reciprocal Rank (MRR) | One over the rank of the first relevant result, and its average over questions; rewards ranking a correct passage first | [Evaluation](concepts/09-evaluation.md) |
| Latency percentile, p50, p95 | The value a given share of measurements falls at or below: the median, and the tail users notice. A mean hides a slow tail | [Evaluation](concepts/09-evaluation.md) |
| Warm-up | An untimed first query, which keeps a one-time model load or cache fill out of the percentiles | [Evaluation](concepts/09-evaluation.md), [Evaluation Harness](project/02-evaluation-harness.md) |
| Saved run | A recorded result file, so two configurations are compared after the fact rather than from memory | [Evaluation](concepts/09-evaluation.md), [Evaluation Harness](project/02-evaluation-harness.md) |
| Comparing runs | Reading a difference against the set's size, since with ten questions one changed result moves an average by a tenth | [Evaluation](concepts/09-evaluation.md) |
| Grounding check | An eval asking whether the answer's citations exist and support it, rather than whether retrieval found the passage | [Evaluation](concepts/09-evaluation.md), [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Probe | A small experiment run against an installed library or live service to settle how it actually behaves, before any code depends on the claim | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md), [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |

## 11. The stack and the resume claims

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Postgres | The single database holding documents, chunks, vectors, the full-text index, and the agent's checkpoints | [Storage and Schema](project/00-storage-and-schema.md) |
| pgvector | The Postgres extension adding a vector column type, distance operators, and vector indexes | [Storage and Schema](project/00-storage-and-schema.md) |
| `vector(N)` | The column type for an N-dimension embedding, fixed per column | [Storage and Schema](project/00-storage-and-schema.md) |
| 2000-dimension limit | pgvector's cap on an HNSW-indexed column, checked by the store so the failure is a typed error rather than a database exception mid-registration | [Storage and Schema](project/00-storage-and-schema.md) |
| Per-model embedding columns | One vector column per registered embedder, which makes adding a second model additive rather than a migration | [Storage and Schema](project/00-storage-and-schema.md) |
| Embedder registry | The table and interface recording which models exist, their dimension, and their column name | [Storage and Schema](project/00-storage-and-schema.md) |
| `bge-small-en-v1.5`, `bge-base-en-v1.5` | The default embedding model at 384 dimensions, and the 768-dimension model registered beside it for comparison and left out of the default after it showed no recall gain | [Evaluation Harness](project/02-evaluation-harness.md) |
| `jina-reranker-v1-tiny-en` | The cross-encoder used for reranking, chosen for size on this machine | [Reranking (project)](project/04-reranking.md) |
| `qwen/qwen3.8-27b` on Groq | The generation model and provider actually used, on a free plan | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| OpenAI-compatible protocol | The chat-completions request format many providers accept, which keeps the generator free of a vendor SDK. The resume says the OpenAI API; the code speaks this protocol to Groq | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md), [Study Assistant Deep Dive](study-assistant-deep-dive.md) |
| Docker Compose | How the Postgres instance with pgvector is run locally | [Storage and Schema](project/00-storage-and-schema.md) |
| Where the resume is ahead of the code | The claims the repository does not yet support, named explicitly so they are not defended as built | [Study Assistant Deep Dive](study-assistant-deep-dive.md), [Code Freeze and Walkthrough](project/07-code-freeze-and-walkthrough.md) |
| ADR, decision record | The numbered record settling one design decision and naming the alternative it rejected, which every trade-off in the Project section links to | [Project](project/README.md) |

## 12. Not covered here

Four topics sit next to this material and are worth separate preparation, because neither appendix
indexes them: this guide does not teach them, so there is nothing here to look up.

- The global interpreter lock, and what it does and does not mean for threads against `asyncio`.
  The guide uses `asyncio.to_thread` to keep an event loop free, but does not explain the lock
  itself.
- Generators and iterators as language features. The `Generator` in this project is the class that
  produces an answer, not the Python construct, so the two share only a name.
- False-positive rate and token usage as agent metrics. The evaluation pages measure retrieval
  quality and latency, not cost per run or the rate at which a tool reports a problem that is not
  there.
- Dry-run modes, and separating read-only tools from destructive ones. The one tool here only
  reads, so the question never arose in the build.
