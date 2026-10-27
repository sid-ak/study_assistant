# rag_core_testing — Agent Context

`rag_core_testing` holds the test doubles and test data shared by every test suite that exercises
`rag_core`. It lives apart from `rag_core` so the library ships only code the application runs. See
the root [`AGENTS.md`](../../AGENTS.md) for project-wide context and
[`packages/rag_core/AGENTS.md`](../rag_core/AGENTS.md) for the protocols these fakes implement.

## Contents

- `store.py`: `InMemoryStore`, a fake of `rag_core.store.StoreProtocol`.
- `embedders.py`: `InMemoryEmbedderRegistry`, a fake of
  `rag_core.store.embedders.EmbedderRegistryProtocol`.
- `factories.py`: test data, such as the small-dimension `EMBEDDER_A` / `EMBEDDER_B` and
  `make_chunk`, which builds a valid `add_chunks` row.

## Conventions

- Dev-only. It is in the root `dev` dependency group and must never appear in a runtime
  package's `dependencies`. No module under any `src/` other than this package's imports it.
- A fake is a full implementation of its protocol, not a stub. It enforces every constraint the
  real backend enforces and raises the same `rag_core.store.errors` types. Checks shared with the
  real implementation come from `rag_core.store.validation`, not a copy.
- A fake is verified by `rag_core`'s parametrized contract suites (`test_store.py`,
  `test_embedder_registry.py`), which run every test against the fake and the DB implementation.
  Change a fake together with its protocol and real implementation, never on its own.
- New fakes or factories go here rather than in a package's `tests/` directory, so a later
  workspace member (CLI, services) can reuse them.
