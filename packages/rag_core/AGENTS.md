# rag_core — Agent Context

`rag_core` is the shared retrieval library: the single, authoritative implementation of
chunking, embedding, hybrid retrieval, reranking, and pgvector access. See the root
[`AGENTS.md`](../../AGENTS.md) for project-wide context.

## Golden rule

Retrieval lives only here. The MCP server, the API, and the CLI are _consumers_ of `rag_core`,
never reimplementers. If retrieval logic is being written anywhere else, it belongs here instead
([ADR 0001](../../docs/decisions/0001-rag-retrieval-boundary.md)). The public surface is an internal
API — treat it as versioned and change it deliberately.

## Conventions specific to this package

- Lazy model loading. No `torch` import at module top-level outside `embed/` and `rerank/`.
  Importing `rag_core` (or any non-model module) must not pull in PyTorch or load weights
  ([ADR 0002](../../docs/decisions/0002-local-embedding-and-reranking.md)).
- Embedder and reranker sit behind a small interface so the rest of the system is agnostic to
  the concrete model. The one hard lock-in is the pgvector embedding dimension (`vector(N)`): query
  and document vectors must come from the same model, pinned in config, not chosen per call.
  Changing embedders later means a re-embed plus schema migration.
- `user_id` seam. Schema carries a defaulted `user_id` column on relevant tables so multi-user
  auth can be layered on later without reshaping the data model
  ([ADR 0003](../../docs/decisions/0003-local-single-user-scope.md)).

## Layout (built out across phases)

```text
src/rag_core/
├── ingest/     # pptx/pdf/md parsing, semantic chunking   (Phase 2/3)
├── embed/      # bge-m3 embedder, lazy torch load          (Phase 4)
├── rerank/     # bge-reranker-v2-m3 cross-encoder          (Phase 5)
├── retrieve/   # dense + BM25 + RRF fusion                 (Phase 5)
├── store/      # pgvector access, schema, migrations       (Phase 1)
└── config.py   # pinned models, dimensions, settings
```

Only the package skeleton exists today. Modules are added in the phases noted above; until then,
keep new code out of this package unless its phase has started.
