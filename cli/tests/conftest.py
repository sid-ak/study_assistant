"""Shared fixtures for the ``study`` CLI tests.

The CLI builds its real embedder, store, and registry in ``build_components``. These fixtures
replace that function with one returning in-memory fakes, so command tests run without a model or a
database.
"""

from pathlib import Path

import pytest

from rag_core_testing import (
    HASHING_EMBEDDER,
    HashingEmbedder,
    InMemoryEmbedderRegistry,
    InMemoryStore,
)
from study_cli import main as cli_main


@pytest.fixture
def components(monkeypatch: pytest.MonkeyPatch) -> cli_main.Components:
    """Fake components that ``main`` uses in place of the real model, store, and registry."""
    fakes = cli_main.Components(
        embedder=HashingEmbedder(),
        store=InMemoryStore(embedder=HASHING_EMBEDDER),
        registry=InMemoryEmbedderRegistry(),
    )

    def build_fakes(settings: object) -> cli_main.Components:
        """Return the fakes whatever the settings say."""
        return fakes

    monkeypatch.setattr(cli_main, "build_components", build_fakes)
    return fakes


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A folder holding two small markdown documents."""
    (tmp_path / "build.md").write_text("# Build\n\nRun cmake --preset release.\n")
    (tmp_path / "ci.md").write_text("# Failure\n\nundefined reference to pthread_create\n")
    return tmp_path
