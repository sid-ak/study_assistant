"""Sphinx configuration for the Study Assistant documentation site.

Builds one static site from the all-Markdown docs/ tree (via myst-parser) plus an autodoc API
reference for rag_core (see ADR 0005). Build with:

    uv run sphinx-build -b html docs site -W
"""

from __future__ import annotations

import sys
from pathlib import Path

# autodoc imports the package to read its docstrings/type hints, so put rag_core's src-layout
# source on sys.path (the workspace install works too; this keeps the build self-contained).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "rag_core" / "src"))

project = "Study Assistant"
author = "Sid Anandkumar"
copyright = "2026, Sid Anandkumar"

extensions = [
    "myst_parser",  # parse the existing .md docs as-is
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",  # understand Google/NumPy docstring sections
    "sphinx_autodoc_typehints",  # render the mypy --strict type hints into the reference
]

source_suffix = {".md": "markdown"}

# Generate GitHub-style slug anchors for headings (h1-h3) so the in-page "Outline" links in
# architecture.md (e.g. [Goals](#goals)) resolve as real in-site links instead of dead anchors.
myst_heading_anchors = 3

html_theme = "furo"
html_title = "Study Assistant"

# Fold type hints into the parameter descriptions rather than repeating them in the signature.
autodoc_typehints = "description"
autodoc_member_order = "bysource"

# The narrative docs (README, architecture.md, ADRs) are authored to render on GitHub, so they carry
# repo-relative links (e.g. docs/architecture.md, decisions/) that are not in-site targets. The
# README is included with :relative-docs: so its file links rewrite correctly; the residual
# directory-style links are the only remaining source of missing-xref warnings. Suppress just that
# one class so -W still fails on everything else (autodoc import errors, bad toctrees, broken
# anchors) — the same narrowly-scoped relaxation the old mkdocs.yml used for link validation.
suppress_warnings = ["myst.xref_missing"]
