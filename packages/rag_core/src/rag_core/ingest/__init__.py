"""Ingestion: turning source documents into chunks ready to embed and store.

``parse_sections`` splits markdown into sections under their heading paths, and a
``ChunkerProtocol`` implementation turns a document into ``TextChunk`` values that carry their
source and section in ``metadata``. ``ingest_folder`` runs the whole path for a folder: chunk,
embed, and store each markdown file, skipping files already stored unchanged.
"""

from rag_core.ingest.chunking import ChunkerProtocol, HeadingChunker, TextChunk
from rag_core.ingest.markdown import Section, parse_sections
from rag_core.ingest.pipeline import IngestReport, ingest_folder

__all__ = [
    "ChunkerProtocol",
    "HeadingChunker",
    "IngestReport",
    "Section",
    "TextChunk",
    "ingest_folder",
    "parse_sections",
]
