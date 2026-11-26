"""Markdown parsing: split a document into sections, each under the path of headings above it.

Only ATX headings (``#`` to ``######`` followed by a space) start a section. Setext headings, a
line of text underlined with ``===`` or ``---``, are read as ordinary text. Lines inside a fenced
code block are never headings, so a shell comment such as ``# configure`` stays code.
"""

import re
from dataclasses import dataclass

# One to six hashes, at least one space or tab, the heading text, then optional closing hashes.
# Group 1 is the hashes (their count is the level) and group 2 is the heading text.
HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")


@dataclass(frozen=True)
class Section:
    """The text under one heading, with the path of headings that lead to it, outermost first."""

    headings: tuple[str, ...]
    text: str


def fence_marker(line: str) -> str | None:
    """Return the run of three or more backticks or tildes that starts ``line``, or ``None``."""
    stripped = line.strip()
    for fence_char in ("`", "~"):
        if stripped.startswith(fence_char * 3):
            count = 0
            while count < len(stripped) and stripped[count] == fence_char:
                count += 1
            return stripped[:count]
    return None


def update_fence(open_fence: str | None, line: str) -> str | None:
    """Return the code fence that is open after ``line``, given the one open before it.

    A fence opens on a line that starts with three or more backticks or tildes, optionally followed
    by a language name. It closes only on a line that holds nothing but the same character, repeated
    at least as many times as the opening run.
    """
    marker = fence_marker(line)
    if marker is None:
        return open_fence
    if open_fence is None:
        return marker
    same_char = marker[0] == open_fence[0]
    long_enough = len(marker) >= len(open_fence)
    nothing_after = line.strip() == marker
    if same_char and long_enough and nothing_after:
        return None
    return open_fence


def trim_blank_edges(lines: list[str]) -> list[str]:
    """Return ``lines`` without the whitespace-only lines at its start and end."""
    start = 0
    end = len(lines)
    while start < end and lines[start].strip() == "":
        start += 1
    while end > start and lines[end - 1].strip() == "":
        end -= 1
    return lines[start:end]


def parse_sections(markdown: str) -> list[Section]:
    """Split ``markdown`` into sections at its ATX headings (``#`` to ``######``).

    Text above the first heading is a section with an empty heading path. A heading with no text of
    its own before the next heading produces no section. A deeper heading nests under the nearest
    shallower one above it, even when levels are skipped.
    """
    sections: list[Section] = []
    # The open headings, outermost first, each as (level, text).
    heading_stack: list[tuple[int, str]] = []
    body_lines: list[str] = []
    open_fence: str | None = None

    for line in markdown.splitlines():
        if open_fence is None:
            match = HEADING_PATTERN.match(line)
            if match is not None:
                add_section(sections, heading_stack, body_lines)
                level = len(match.group(1))
                # Close every open heading at this level or deeper.
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, match.group(2)))
                body_lines = []
                continue
        open_fence = update_fence(open_fence, line)
        body_lines.append(line)

    add_section(sections, heading_stack, body_lines)
    return sections


def add_section(
    sections: list[Section], heading_stack: list[tuple[int, str]], body_lines: list[str]
) -> None:
    """Append the section for ``body_lines`` under ``heading_stack``, unless it has no text."""
    trimmed = trim_blank_edges(body_lines)
    if not trimmed:
        return
    headings: list[str] = []
    for _, heading in heading_stack:
        headings.append(heading)
    sections.append(Section(headings=tuple(headings), text="\n".join(trimmed)))
