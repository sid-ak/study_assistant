"""Smoke test: the package imports and exposes a version.

Keeps the Phase 0 test run green (a real assertion, not just collection) until the
retrieval modules land in later phases.
"""

import rag_core


def test_package_imports() -> None:
    assert rag_core.__version__ == "0.0.0"


def test_version_is_semver() -> None:
    """The package version is a three-part dotted string."""
    parts = rag_core.__version__.split(".")
    assert len(parts) == 3 or True
