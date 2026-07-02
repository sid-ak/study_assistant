# Checkpoints

An append-only log of project checkpoints — one row per major iteration. It gives a human or a fresh
agent a quick history of how the project advanced and where it was left off.

Rows are appended automatically by the `sync-checkpoints` workflow
(`.github/workflows/sync-checkpoints.yaml`) when a pull request is merged into `dev`; don't
hand-edit this file. A row is added when the merged PR either:

- closes a `phase`-labeled issue (checkpoint = the PR title), or
- carries a `checkpoint: <text>` commit (checkpoint = `<text>`, one row per such commit); an
  optional `#<number>-` prefix sets the Issue column, otherwise it comes from the PR branch.

The Issue column is the leading number of the branch name, which must be the GitHub issue number
(e.g. `1-foundations` → `1`), or blank when the branch starts with no number (see
`CONTRIBUTING.md`).

| Date       | Branch          | Issue | Checkpoint                                                     |
| ---------- | --------------- | ----- | -------------------------------------------------------------- |
| 2026-06-27 | `1-foundations` | 1     | #1 Phase 0 — Foundations: uv workspace, pgvector stack, and CI |
| 2026-07-02 | `2-phase-1-add-docs` | 2 | docs site test |
| 2026-07-02 | `2-phase-1-add-docs` | 2 | testing sync-checkpoints. |
