"""Sphinx configuration for the Study Assistant documentation site.

Builds one static site from the all-Markdown documentation tree (via myst-parser) plus an autodoc
API reference for rag_core and the study CLI. Build with:

    uv run sphinx-build -b html docs site -W
"""

from __future__ import annotations

import sys
from pathlib import Path

# autodoc imports the packages to read their docstrings/type hints, so put their src-layout
# source on sys.path (the workspace install works too; this keeps the build self-contained).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "rag_core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "cli" / "src"))
sys.path.insert(0, str(REPO_ROOT / "evals" / "src"))
sys.path.insert(0, str(REPO_ROOT / "services" / "mcp_server" / "src"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api" / "src"))

# Import the MCP SDK while nothing else has been documented yet. Imported later, partway through the
# autodoc run, one of its pydantic models (mcp_types.SubscriptionFilter) fails to build with
# "The type annotation for `__pydantic_extra__` must be `dict[str, ...]`", which an import in a
# plain interpreter does not reproduce. Importing it here first lets autodoc reuse the loaded
# module.
import mcp  # noqa: E402, F401

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

# Generate GitHub-style slug anchors for headings (h1-h3) so in-page heading links such as
# [Goals](#goals) resolve as real in-site links instead of dead anchors.
myst_heading_anchors = 3

html_theme = "furo"
html_title = "Study Assistant"

# Fold type hints into the parameter descriptions rather than repeating them in the signature.
autodoc_typehints = "description"
autodoc_member_order = "bysource"

# The narrative docs (README, architecture, decision records) are authored to render on GitHub, so
# they carry repo-relative file and directory links that are not in-site targets. The
# README is included with :relative-docs: so its file links rewrite correctly; the residual
# directory-style links are the only remaining source of missing-xref warnings. Suppress just that
# one class so -W still fails on everything else (autodoc import errors, bad toctrees, broken
# anchors).
suppress_warnings = ["myst.xref_missing"]
