"""Shared fixtures for the eval harness tests: a small corpus ingested into the in-memory store.

The hashing embedder ranks chunks by shared words, so each question below is written to share
words with exactly one section, and the expected rankings are known without a model.
"""

from pathlib import Path

import pytest

from evals.golden import ExpectedSection, GoldenQuestion
from rag_core.ingest import ingest_folder
from rag_core_testing import HASHING_EMBEDDER, HashingEmbedder, InMemoryStore


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A folder with three sections across two documents, each about a different thing."""
    folder = tmp_path / "corpus"
    (folder / "ci").mkdir(parents=True)
    (folder / "build.md").write_text(
        "# Build\n\n## Presets\n\nRun cmake with the release preset.\n\n"
        "## Caching\n\nccache stores compiled objects.\n"
    )
    (folder / "ci" / "pthread.md").write_text(
        "# Failure\n\n## Cause\n\nlibpthread was not linked on the oldest image.\n"
    )
    return folder


@pytest.fixture
def embedder() -> HashingEmbedder:
    """The hashing embedder the store below was filled with."""
    return HashingEmbedder()


@pytest.fixture
def store(corpus: Path, embedder: HashingEmbedder) -> InMemoryStore:
    """An in-memory store holding the ``corpus`` folder's chunks."""
    store = InMemoryStore(embedder=HASHING_EMBEDDER)
    ingest_folder(corpus, store=store, embedder=embedder)
    return store


@pytest.fixture
def caching_question() -> GoldenQuestion:
    """A question whose words appear only in the Caching section, labeled with that section."""
    return GoldenQuestion(
        id="caching",
        text="ccache compiled objects",
        expected=(ExpectedSection("build.md", "Caching"),),
    )


@pytest.fixture
def mislabeled_question() -> GoldenQuestion:
    """A question about caching labeled with the Presets section, which it never ranks first."""
    return GoldenQuestion(
        id="mislabeled",
        text="ccache compiled objects",
        expected=(ExpectedSection("build.md", "Presets"),),
    )


@pytest.fixture
def golden_file(tmp_path: Path) -> Path:
    """A golden-set file with the caching question and one about the pthread failure."""
    path = tmp_path / "questions.toml"
    path.write_text(
        '[[questions]]\nid = "caching"\ntext = "ccache compiled objects"\n'
        'expected = [{ document = "build.md", section = "Caching" }]\n\n'
        '[[questions]]\nid = "pthread"\ntext = "libpthread linked oldest image"\n'
        'expected = [{ document = "ci/pthread.md", section = "Cause" }]\n'
    )
    return path
