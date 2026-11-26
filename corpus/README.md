# MVP corpus

`release_engineering/` is the document set the Phase 1.5 MVP ingests and evaluates against, as
recorded in [ADR 0009](../docs/decisions/0009-mvp-corpus.md). It describes Orbit, a fictional C++
service, through three kinds of markdown document:

- `build/`: build-system guides for CMake and Bazel.
- `releases/`: release notes for Orbit's versions.
- `ci/`: CI failure write-ups, each with the failing log excerpt, its cause, its fix, and how to
  prevent it.

Orbit, its versions, its flags that start with `--orbit-` or `ORBIT_`, and its error codes are
invented. The CMake, Bazel, compiler, and sanitizer options the documents describe are real.
The documents are written for this repository.

Ingest it with:

```sh
uv run study ingest corpus/release_engineering
```

This README sits outside `release_engineering/`, so it is not ingested.
