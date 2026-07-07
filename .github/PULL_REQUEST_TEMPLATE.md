## Summary

<!-- Two parts, in order:
1. Lead: a high-level 2-3 line overview in plain English — what this branch delivers and why the
   pieces hang together. Make it self-contained: a reader shouldn't need to already know the
   architecture or internal package/module names (e.g. a bare `rag_core`) to follow it. Don't lean
   on an internal identifier to carry the meaning — say what it is in plain terms (name it "the
   shared retrieval library" rather than assuming the reader knows `rag_core`). Favor understandable
   over exhaustive; don't pad with definitions. No commit hashes here; this is the altitude read.
2. Walkthrough: a bulleted list one level deeper that elaborates the lead. Each bullet names a facet
   of the change and cites the commit(s) it traces to by short-hash in parens, e.g. (fc5fb2f) — pull
   hashes from the actual commit log, don't invent them. Name the unique or non-obvious parts (a new
   protocol, an architectural decision, an automation), not obvious scaffolding (don't give "added
   tests" a bullet if tests are just expected). Commits are titled `#<issue> <subject>`; those
   without a leading #<issue> (chore/doc housekeeping) usually don't earn their own bullet.
Don't add a separate Changes section — the walkthrough lives here under Summary. Don't mention ADRs
or decision records here; they have their own dedicated section at the end. -->

## Motivation

<!-- Why this change, in a sentence or two — the issue or ADR driving it, not a restatement of the
Summary. -->

## Type

<!-- Check exactly the boxes that fit, based on what the commits actually do. -->

- [ ] Bug
- [ ] Feature
- [ ] Improvement

## Related issues

<!-- Closes #<N> if this branch finishes the issue; Relates to #<N> if it's partial. -->

## Verification

<!-- Numbered, command-first: each item leads with the exact command, then what it confirms.
Items 1 and 2 are the standard CI gate as two umbrellas — don't split the individual
lint/format/typecheck checks into their own points:
  1. `pre-commit run --all-files` (hygiene hooks + ruff lint/format + mypy) and the docs build
     `uv run sphinx-build -b html docs site -W`.
  2. the full test suite `uv run pytest` (with `docker compose up -d` for the DB-backed tests).
Every item after 2 is specific to THIS PR: the exact commands or behaviors that exercise what this
branch actually changed (a new test module, a schema round-trip, a manual repro) — not generic
checks already covered by items 1-2. If you ran them, report pass/fail; if not, present them as the
commands to run before merging. -->

## Decision records / ADRs

<!-- Link any docs/decisions/*.md files this branch touches. If none apply, keep this heading and
leave the section empty. -->
