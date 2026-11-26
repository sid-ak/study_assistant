"""Chunking: the ``ChunkerProtocol`` interface and the heading-aware ``HeadingChunker``."""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from rag_core.ingest.markdown import parse_sections, update_fence

# Joins the parts of a heading path into the breadcrumb line that opens a chunk.
BREADCRUMB_SEPARATOR = " > "


@dataclass(frozen=True)
class TextChunk:
    """One chunk of a document: the text to embed and store, and where it came from.

    ``metadata`` holds ``source`` (the document's path or name), ``section`` (the innermost heading,
    or ``""`` above the first heading), ``headings`` (the full heading path, outermost first), and
    ``chunk_index`` (the chunk's position in its document).
    """

    content: str
    metadata: dict[str, Any]


@runtime_checkable
class ChunkerProtocol(Protocol):
    """Structural interface for turning one document into chunks."""

    def chunk(self, markdown: str, source: str) -> list[TextChunk]:
        """Split ``markdown`` into chunks, in document order.

        Every word of the document's body text appears in exactly one chunk, in order. Each chunk's
        ``metadata`` names ``source``, its section, and its position. A document with no text gives
        no chunks.
        """
        ...


def count_words(text: str) -> int:
    """Number of whitespace-separated words in ``text``."""
    return len(text.split())


def pack(units: list[str], separator: str, max_words: int) -> list[str]:
    """Join consecutive ``units`` with ``separator`` into groups of at most ``max_words`` words.

    Units are added to the current group until the next one would overflow it. A unit that is over
    the budget on its own still becomes a group of its own.
    """
    groups: list[str] = []
    current: list[str] = []
    current_words = 0
    for unit in units:
        words = count_words(unit)
        if current and current_words + words > max_words:
            groups.append(separator.join(current))
            current = []
            current_words = 0
        current.append(unit)
        current_words += words
    if current:
        groups.append(separator.join(current))
    return groups


def split_blocks(text: str) -> list[str]:
    """Split ``text`` into blocks at blank lines, keeping each fenced code block in one block."""
    blocks: list[str] = []
    current: list[str] = []
    open_fence: str | None = None
    for line in text.split("\n"):
        is_blank = line.strip() == ""
        if is_blank and open_fence is None:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        open_fence = update_fence(open_fence, line)
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


class HeadingChunker:
    """Chunker that keeps each chunk inside one markdown section.

    Each chunk starts with a breadcrumb line, the section's heading path joined by `` > ``, so the
    embedded text says where it sits in the document. A section that fits in ``max_words`` body
    words is one chunk. A longer one is split at the largest boundary that fits: between
    paragraphs or code blocks first, then between lines, then between words.
    """

    def __init__(self, max_words: int = 200) -> None:
        """Set the largest number of body words one chunk may hold; it must be at least one."""
        if max_words < 1:
            raise ValueError(f"max_words must be at least 1, not {max_words}.")
        self.max_words = max_words

    def chunk(self, markdown: str, source: str) -> list[TextChunk]:
        """Split ``markdown`` into chunks that each stay inside one section."""
        chunks: list[TextChunk] = []
        for section in parse_sections(markdown):
            headings = list(section.headings)
            if headings:
                section_name = headings[-1]
            else:
                section_name = ""
            for body in self.split_section(section.text):
                if headings:
                    content = BREADCRUMB_SEPARATOR.join(headings) + "\n\n" + body
                else:
                    content = body
                metadata = {
                    "source": source,
                    "section": section_name,
                    "headings": headings,
                    "chunk_index": len(chunks),
                }
                chunks.append(TextChunk(content=content, metadata=metadata))
        return chunks

    def split_section(self, text: str) -> list[str]:
        """Split one section's text into bodies of at most ``max_words`` words each."""
        units: list[str] = []
        for block in split_blocks(text):
            if count_words(block) <= self.max_words:
                units.append(block)
            else:
                units.extend(self.split_block(block))
        return pack(units, "\n\n", self.max_words)

    def split_block(self, block: str) -> list[str]:
        """Split an oversized block between lines, and an oversized line between words."""
        pieces: list[str] = []
        for line in block.split("\n"):
            if count_words(line) <= self.max_words:
                pieces.append(line)
                continue
            words = line.split()
            for start in range(0, len(words), self.max_words):
                pieces.append(" ".join(words[start : start + self.max_words]))
        return pack(pieces, "\n", self.max_words)
