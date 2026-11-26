"""Behavior of ``ingest_folder``: loading a folder of markdown files idempotently.

Each test runs against both stores through the ``store`` fixture, with ``HashingEmbedder`` in place
of a model, so ingestion writes and reads real rows in the database run.
"""

import hashlib
import uuid
from pathlib import Path

import pytest

from rag_core.ingest import HeadingChunker, IngestReport, ingest_folder
from rag_core.ingest.pipeline import DOCUMENT_ID_NAMESPACE
from rag_core.store import StoreProtocol
from rag_core.store.embedders import EmbedderInfo, EmbedderRegistryProtocol
from rag_core_testing import HASHING_EMBEDDER, HashingEmbedder


@pytest.fixture
def hashing_store(
    store: StoreProtocol, embedder_registry: EmbedderRegistryProtocol
) -> StoreProtocol:
    """An empty store bound to the hashing embedder's registered model."""
    embedder_registry.register(HASHING_EMBEDDER.model_id, HASHING_EMBEDDER.dimension)
    return store.with_embedder(HASHING_EMBEDDER)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A folder with two markdown files, one nested, and one file that is not markdown."""
    (tmp_path / "build.md").write_text("# Build\n\nRun cmake --preset release.\n")
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "pthread.md").write_text("# Failure\n\nundefined reference to pthread\n")
    (tmp_path / "notes.txt").write_text("not markdown")
    return tmp_path


def ingest(folder: Path, store: StoreProtocol) -> IngestReport:
    """Ingest ``folder`` into ``store`` with the hashing embedder and default chunking."""
    return ingest_folder(folder, store=store, embedder=HashingEmbedder())


def stored_sources(store: StoreProtocol) -> list[str]:
    """The ``source`` of every chunk a broad search returns, sorted."""
    query = HashingEmbedder().embed_query("build failure cmake pthread release")
    sources = []
    for row in store.search_dense(query, limit=100):
        sources.append(row["metadata"]["source"])
    return sorted(sources)


def test_every_markdown_file_is_added(corpus: Path, hashing_store: StoreProtocol) -> None:
    """Markdown files anywhere under the folder are ingested, named by relative path."""
    report = ingest(corpus, hashing_store)
    assert report.added == ["build.md", "ci/pthread.md"]
    assert report.unchanged == []
    assert report.replaced == []
    assert report.chunks_written == 2
    assert stored_sources(hashing_store) == ["build.md", "ci/pthread.md"]


def test_chunks_are_findable_by_their_content(corpus: Path, hashing_store: StoreProtocol) -> None:
    """An ingested chunk is the nearest result for a query about its text."""
    ingest(corpus, hashing_store)
    query = HashingEmbedder().embed_query("undefined reference to pthread")
    top = hashing_store.search_dense(query, limit=1)[0]
    assert top["metadata"]["source"] == "ci/pthread.md"
    assert top["metadata"]["section"] == "Failure"
    assert top["content"] == "Failure\n\nundefined reference to pthread"


def test_a_second_run_changes_nothing(corpus: Path, hashing_store: StoreProtocol) -> None:
    """Re-ingesting an unchanged folder writes nothing and reports every file as unchanged."""
    ingest(corpus, hashing_store)
    report = ingest(corpus, hashing_store)
    assert report.added == []
    assert report.unchanged == ["build.md", "ci/pthread.md"]
    assert report.chunks_written == 0
    assert stored_sources(hashing_store) == ["build.md", "ci/pthread.md"]


def test_a_changed_file_is_replaced(corpus: Path, hashing_store: StoreProtocol) -> None:
    """A file whose content changed has its old chunks replaced by the new ones."""
    ingest(corpus, hashing_store)
    (corpus / "build.md").write_text("# Build\n\nUse ninja.\n\n# Test\n\nRun ctest.\n")
    report = ingest(corpus, hashing_store)
    assert report.replaced == ["build.md"]
    assert report.unchanged == ["ci/pthread.md"]
    assert report.chunks_written == 2
    assert stored_sources(hashing_store) == ["build.md", "build.md", "ci/pthread.md"]
    contents = []
    for row in hashing_store.search_dense(HashingEmbedder().embed_query("build"), limit=100):
        contents.append(row["content"])
    assert "Build\n\nRun cmake --preset release." not in contents


def test_a_file_with_no_text_is_skipped(corpus: Path, hashing_store: StoreProtocol) -> None:
    """A markdown file with nothing to chunk is reported as empty and stores nothing."""
    (corpus / "blank.md").write_text("\n\n")
    report = ingest(corpus, hashing_store)
    assert report.empty == ["blank.md"]
    assert "blank.md" not in stored_sources(hashing_store)


def test_the_chunker_can_be_chosen(corpus: Path, hashing_store: StoreProtocol) -> None:
    """A given chunker is used in place of the default."""
    (corpus / "build.md").write_text("# Build\n\none two three four\n")
    report = ingest_folder(
        corpus,
        store=hashing_store,
        embedder=HashingEmbedder(),
        chunker=HeadingChunker(max_words=2),
    )
    # Each file has four body words, so a two-word budget gives two chunks per file.
    assert report.chunks_written == 4
    assert stored_sources(hashing_store) == [
        "build.md",
        "build.md",
        "ci/pthread.md",
        "ci/pthread.md",
    ]


def test_an_embedder_for_another_model_is_refused(
    corpus: Path, hashing_store: StoreProtocol
) -> None:
    """Ingestion refuses an embedder whose model differs from the store's, before writing."""
    other = HashingEmbedder(EmbedderInfo(model_id="test/other-model", dimension=64))
    with pytest.raises(ValueError, match="test/other-model"):
        ingest_folder(corpus, store=hashing_store, embedder=other)
    assert stored_sources(hashing_store) == []


def test_a_missing_folder_is_refused(tmp_path: Path, hashing_store: StoreProtocol) -> None:
    """A path that is not a folder raises instead of ingesting nothing."""
    with pytest.raises(NotADirectoryError):
        ingest(tmp_path / "missing", hashing_store)


def test_a_document_left_without_chunks_gets_them(
    corpus: Path, hashing_store: StoreProtocol
) -> None:
    """A document stored by a run that stopped before its chunks has them written next time."""
    data = (corpus / "build.md").read_bytes()
    hashing_store.add_document(
        id=uuid.uuid5(DOCUMENT_ID_NAMESPACE, "build.md"),
        filename="build.md",
        file_hash=hashlib.sha256(data).hexdigest(),
    )
    report = ingest(corpus, hashing_store)
    assert report.replaced == ["build.md"]
    assert report.added == ["ci/pthread.md"]
    assert stored_sources(hashing_store) == ["build.md", "ci/pthread.md"]


def test_a_file_that_is_not_utf8_is_reported_and_skipped(
    corpus: Path, hashing_store: StoreProtocol
) -> None:
    """A file that cannot be decoded as UTF-8 is listed as unreadable; the others still ingest."""
    (corpus / "a-latin1.md").write_bytes("# Café\n\nbr\xfbl\xe9\n".encode("latin-1"))
    report = ingest(corpus, hashing_store)
    assert report.unreadable == ["a-latin1.md"]
    assert report.added == ["build.md", "ci/pthread.md"]
    assert stored_sources(hashing_store) == ["build.md", "ci/pthread.md"]
