# 5. Documentation site tooling: Sphinx, MyST, and Furo

- Status: Accepted
- Date: 2026-07-01

## Context

The narrative docs (`architecture.md`, ADRs, `issues.md`, `checkpoints.md`) are already a
Markdown-only, docs-as-code tree. Once `rag_core` carries real typed modules (`config.py`,
`store/`, and later `ingest/`, `embed/`, `rerank/`, `retrieve/`), a second need shows up: a browsable
API reference generated from docstrings and the `mypy --strict` type hints already required by
`AGENTS.md`, rather than hand-written and prone to drifting from the code. Both halves — narrative
and generated reference — are wanted in one static site, deployed the same way the rest of the
project's automation works (a GitHub Actions workflow, alongside `sync-issues` and
`sync-checkpoints`).

An initial pass adopted MkDocs + `mkdocstrings` + Material for MkDocs and got as far as a working
`mkdocs.yml`, a generated API reference page, and a deploy workflow. That work surfaced a governance
problem rather than a technical one: MkDocs 2.0 (announced by a maintainer who took over the project
mid-2024) removes the plugin system entirely, has no migration path for existing projects, and is
currently unlicensed. Since `mkdocstrings` — the entire reason to use this stack — is itself a
plugin, pinning `mkdocs<2` only defers the exposure; it does not remove it. For a project being
written from scratch with no legacy MkDocs investment to protect, that is a reason to pick a
foundation without that single point of failure, not to work around it.

Several tool families were considered:

1. **MkDocs + Material + `mkdocstrings`** — the original pick. Excellent ergonomics and theme, but
   its core dependency (MkDocs itself) is mid-fork, with the maintainer removing the plugin system
   that `mkdocstrings` depends on and no announced compatibility story for existing users.
2. **Zensical** — a from-scratch static site generator built by the Material for MkDocs team,
   explicitly aimed at being a drop-in MkDocs 1.x replacement, and already listing `mkdocstrings` as
   a supported (Tier 1) plugin. Rejected for now: versioned `0.0.x`, and its own compatibility page
   states the plugin/module system's public API is deliberately being held back until no breaking
   changes are expected. Worth revisiting once it reaches a stable public API — migration should be
   closer to a drop-in swap than a rewrite by the team's own design goal.
3. **Decoupled: `pdoc` (API reference only) + plain Markdown narrative docs.** `pdoc` has no plugin
   system to fracture — it is a single, focused tool with nothing to depend on breaking. Rejected as
   the primary choice because it would abandon a unified site (nav, cross-linking, search across
   both narrative and reference) in exchange for a risk this project can avoid without that
   trade-off.
4. **Node-based site generators — Starlight (Astro), VitePress, Docusaurus.** All are mature, fast,
   and have no relation to the MkDocs governance problem. Rejected for this project specifically:
   none has a first-class Python docstring/type-hint introspection story equivalent to
   `autodoc`/`mkdocstrings` — generating the API reference would mean running a separate Python tool
   to emit Markdown and gluing it into the site, plus introducing a second runtime (Node) alongside
   the `uv` Python workspace this project otherwise keeps to one language end-to-end (per
   [ADR 0000](0000-stack.md)). Docusaurus in particular adds versioning/i18n machinery this
   single-user, single-corpus project (per [ADR 0003](0003-local-single-user-scope.md)) has no use
   for.
5. **Quarto.** A strong fit on paper given the project's ML/RAG content — it can execute Python code
   blocks live, which could embed real retrieval/generation output in the docs. Rejected for now:
   it is a separate non-Python binary/runtime (not a `uv` dev dependency), its docstring-to-reference
   story (`quartodoc`) is newer and far less mature than `autodoc`, and the live-execution capability
   is a genuine future enhancement rather than a current need. Worth reconsidering under a
   documentation "Future Scope" once retrieval/generation exist to demonstrate.
6. **Sphinx, with a modern theme (PyData Sphinx Theme, Sphinx Book Theme, or Furo).** The long-standing
   Python documentation standard, multi-maintainer governed with no comparable fork history, and
   `autodoc` integrates directly with docstrings and type hints. Historically dated default styling,
   but that is a theme problem, not a Sphinx problem — solved by pairing it with a modern theme.

## Decision

Adopt **Sphinx** with **`myst-parser`** (so the existing all-Markdown `docs/` tree needs no rewrite),
**`autodoc`** plus **`sphinx-autodoc-typehints`** for the generated API reference, and **Furo** as the
theme. Furo over PyData Sphinx Theme or Sphinx Book Theme specifically: PyData's version-switcher and
multi-project chrome targets scientific-package ecosystems this project doesn't have, and Sphinx Book
Theme leans toward long-form, Jupyter-book-style scientific text; Furo is minimal, actively
maintained, and closest in spirit to the clean single-project developer-tool look the MkDocs +
Material setup was chosen for in the first place.

The MkDocs-based setup (`mkdocs.yml`, the `mkdocstrings` reference page, the mkdocs deploy workflow,
and the corresponding dev dependencies) is removed rather than kept as a fallback — there is no
production site depending on it yet, so this is the cheapest point at which to switch.

## Consequences

- No second point of failure from a single maintainer's roadmap: Sphinx has a core-developer team
  with shared commit access, and no history comparable to the MkDocs 2.0 situation.
- Stays inside the `uv` Python workspace as a dev dependency, consistent with keeping the ML core and
  its tooling in one language and one workspace ([ADR 0000](0000-stack.md)) — no Node runtime (as
  Starlight/VitePress/Docusaurus would require) or separate binary (as Quarto would require) enters
  the toolchain.
- `myst-parser` means `architecture.md`, the ADRs, `issues.md`, and `checkpoints.md` are wired into a
  Sphinx `toctree` as-is; no content is rewritten into reStructuredText.
- Gives up things this project doesn't currently need: Docusaurus-grade versioning/i18n, Starlight's
  zero-client-JS search speed, and Quarto's live code execution. Quarto in particular is a candidate
  to revisit later, under a documentation "Future Scope," once retrieval/generation output exists to
  embed as living examples.
- Some Sphinx configuration and cross-referencing (`conf.py`, roles like `:py:class:`) is still
  reST-flavored under the hood even though page content is authored in Markdown — an accepted
  friction in exchange for governance stability and native `autodoc`/type-hint integration.
- Deployment follows the same pattern as the rest of the project's automation: a GitHub Actions
  workflow builds the site and publishes to GitHub Pages, split out from `ci.yaml` the same way
  `sync-issues` and `sync-checkpoints` already are.
