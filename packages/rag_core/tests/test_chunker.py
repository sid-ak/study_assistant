"""Behavior of markdown chunkers.

The contract tests at the top take ``chunker: ChunkerProtocol`` and run against every
implementation. The tests below them pin what only ``HeadingChunker`` does: one section per chunk,
a heading breadcrumb, and splitting oversized sections at the largest boundary that fits.
"""

import pytest

from rag_core.ingest import ChunkerProtocol, HeadingChunker, TextChunk

DOCUMENT = """Preamble before any heading.

# Build

Configure with CMake, then build.

## Presets

Use the release preset for shipping builds.

```bash
# configure

cmake --preset release
```

# Test

Run ctest from the build folder.
"""


@pytest.fixture(params=[HeadingChunker])
def chunker(request: pytest.FixtureRequest) -> ChunkerProtocol:
    """Every ``ChunkerProtocol`` implementation, once each, with its default settings."""
    implementation: type[ChunkerProtocol] = request.param
    return implementation()


def body_words(chunk: TextChunk) -> list[str]:
    """The words of a chunk's content after its breadcrumb line, if it has one."""
    content = chunk.content
    if chunk.metadata["headings"]:
        _, _, content = content.partition("\n\n")
    return content.split()


def test_conforms_to_the_protocol(chunker: ChunkerProtocol) -> None:
    """Each implementation satisfies ``ChunkerProtocol`` at run time."""
    assert isinstance(chunker, ChunkerProtocol)


def test_empty_document_gives_no_chunks(chunker: ChunkerProtocol) -> None:
    """A document with no text produces no chunks."""
    assert chunker.chunk("\n  \n", source="empty.md") == []


def test_every_chunk_names_its_source(chunker: ChunkerProtocol) -> None:
    """Each chunk's metadata carries the source it was given."""
    chunks = chunker.chunk(DOCUMENT, source="docs/build.md")
    assert chunks
    for chunk in chunks:
        assert chunk.metadata["source"] == "docs/build.md"


def test_chunk_indexes_count_up_from_zero(chunker: ChunkerProtocol) -> None:
    """``chunk_index`` is each chunk's position in the document."""
    chunks = chunker.chunk(DOCUMENT, source="a.md")
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == list(range(len(chunks)))


def test_every_chunk_names_its_section(chunker: ChunkerProtocol) -> None:
    """``section`` is the innermost heading and ``headings`` the full path to it."""
    chunks = chunker.chunk(DOCUMENT, source="a.md")
    for chunk in chunks:
        headings = chunk.metadata["headings"]
        expected_section = headings[-1] if headings else ""
        assert chunk.metadata["section"] == expected_section
    assert {tuple(chunk.metadata["headings"]) for chunk in chunks} == {
        (),
        ("Build",),
        ("Build", "Presets"),
        ("Test",),
    }


def test_no_body_text_is_lost(chunker: ChunkerProtocol) -> None:
    """Every word under the headings appears in the chunks, in document order."""
    chunks = chunker.chunk(DOCUMENT, source="a.md")
    words: list[str] = []
    for chunk in chunks:
        words.extend(body_words(chunk))
    heading_lines = {"# Build", "## Presets", "# Test"}
    expected: list[str] = []
    for line in DOCUMENT.splitlines():
        if line not in heading_lines:
            expected.extend(line.split())
    assert words == expected


def test_breadcrumb_heads_each_chunk_under_a_heading() -> None:
    """Content starts with the heading path joined by `` > ``, then a blank line, then the body."""
    chunks = HeadingChunker().chunk("# Build\n\n## Presets\n\nUse presets.\n", source="a.md")
    assert chunks == [
        TextChunk(
            content="Build > Presets\n\nUse presets.",
            metadata={
                "source": "a.md",
                "section": "Presets",
                "headings": ["Build", "Presets"],
                "chunk_index": 0,
            },
        )
    ]


def test_text_before_any_heading_has_no_breadcrumb() -> None:
    """A chunk with no heading path is its body alone."""
    chunks = HeadingChunker().chunk("Just a note.\n", source="a.md")
    assert chunks[0].content == "Just a note."
    assert chunks[0].metadata["section"] == ""


def test_a_chunk_never_spans_two_sections() -> None:
    """Short sections stay separate chunks even when they would fit together."""
    chunks = HeadingChunker(max_words=100).chunk("# A\n\none\n\n# B\n\ntwo\n", source="a.md")
    assert [chunk.content for chunk in chunks] == ["A\n\none", "B\n\ntwo"]


def test_paragraphs_are_packed_until_the_word_budget_is_full() -> None:
    """Whole paragraphs are grouped greedily, and a paragraph that would overflow starts a chunk."""
    markdown = "# A\n\none two three four\n\nfive six seven eight\n\nnine ten eleven twelve\n"
    chunks = HeadingChunker(max_words=8).chunk(markdown, source="a.md")
    assert [chunk.content for chunk in chunks] == [
        "A\n\none two three four\n\nfive six seven eight",
        "A\n\nnine ten eleven twelve",
    ]


def test_a_code_fence_with_blank_lines_stays_whole() -> None:
    """A fenced block is one unit, so a blank line inside it is not a split point."""
    code = "```\nline one\n\nline two\n```"
    chunks = HeadingChunker(max_words=6).chunk(f"# A\n\n{code}\n", source="a.md")
    assert [chunk.content for chunk in chunks] == [f"A\n\n{code}"]


def test_an_oversized_block_is_split_between_lines() -> None:
    """A block over the budget splits at line breaks, keeping each line whole."""
    code = "```\none two\nthree four\nfive six\n```"
    chunks = HeadingChunker(max_words=4).chunk(f"# A\n\n{code}\n", source="a.md")
    assert [chunk.content for chunk in chunks] == [
        "A\n\n```\none two",
        "A\n\nthree four\nfive six",
        "A\n\n```",
    ]


def test_an_oversized_line_is_split_between_words() -> None:
    """A single line over the budget splits into runs of at most ``max_words`` words."""
    chunks = HeadingChunker(max_words=3).chunk("# A\n\na b c d e f g\n", source="a.md")
    assert [chunk.content for chunk in chunks] == ["A\n\na b c", "A\n\nd e f", "A\n\ng"]


@pytest.mark.parametrize("max_words", [0, -1])
def test_max_words_must_be_positive(max_words: int) -> None:
    """A word budget below one is refused when the chunker is built."""
    with pytest.raises(ValueError):
        HeadingChunker(max_words=max_words)


def test_default_budget_fits_the_embedding_models_input() -> None:
    """The default is 120 body words, under 512 tokens even at 4.1 tokens per word.

    4.1 is the highest tokens-per-word ratio measured on the corpus, in chunks that are mostly
    code or log excerpts; prose is nearer 1.8. bge models truncate input past 512 tokens.
    """
    assert HeadingChunker().max_words == 120
