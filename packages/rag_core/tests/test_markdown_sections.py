"""Behavior of ``parse_sections``: splitting markdown into sections under their heading paths."""

import pytest

from rag_core.ingest import Section, parse_sections


def test_text_before_any_heading_has_an_empty_heading_path() -> None:
    """Text above the first heading becomes a section with no headings."""
    sections = parse_sections("Intro line.\n\n# Title\n\nBody.")
    assert sections[0] == Section(headings=(), text="Intro line.")


def test_each_heading_starts_a_section_holding_its_body() -> None:
    """A heading's section holds the lines up to the next heading, without the heading line."""
    sections = parse_sections("# Build\n\nRun make.\n\n# Test\n\nRun ctest.\n")
    assert sections == [
        Section(headings=("Build",), text="Run make."),
        Section(headings=("Test",), text="Run ctest."),
    ]


def test_nested_headings_carry_their_parents() -> None:
    """A subheading's path lists every enclosing heading, outermost first."""
    markdown = "# Guide\n\nTop.\n\n## Install\n\nSteps.\n\n### Linux\n\napt install.\n"
    sections = parse_sections(markdown)
    assert [section.headings for section in sections] == [
        ("Guide",),
        ("Guide", "Install"),
        ("Guide", "Install", "Linux"),
    ]


def test_a_shallower_heading_closes_deeper_ones() -> None:
    """Returning to a higher level drops the deeper headings from the path."""
    markdown = "# A\n\n## B\n\nb text\n\n# C\n\nc text\n\n## D\n\nd text\n"
    sections = parse_sections(markdown)
    assert [section.headings for section in sections] == [("A", "B"), ("C",), ("C", "D")]


def test_a_skipped_level_still_nests_under_the_last_shallower_heading() -> None:
    """A ``###`` directly under a ``#`` nests under it, with no empty level in between."""
    sections = parse_sections("# A\n\n### C\n\ntext\n")
    assert sections == [Section(headings=("A", "C"), text="text")]


def test_headings_with_no_body_produce_no_section() -> None:
    """A heading followed only by subheadings contributes no empty section of its own."""
    sections = parse_sections("# Guide\n\n## Install\n\nSteps.\n")
    assert sections == [Section(headings=("Guide", "Install"), text="Steps.")]


@pytest.mark.parametrize(
    ("line", "heading"),
    [
        ("# Title", "Title"),
        ("###### Deepest", "Deepest"),
        ("## Closed ##", "Closed"),
        ("#   Padded   ", "Padded"),
    ],
)
def test_atx_heading_text_is_trimmed(line: str, heading: str) -> None:
    """Heading text drops the leading hashes, surrounding spaces, and any closing hashes."""
    sections = parse_sections(f"{line}\n\nbody\n")
    assert sections[0].headings == (heading,)


@pytest.mark.parametrize("line", ["#NoSpace", "####### Seven", "#hashtag in text"])
def test_lines_that_are_not_atx_headings_stay_body_text(line: str) -> None:
    """A hash run with no following space, or more than six hashes, is ordinary text."""
    sections = parse_sections(f"# Real\n\n{line}\n")
    assert sections == [Section(headings=("Real",), text=line)]


@pytest.mark.parametrize("fence", ["```", "~~~", "````"])
def test_hash_lines_inside_a_fenced_code_block_are_not_headings(fence: str) -> None:
    """A shell comment inside a code fence stays part of the section's text."""
    code = f"{fence}bash\n# configure the build\ncmake -S . -B build\n{fence}"
    sections = parse_sections(f"# Build\n\n{code}\n\nAfter.\n")
    assert sections == [Section(headings=("Build",), text=f"{code}\n\nAfter.")]


def test_a_fence_closes_only_on_its_own_marker() -> None:
    """A ``~~~`` line inside a backtick fence does not close it."""
    code = "```\n~~~\n# still code\n```"
    sections = parse_sections(f"# A\n\n{code}\n")
    assert sections == [Section(headings=("A",), text=code)]


def test_blank_lines_inside_a_section_are_kept_and_its_edges_trimmed() -> None:
    """Paragraph breaks survive; blank lines at the start and end of a section do not."""
    sections = parse_sections("# A\n\n\nfirst\n\nsecond\n\n\n")
    assert sections == [Section(headings=("A",), text="first\n\nsecond")]


def test_empty_document_has_no_sections() -> None:
    """Whitespace-only markdown yields no sections."""
    assert parse_sections("  \n\n") == []
