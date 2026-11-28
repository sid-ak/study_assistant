# Appendix B: Implementation Reference

> Part of [AI, RAG & Python](README.md)

The rest of the guide's vocabulary: how each mechanism works inside, the exact names the libraries
and the database use, the test tooling, and the project's own file layout. These are entries to look
up while reading a page or the code, not to recall.

The concepts these implement, and the terms worth explaining without a reference, are in
[Appendix A](appendix-a-core-terminology.md).

| Section | Covers |
| ------- | ------ |
| [1. Index and retrieval internals](#1-index-and-retrieval-internals) | How the indexes and scorers work |
| [2. Embedding internals](#2-embedding-internals) | Inside the embedding model |
| [3. Generation internals](#3-generation-internals) | Inside the decoding loop |
| [4. Postgres and pgvector surface](#4-postgres-and-pgvector-surface) | Types, operators, functions, settings |
| [5. Framework and library surface](#5-framework-and-library-surface) | LangGraph, MCP, fastembed, and the rest |
| [6. Python language and test tooling](#6-python-language-and-test-tooling) | The remaining syntax and pytest |
| [7. Project surface](#7-project-surface) | Packages, commands, rejected options |

---

## 1. Index and retrieval internals

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Navigable small world | A graph where each node links to nearby nodes plus a few far ones, so a greedy walk reaches any region in few steps | [Retrieval](concepts/05-retrieval.md) |
| Greedy walk | Always moving to the neighbor closest to the target, which is how an HNSW search navigates | [Retrieval](concepts/05-retrieval.md) |
| Layer hierarchy, skip list | HNSW's layers: every node on the bottom with short links, exponentially fewer nodes above with long ones, like a skip list's express lanes | [Retrieval](concepts/05-retrieval.md) |
| HNSW insertion | A new vector gets a random top layer and is linked to its nearest nodes on each layer at or below it, found with the same search | [Retrieval](concepts/05-retrieval.md) |
| IVFFlat | The alternative pgvector index, which partitions vectors into lists instead of building a graph | [Retrieval](concepts/05-retrieval.md) |
| Index constraints | Properties that shape a design: one index serves one dimension, a filter can starve a fixed candidate list, and an index orders by distance only | [Retrieval](concepts/05-retrieval.md) |
| Recall@k as approximation quality | The share of the true k nearest vectors, found by an exact search, that an approximate search also returned | [Retrieval](concepts/05-retrieval.md) |
| Inverted index | A map from each word to the passages containing it, which turns matching into a lookup rather than a scan | [Retrieval](concepts/05-retrieval.md) |
| Stop words, stemming | Dropping very common words, and reducing words to a root so inflections match | [Retrieval](concepts/05-retrieval.md), [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| Saturation | The property that the tenth occurrence of a word adds much less to a BM25 score than the second | [Retrieval](concepts/05-retrieval.md) |
| Length correction | BM25's adjustment for passage length, so a long passage does not score highly on word count alone | [Retrieval](concepts/05-retrieval.md) |
| High-dimensional space | The regime embeddings live in, where distances between unrelated points concentrate and intuitions from two or three dimensions mislead | [Vector Space and Similarity](concepts/02-vector-space-and-similarity.md) |
| Small-collection effect | Why a few hundred vectors hide the recall and latency trade-off: a small candidate list already covers much of the graph | [Retrieval](concepts/05-retrieval.md) |

## 2. Embedding internals

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Tokenizer | The component splitting text into tokens, with its own vocabulary per model | [Embeddings](concepts/03-embeddings.md) |
| Subword | A fragment of a rare word, which lets a fixed vocabulary represent any text | [Embeddings](concepts/03-embeddings.md) |
| Token counts against word counts | Why a size limit in tokens holds far fewer words of code than of prose: flags, paths, and log lines split into many pieces each | [Embeddings](concepts/03-embeddings.md) |
| Input limit | The fixed number of tokens a model reads, often 512; most libraries truncate longer input with no error | [Embeddings](concepts/03-embeddings.md) |
| Transformer encoder | The architecture reading all tokens at once and outputting one context-adjusted vector per token | [Embeddings](concepts/03-embeddings.md) |
| Pooling | Reducing the per-token vectors to one vector for the whole text | [Embeddings](concepts/03-embeddings.md) |
| CLS pooling against mean pooling | Taking a special first token's vector, trained to summarize the input and used by the BGE models, against averaging every token's vector | [Embeddings](concepts/03-embeddings.md) |
| Hard negatives | Passages that look relevant but are not, added to training on purpose to teach finer distinctions than random negatives do | [Embeddings](concepts/03-embeddings.md) |
| Model size against quality | The trade between a larger model's accuracy and its memory and latency cost | [Embeddings](concepts/03-embeddings.md) |
| Query and document prefixes | Short instruction strings some models require in front of a query or a passage, which must match the training convention | [Embeddings](concepts/03-embeddings.md) |
| Semantic chunking | Splitting where consecutive sentences stop resembling each other, measured with embeddings | [Chunking](concepts/04-chunking.md) |

## 3. Generation internals

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| Next-token prediction | The loop a language model runs: output a probability for every token in the vocabulary, pick one, append it, repeat until an end token or a length limit | [Generation](concepts/07-generation.md) |
| Greedy decoding | Always taking the most likely token, which makes output repeatable for the same input | [Generation](concepts/07-generation.md) |
| Sampling | Picking a token at random in proportion to its probability | [Generation](concepts/07-generation.md) |
| Chat models and roles | A model trained on messages, where the system message sets rules, user messages carry requests, and assistant messages are replies, all joined into one token sequence | [Generation](concepts/07-generation.md) |
| Position in a long context | That models use information in the middle of a long context less reliably than information near its start or end | [Generation](concepts/07-generation.md) |

## 4. Postgres and pgvector surface

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| `<=>` | pgvector's cosine distance operator, which an HNSW index on that column can serve | [Storage and Schema](project/00-storage-and-schema.md) |
| `hnsw.ef_search` | The session or transaction setting carrying `ef_search` into one query | [Storage and Schema](project/00-storage-and-schema.md), [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `set_config` | The function used to set that value for a transaction | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| pgvector HNSW defaults | `m = 16`, `ef_construction = 64`, `ef_search = 40` | [Retrieval](concepts/05-retrieval.md) |
| `tsvector`, `to_tsvector` | The full-text type and the function producing it, here a generated column over the chunk's content | [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| `plainto_tsquery`, `tsquery` | The parser turning a plain question into a query, which joins terms with AND until it is rewritten to OR | [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| AND to OR rewriting | Replacing each `&` in the parsed query with the OR operator, so a question matches any of its words rather than all of them | [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| `ts_rank` | Postgres's full-text ranking function, which uses no inverse document frequency and ignores length by default, so it is not BM25 | [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| GIN index | The inverted index type backing full-text search on the `tsvector` column | [Hybrid Retrieval](project/05-hybrid-retrieval.md) |
| `uuid5`, SHA-256 content hash | A deterministic id derived from a path, and the hash deciding whether content changed | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `document_id`, `metadata`, `user_id` | The chunk's source reference, its stored side information, and the owner scope a query filters by | [Storage and Schema](project/00-storage-and-schema.md) |
| psycopg named parameters | Binding values as `%(name)s` so query text is never built by concatenation | [Hybrid Retrieval](project/05-hybrid-retrieval.md) |

## 5. Framework and library surface

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| `StateGraph`, `add_node`, `add_edge`, `add_conditional_edges`, `START` | LangGraph's builder API: the graph over a state type, its steps, its fixed transitions, its chosen transitions, and the entry point | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `compile(checkpointer=...)` | Turning the built graph into a runnable one, optionally with a saver attached | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `ainvoke` | Running a graph, with an initial state to start or a `Command` to resume | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `aget_state`, `saved.interrupts` | Reading back the state saved under a thread id, and the field distinguishing a paused run from an unknown one | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `Command(resume=...)` | The counterpart to `interrupt`: the value it carries becomes that call's return value | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `RunnableConfig`, `configurable.thread_id` | The config every call to a compiled graph carries, and the key naming which run it means | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `AsyncPostgresSaver`, `saver.setup()` | LangGraph's Postgres checkpointer, and the call creating its four tables on first use | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| In-memory saver | LangGraph's non-persistent checkpointer, enough for a test that reads saved state back | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `JsonPlusSerializer` | The checkpoint serializer, which must be told the custom types the state carries or restores them as plain dictionaries | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| MCP SDK (`mcp`) | The library providing the server, the client, and the transports for the protocol | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| In-process client | Connecting the real MCP client to a server object with no subprocess, so tests drive the real protocol | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| anyio, `ExceptionGroup` | The async library the SDK's client runs its task group on, and the wrapper nesting an exception raised inside it | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| fastembed | The embedding and reranking library used here, which runs quantized models with no PyTorch dependency | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md), [Reranking (project)](project/04-reranking.md) |
| ONNX Runtime, quantized model | The portable inference runtime, and a reduced-precision model that is smaller and faster at a small accuracy cost | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| Lazy loading | Deferring a model load until the first call, so importing or constructing the component stays fast | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| httpx, `httpx.MockTransport` | The HTTP client the generator uses, and the in-process transport letting tests assert exactly what was sent | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| psycopg | The Postgres driver the project uses directly, with no ORM | [Storage and Schema](project/00-storage-and-schema.md) |
| mypy `--strict` | The type checker in its strictest mode, which rejects untyped functions and verifies implementations against their protocols | [Storage and Schema](project/00-storage-and-schema.md) |
| uv workspace | The multi-package layout the libraries, services, CLI, and evals live in, each with its own dependencies | [Storage and Schema](project/00-storage-and-schema.md) |
| `tomllib` | Reads TOML with the standard library, so the eval harness adds no dependency | [Evaluation Harness](project/02-evaluation-harness.md) |

## 6. Python language and test tooling

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| `TypedDict` with `total=False` | A typed dict whose keys may be absent, so a graph step returns only the keys it changes | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Union return type, `isinstance` narrowing | One call that can finish or pause, and the check picking the branch for whichever came back | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `X \| None` | An optional value the caller has to handle explicitly | [Reranking (project)](project/04-reranking.md) |
| `dataclasses.replace`, `dataclasses.asdict` | A copy of a frozen object with one field changed, and a nested conversion to dicts for JSON | [Reranking (project)](project/04-reranking.md), [Evaluation Harness](project/02-evaluation-harness.md) |
| `@contextmanager`, `@asynccontextmanager` | Turning a setup-and-teardown pair into one `with` or `async with` block | [Storage and Schema](project/00-storage-and-schema.md), [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `__aenter__`, `__aexit__` | The async context-manager methods, implemented directly so one client owns a connection for a whole run | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `AsyncExitStack` | Opens several context managers conditionally and closes them in reverse order | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `__call__` | An object callable like a function, holding the graph it answers with | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Keyword-only parameters (`*`) | Forces callers to name arguments, so a call site says which embedder and store it means | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| `zip(..., strict=True)` | Raises instead of truncating when two sequences differ in length, catching a model that returns the wrong number of vectors or scores | [Evaluation Harness](project/02-evaluation-harness.md), [Reranking (project)](project/04-reranking.md) |
| `open(..., "x")` | Exclusive creation, which fails rather than overwriting a saved run | [Evaluation Harness](project/02-evaluation-harness.md) |
| `math.ceil`, `math.exp` | The nearest-rank percentile, and the sigmoid over a reranker logit | [Evaluation Harness](project/02-evaluation-harness.md), [Reranking (project)](project/04-reranking.md) |
| `hashlib.sha256`, `json.dumps(sort_keys=True)` | A stable cache key, so the same request always hashes the same way | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `ast.parse`, `ast.walk` | Reads every import in a source file without importing it, which is how the retrieval boundary is enforced | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `uuid4().hex` | Names a paused run when the caller gives none | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| pytest fixtures, `params`, `parametrize`, `ids`, `marks` | One test body run against every implementation or input, each case named in the output and markable | [Storage and Schema](project/00-storage-and-schema.md), [Evaluation Harness](project/02-evaluation-harness.md) |
| `monkeypatch`, `capsys`, `tmp_path` | Swapping a function, capturing printed output, and writing into a fresh folder per test | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md) |
| Custom markers (`unit`, `integration`) | Separating tests needing no services from those needing a database or a model download | [Storage and Schema](project/00-storage-and-schema.md) |
| Contract test | One parametrized test body asserting the behavior every implementation of a protocol must share | [Storage and Schema](project/00-storage-and-schema.md) |
| Fake | An in-memory implementation enforcing the real constraints, as opposed to a mock that only records calls | [Storage and Schema](project/00-storage-and-schema.md) |
| Injected `sleep` | A function passed in that records each wait instead of pausing, so backoff tests assert exact delays and run instantly | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `[project.scripts]` | The packaging entry installing a module's function as a command | [Evaluation Harness](project/02-evaluation-harness.md) |

## 7. Project surface

| Term | What it means | Covered in |
| ---- | ------------- | ---------- |
| `rag_core`, `rag_core_testing` | The retrieval library, and its shared fakes and contract tests | [Storage and Schema](project/00-storage-and-schema.md) |
| `services/mcp_server`, `services/api` | The MCP tool server, and the service that may not import the retrieval library | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `study ingest`, `study query`, `study embed` | The CLI commands loading the corpus, searching it, and filling a second model's column for stored chunks | [Ingestion and HNSW Retrieval](project/01-ingestion-and-hnsw-retrieval.md), [Evaluation Harness](project/02-evaluation-harness.md) |
| `study-eval` | The eval runner, which scores a named run and saves it | [Evaluation Harness](project/02-evaluation-harness.md) |
| `study-mcp` | The tool server's command, which the agent's client starts as a subprocess | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| `study-ask` | The agent command, with `--review` to pause for approval and `--resume <thread-id>` to continue a paused run | [Human-in-the-Loop Checkpoint](project/06-human-in-the-loop-checkpoint.md) |
| `bge-reranker-v2-m3`, `ms-marco-MiniLM-L-6-v2` | The rerankers rejected: one too large for the machine, one slower and without a stated license | [Reranking (project)](project/04-reranking.md) |
| Nearest-rank percentile | The percentile method returning a measured value rather than interpolating between two | [Evaluation](concepts/09-evaluation.md) |
| `TMPDIR` and the model cache | Why a tool server needs it passed: without it the server looked elsewhere, downloaded a second copy of the model, and took 4.3 s to connect instead of 0.9 s | [Bounded Agent over MCP](project/03-bounded-agent-over-mcp.md) |
| Code freeze | The final stage: a fresh clone, an audit of the records, and every measurement collected in one place | [Code Freeze and Walkthrough](project/07-code-freeze-and-walkthrough.md) |
