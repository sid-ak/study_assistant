# 10. Lightweight Embedding and Reranking Models

- Status: Accepted
- Date: 2026-11-25

## Context

[ADR 0002](0002-local-embedding-and-reranking.md) chose a local, in-process retrieval stack and named
two models for it: `bge-m3` for embeddings and `bge-reranker-v2-m3` for reranking. Both run through
PyTorch. The install alone is large, and each model's weights are a few gigabytes.

The development machine cannot hold that stack:

- An Apple M1 with 8 GB of RAM, shared with Docker and the Postgres container.
- About 7 GB of free disk.
- A budget of zero, so hosted embedding or reranking APIs and rented compute are out.

The reasons for the local stack in ADR 0002 still hold: no per-call cost, retrieval that works
offline, and owning the eval loop. Only the model choice has to change.

`fastembed` is a Python library that runs quantized embedding and cross-encoder models on ONNX
Runtime instead of PyTorch. Its declared dependencies on PyPI include `onnxruntime` and no `torch`.
Four candidate models were measured on the development machine on 2026-11-25 with
`scripts/probes/probe_fastembed.py`. The probe used fastembed 0.9.1, onnxruntime 1.32.0, and Python
3.12, and its environment took 147 MB of disk.

| Model | Role | Disk | Dimension | Speed | Peak memory |
| --- | --- | --- | --- | --- | --- |
| `BAAI/bge-small-en-v1.5` | Embedding | 64 MB | 384 | 4 ms per query, 14 chunks per second | 621 MB |
| `BAAI/bge-base-en-v1.5` | Embedding | 208 MB | 768 | 12 ms per query (p95 35 ms), 4 chunks per second | 1,233 MB |
| `Xenova/ms-marco-MiniLM-L-6-v2` | Reranking | 87 MB | not applicable | 20 candidates in 749 ms (p50), 1,271 ms (max) | 792 MB |
| `jinaai/jina-reranker-v1-tiny-en` | Reranking | 128 MB | not applicable | 20 candidates in 558 ms (p50), 634 ms (max) | 700 MB |

Chunks in the speed test were about 250 tokens. On a five-document sample, every model ranked the
correct document first. `bge-base-en-v1.5` separated it more clearly than `bge-small-en-v1.5`
(cosine 0.83 against 0.56 for the runner-up, compared with 0.83 against 0.71). A single query is not
an evaluation, so this difference is a hypothesis for the eval harness to test, not a result.

## Decision

The retrieval models run on `fastembed`:

- Embedding: `BAAI/bge-small-en-v1.5` (MIT license, 384 dimensions) is the default and current
  embedder.
- Comparison embedder: `BAAI/bge-base-en-v1.5` (768 dimensions) is registered beside it for an eval
  run that compares the two. It becomes the default only if the harness shows a recall gain worth
  its cost.
- Reranking: `jinaai/jina-reranker-v1-tiny-en` (Apache-2.0 license). It was faster and had a tighter
  spread than `ms-marco-MiniLM-L-6-v2`, and its license is stated on its model card, which the
  MiniLM card does not do.

This record replaces only the model choice in ADR 0002. The rest of ADR 0002, a local in-process
stack with an owned eval loop, is unchanged.

## Consequences

- No PyTorch in the retrieval path. The runtime and all three chosen models fit in about 550 MB of
  disk, and each model peaked under 1.3 GB of process memory when measured on its own. Memory with
  the embedder and reranker loaded together has not been measured.
- Both embedding dimensions are well under pgvector's 2000-dimension limit for an HNSW index.
- Running two embedders side by side uses the per-model columns from
  [ADR 0008](0008-per-model-embedding-columns.md). Comparing them, or switching the default later, is
  an additive change rather than a migration.
- The models are English-only and smaller than `bge-m3`, so their quality ceiling is lower. The MVP
  corpus is English ([ADR 0009](0009-mvp-corpus.md)), and the eval harness measures whether the
  quality is enough.
- Reranking costs about half a second per query for 20 candidates. The candidate count stays
  configurable and small, which matters more on this machine than the 50 candidates ADR 0002
  assumed.
- `fastembed` downloads model files on first use into a cache directory that stores files once and
  links them from a snapshot folder. Measure its disk use with `du`, not by summing file sizes, which
  counts each file twice.
