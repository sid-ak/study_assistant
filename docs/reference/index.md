# API Reference

Generated from docstrings and the `mypy --strict` type hints by Sphinx autodoc (see
[ADR 0005](../decisions/0005-documentation-tooling.md)). One directive block per module, so the
reference stays navigable rather than one giant page.

## rag_core

```{eval-rst}
.. automodule:: rag_core
   :members:
   :undoc-members:
   :show-inheritance:
```

## Modules added as phases land

The following modules are not yet in the tree; add one `automodule` block each (identical in shape
to the `rag_core` block above) as they land:

- `rag_core.config` — settings
- `rag_core.store.client` — pgvector access
- `rag_core.store.schema` — table/index DDL
- later phases: `rag_core.ingest`, `rag_core.embed`, `rag_core.rerank`, `rag_core.retrieve`
