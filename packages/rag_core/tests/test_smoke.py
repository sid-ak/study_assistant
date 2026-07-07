"""Smoke test: the package imports and exposes a version.

Keeps the Phase 0 test run green (a real assertion, not just collection) until the
retrieval modules land in later phases.
"""

import rag_core


def test_package_imports() -> None:
    """rag_core imports and exposes its version string."""
    assert rag_core.__version__ == "0.0.0"
