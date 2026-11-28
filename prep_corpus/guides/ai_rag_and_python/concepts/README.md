# Concepts

> Part of [AI, RAG & Python](../README.md)

General concepts behind retrieval-augmented generation, independent of any one codebase. Each page
defines its terms on first use and explains each idea by its mechanism, so it applies to any RAG
system. A page grows a new section when a later stage of the [Project](../project/README.md) needs a
concept it does not yet cover.

---

## Pages

| Page | What it covers |
| ---- | -------------- |
| [RAG Overview](01-rag-overview.md) | What retrieval-augmented generation is, the problem it solves, and the stages of the pipeline |
| [Vector Space and Similarity](02-vector-space-and-similarity.md) | Vectors and dimensions, dot product, Euclidean distance, cosine similarity, and normalization |
| [Embeddings](03-embeddings.md) | How embedding models turn text into vectors: tokens, pooling, bi-encoders, contrastive training, model size, and query prefixes |
| [Chunking](04-chunking.md) | Why documents are split, fixed-size and structure-aware chunking, overlap, and chunk size trade-offs |
| [Retrieval](05-retrieval.md) | Dense search, exact and approximate nearest-neighbor search, HNSW and its parameters, lexical search with TF-IDF and BM25, and hybrid search with Reciprocal Rank Fusion |
| [Reranking](06-reranking.md) | Cross-encoders against bi-encoders, retrieve then rerank, latency cost, and reranker scores as relevance grades |
| [Generation](07-generation.md) | How a language model produces text, context windows, grounding and citations, structured output, and rate limits |
| [Agents and Tools](08-agents-and-tools.md) | Agent loops as state machines, tool calling and tool design, the Model Context Protocol, bounded loops, checkpointing, and human-in-the-loop approval |
| [Evaluation](09-evaluation.md) | Golden sets, Recall@K, Mean Reciprocal Rank, latency percentiles, comparing runs, and grounding checks for generated answers |
