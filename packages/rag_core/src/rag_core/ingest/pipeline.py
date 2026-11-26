"""Folder ingestion: chunk, embed, and store every markdown file under a folder.

A document's id is derived from its path relative to the folder, and its content is identified by
a SHA-256 hash of the file's bytes. Re-running over the same folder therefore finds each document
again and only writes what changed:

- A file whose content is already stored, with chunks, is left alone.
- A file whose path was ingested before with other content has its old chunks replaced.
- Everything else is added.

A file is chunked and embedded before anything is written for it, so a failure in either step
leaves the store untouched. If a run stops between storing a document and its chunks, the next run
sees a document with no chunks and writes them.

A file that is not valid UTF-8 is reported as unreadable and skipped, and the run continues.

Some cases are not reconciled:

- A file removed from the folder keeps its stored document.
- A file moved to a new path with the same content keeps its old path until its content changes.
- Two files with identical bytes share one stored document, because content is identified by its
  hash. The second is reported as unchanged. If the first is later edited, the shared content is
  stored again under the second path when the run reaches it, which may be the next run.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag_core.embed.binding import check_same_model
from rag_core.embed.protocol import EmbedderProtocol
from rag_core.ingest.chunking import ChunkerProtocol, HeadingChunker
from rag_core.store.errors import DuplicateIdError
from rag_core.store.protocol import StoreProtocol

# Namespace for document ids: uuid5 of this and a relative path is the same on every run.
DOCUMENT_ID_NAMESPACE = uuid.UUID("6f1c2a54-8d0e-4b7a-9a43-2f5e0c9b1d17")


@dataclass
class IngestReport:
    """What one ingestion run did, file by file, named by path relative to the folder."""

    added: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    chunks_written: int = 0


def markdown_files(folder: Path) -> list[tuple[str, Path]]:
    """Every ``*.md`` file under ``folder``, as (relative POSIX path, full path), sorted by path."""
    found: list[tuple[str, Path]] = []
    for path in folder.rglob("*.md"):
        if path.is_file():
            found.append((path.relative_to(folder).as_posix(), path))
    found.sort()
    return found


def ingest_folder(
    folder: Path,
    *,
    store: StoreProtocol,
    embedder: EmbedderProtocol,
    chunker: ChunkerProtocol | None = None,
) -> IngestReport:
    """Ingest every ``*.md`` file under ``folder`` into ``store``, and report what changed.

    ``store`` must be bound to ``embedder``'s model, or ``ValueError`` is raised before anything is
    read. ``chunker`` defaults to a ``HeadingChunker`` with its default size. Raises
    ``NotADirectoryError`` if ``folder`` is not a folder.
    """
    check_same_model(embedder, store)
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} is not a folder.")
    if chunker is None:
        chunker = HeadingChunker()

    report = IngestReport()
    for source, path in markdown_files(folder):
        data = path.read_bytes()
        file_hash = hashlib.sha256(data).hexdigest()

        stored = store.get_document_by_hash(file_hash)
        if stored is not None and store.get_chunks_by_document(stored["id"]):
            report.unchanged.append(source)
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # One file in another encoding must not stop the rest of the folder.
            report.unreadable.append(source)
            continue
        chunks = chunker.chunk(text, source=source)
        if not chunks:
            report.empty.append(source)
            continue
        texts = [chunk.content for chunk in chunks]
        embeddings = embedder.embed_documents(texts)

        document_id = uuid.uuid5(DOCUMENT_ID_NAMESPACE, source)
        try:
            stored_id = store.add_document(id=document_id, filename=source, file_hash=file_hash)
            if stored is None:
                report.added.append(source)
            else:
                # The document was stored by an earlier run that stopped before its chunks.
                report.replaced.append(source)
        except DuplicateIdError:
            # This path was ingested before with other content: drop that version and its chunks.
            store.delete_document(document_id)
            stored_id = store.add_document(id=document_id, filename=source, file_hash=file_hash)
            report.replaced.append(source)

        rows: list[dict[str, Any]] = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            rows.append(
                {
                    "id": uuid.uuid5(stored_id, str(chunk.metadata["chunk_index"])),
                    "document_id": stored_id,
                    "content": chunk.content,
                    "metadata": chunk.metadata,
                    "embedding": embedding,
                }
            )
        store.add_chunks(rows)
        report.chunks_written += len(rows)
    return report
