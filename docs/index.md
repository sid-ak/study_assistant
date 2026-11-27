```{include} ../README.md
:relative-docs: docs/
:relative-images:
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Project

architecture.md
walkthrough.md
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: API

reference/index.md
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: Decisions (ADRs)

Overview <decisions/README.md>
decisions/0000-stack.md
decisions/0001-rag-retrieval-boundary.md
decisions/0002-local-embedding-and-reranking.md
decisions/0003-local-single-user-scope.md
decisions/0004-cli-batch-ingestion.md
decisions/0005-documentation-tooling.md
decisions/0006-interface-first-architecture.md
decisions/0007-generation-backend.md
decisions/0008-per-model-embedding-columns.md
decisions/0009-mvp-corpus.md
decisions/0010-lightweight-embedding-and-reranking-models.md
decisions/0011-free-hosted-generation.md
decisions/0012-bounded-agent-over-mcp.md
```
