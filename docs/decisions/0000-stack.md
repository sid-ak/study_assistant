# 0. Stack: Python, FastAPI, React, PostgreSQL

- Status: Accepted
- Date: 2026-06-22

## Context

Before any architectural or deployment decision, the project requires a foundational stack to
support its four-layer system from a first principles standpoint.

- Ingestion core demanding an ML/RAG ecosystem.
- HTTP API to orchestrate agent streaming.
- Frontend to render incremental tokens with citations.
- Lightweight data store holding relational chunk text alongside dense vectors.

### Language: Python

Python is itself slow line-by-line. However, Python is actually just a syntax wrapper for highly
optimized C, C++, and Fortran code. The retrieval stack is the heart of the project and is built on
the ML/RAG ecosystem. In this domain, Python is glue code orchestrating optimized native libraries
(NumPy, PyTorch) where the heavy tensor math actually runs, and the surrounding data-science
ecosystem (NumPy, Pandas, scikit-learn) has decades of accumulated work behind it. Choosing Python
keeps the retrieval core and the services that consume it in one language and one workspace.

### Framework: FastAPI

FastAPI was chosen over the other mainstream Python options. The generation lane streams tokens from
the model while the agent loop pauses for human input, so the framework must be async-native and
stream cleanly. FastAPI is built on Asynchronous Server Gateway Interface or ASGI (served by
_Uvicorn_) and supports `StreamingResponse` directly, so tokens flow out over SSE without blocking
the server; its _Pydantic_ typing — already the de facto standard for structuring LLM I/O — matches
the typed-interface discipline used across the retrieval core. Importantly, FastAPI stays minimal,
with no ORM or admin scaffolding unlike other choices such as Django.

### Frontend: React

React suits a token-streaming UI. Answers arrive one token at a time, and React's state model is
built to append each chunk and re-render only the affected message container through the Virtual
DOM, leaving sidebars, inputs, and navigation responsive — the "typing effect" without DOM thrash
even at dozens of updates per second. `useEffect` gives precise control over the stream connection
lifecycle (open on mount, append on message, close on unmount) so streams are not orphaned, and
TypeScript carries the same typed contract into the citation-rendering and human-approval
components.

The considered alternative was Angular. Its default change-detection model is less naturally suited
to high-frequency token appends than React's targeted state-driven re-render. Angular's idiomatic
RxJS-centric data flow adds indirection over consuming a native `ReadableStream` directly, where
React leans on the same `fetch`/stream primitives with less wrapping.

### Datastore: PostgreSQL

PostgreSQL is a single store for both relational data and vectors: the pgvector extension holds
embeddings and runs dense similarity search in the same database that holds chunk text and metadata
for lexical (BM25-style) search. One engine serves both halves of hybrid retrieval and the agent's
persisted state, so there is no second system to run, back up, and keep in sync. Postgres is also
mature, transactional, and trivial to stand up in a single container.

The considered alternative was a dedicated vector database (such as Pinecone, Milvus, or Qdrant)
alongside a relational database. A purpose-built vector engine is excellent at scale, but at a
personal-corpus scale it adds a second datastore to operate and a synchronization problem where
chunk text in one system and vectors in another, kept consistent by hand. Keeping vectors and rows
in one Postgres instance is simpler and keeps the footprint to a single container.

## Decision

- Python: One language across the ML core and the web tier.
- FastAPI: Minimal, typed, async-native (ASGI/Uvicorn), SSE streaming via `StreamingResponse`.
- React: State-driven streaming render.
- PostgreSQL + pgvector: Single store for chunk text, metadata, vectors, and agent state.

## Consequences

- One Language: Shared across the MCP server and API without a cross-runtime boundary.
- First-Class Streaming: FastAPI yields tokens over SSE and React renders them incrementally.
  - Additionally, the browser's native `EventSource` API is `GET` only, but the agent must receive a
    JSON payload (prompt plus chat history) on a `POST`.
  - React therefore enables consuming the stream over the `fetch` API with a `ReadableStream` (for
    example, Vercel AI SDK's `useChat`).
- One Database: Avoids synchronization and footprint limited to one container.
- Well Supported: Lowers operational risk, novel parts of the project sit on top of a proven
  foundation by design.
