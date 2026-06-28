# Checkpoints

An append-only log of project checkpoints — one row per major iteration. It gives a human or a fresh
agent a quick history of how the project advanced and where it was left off.

Rows are appended automatically by the `sync-checkpoints` workflow
(`.github/workflows/sync-checkpoints.yaml`); don't hand-edit this file. A row is added when:

- a pull request that closes a `phase`-labeled issue is merged (checkpoint = the PR title), or
- a commit is pushed whose message is `#<number>-checkpoint: <text>` (checkpoint = `<text>`).

The Issue column is the leading number of the branch name, which must be the GitHub issue number
(e.g. `1-foundations` → `1`), or blank when the branch starts with no number (see
`CONTRIBUTING.md`).

| Date       | Branch          | Issue | Checkpoint                                                     |
| ---------- | --------------- | ----- | -------------------------------------------------------------- |
| 2026-06-27 | `1-foundations` | 1     | #1 Phase 0 — Foundations: uv workspace, pgvector stack, and CI |
