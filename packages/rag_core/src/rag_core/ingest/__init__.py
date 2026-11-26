"""Ingestion: turning source documents into chunks ready to embed and store.

``parse_sections`` splits markdown into sections under their heading paths, and a
``ChunkerProtocol`` implementation turns a document into ``TextChunk`` values that carry their
source and section in ``metadata``.
"""

from rag_core.ingest.chunking import ChunkerProtocol, HeadingChunker, TextChunk
from rag_core.ingest.markdown import Section, parse_sections

__all__ = [
    "ChunkerProtocol",
    "HeadingChunker",
    "Section",
    "TextChunk",
    "parse_sections",
]
