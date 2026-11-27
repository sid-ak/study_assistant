# study_cli — Agent Context

`study_cli` is the `study` console script, the batch entry point for ingestion and retrieval. See
the root [`AGENTS.md`](../AGENTS.md) for project-wide context and
[`docs/architecture.md`](../docs/architecture.md) for where it sits. The ADRs that bind it are the
retrieval boundary (0001) and CLI batch ingestion (0004).

## Surface

- `study ingest <folder>`: prepares the schema, registers the configured embedding model (making
  it current if none is), and ingests every markdown file under the folder. Re-runs write only
  what changed.
- `study embed`: registers the configured embedding model, without making it current if another
  model is, and embeds every stored chunk that model has no vector for. Ingestion skips files
  whose content is already stored, so this is how a second model gets vectors for the existing
  corpus. Run it with `EMBEDDING_MODEL` and `EMBEDDING_DIMENSION` set for that model.
- `study query "<text>" [--limit N] [--ef-search N]`: prints the nearest chunks with their rank,
  cosine distance, chunk id, and source with heading path, then the result count, the latency in
  milliseconds, the model, `ef_search`, and the reranker when `RERANK_ENABLED` is on. The model is loaded with a warm-up query before the
  timed search, so the latency covers embedding the query and searching, not model loading.

## Conventions

- A consumer of `rag_core`, never a reimplementer. Parsing, chunking, embedding, storage, and
  retrieval logic live in `rag_core`; a command only wires settings and components to a
  `rag_core` function and prints the result. If a command needs new behavior, add it to
  `rag_core` with its tests there.
- Commands depend on the protocols (`EmbedderProtocol`, `StoreProtocol`,
  `EmbedderRegistryProtocol`) through the `Components` dataclass. `main` builds the real ones from
  `Settings` in `build_components`; nothing else constructs a concrete class.
- Each command is a `run_<name>(..., components) -> int` function returning the exit status: 0 on
  success, 2 (`USAGE_ERROR`) for bad input such as a missing folder, with the message on stderr.
- Tests replace `build_components` with in-memory fakes through the `components` fixture in
  `tests/conftest.py`, so the command tests need no model and no database. The DB-backed path is
  covered by `rag_core`'s own ingestion and retrieval tests.
