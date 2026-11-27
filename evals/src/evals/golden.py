"""The golden set: questions labeled with the document sections that answer them.

A label names a source document and one of its section headings, not a chunk id. Chunk ids and
boundaries change whenever the chunker changes, while a document's sections stay put, so labels
written this way keep working across re-chunking and re-embedding.

The file format is TOML, one ``[[questions]]`` table per question:

.. code-block:: toml

    [[questions]]
    id = "asan"
    text = "How do I turn on AddressSanitizer?"
    expected = [
        { document = "build_systems/sanitizers.md", section = "AddressSanitizer" },
    ]
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rag_core.ingest.markdown import parse_sections

# The keys a question table and an expected-section table may hold.
QUESTION_KEYS = {"id", "text", "expected"}
EXPECTED_KEYS = {"document", "section"}


class GoldenSetError(ValueError):
    """A golden-set file that cannot be read or does not follow the format."""


@dataclass(frozen=True)
class ExpectedSection:
    """A section that answers a question: a document path and one of its heading texts.

    ``document`` is the path relative to the ingested folder, as ingestion records it in each
    chunk's ``source``. ``section`` is a heading's text, without the leading ``#`` marks.
    """

    document: str
    section: str


@dataclass(frozen=True)
class GoldenQuestion:
    """One question of the golden set and every section that answers it."""

    id: str
    text: str
    expected: tuple[ExpectedSection, ...]


def load_golden(path: Path) -> list[GoldenQuestion]:
    """Read the golden set at ``path``, in file order.

    Raises ``GoldenSetError`` if the file is not valid TOML, has no questions, repeats an id, or
    has a question with a missing, empty, unknown, or non-string field, or with no expected
    sections.
    """
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise GoldenSetError(f"{path} is not valid TOML: {error}") from error

    tables = read_tables(data, "questions", str(path))
    if not tables:
        raise GoldenSetError(f"{path} has no questions.")

    questions: list[GoldenQuestion] = []
    seen_ids: set[str] = set()
    for position, table in enumerate(tables, start=1):
        check_keys(table, QUESTION_KEYS, f"question {position}")
        question_id = read_string(table, "id", f"question {position}")
        text = read_string(table, "text", f"question {question_id!r}")
        if question_id in seen_ids:
            raise GoldenSetError(f"Question id {question_id!r} appears more than once.")
        seen_ids.add(question_id)

        expected: list[ExpectedSection] = []
        for entry in read_tables(table, "expected", f"question {question_id!r}"):
            where = f"an expected section of question {question_id!r}"
            check_keys(entry, EXPECTED_KEYS, where)
            document = read_string(entry, "document", where)
            section = read_string(entry, "section", where)
            expected.append(ExpectedSection(document=document, section=section))
        if not expected:
            raise GoldenSetError(f"Question {question_id!r} has no expected sections.")

        questions.append(GoldenQuestion(id=question_id, text=text, expected=tuple(expected)))
    return questions


def read_tables(table: dict[str, Any], key: str, where: str) -> list[dict[str, Any]]:
    """The tables listed at ``table[key]``, or ``[]`` if it is absent.

    Raises ``GoldenSetError`` naming ``key`` if the value is not a list of tables.
    """
    value = table.get(key, [])
    is_list_of_tables = isinstance(value, list)
    tables: list[dict[str, Any]] = []
    if is_list_of_tables:
        for item in value:
            if isinstance(item, dict):
                tables.append(item)
            else:
                is_list_of_tables = False
    if not is_list_of_tables:
        raise GoldenSetError(f"{where} needs {key!r} to be a list of tables.")
    return tables


def check_keys(table: dict[str, Any], allowed: set[str], where: str) -> None:
    """Raise ``GoldenSetError`` if ``table`` has a key outside ``allowed``, such as a typo."""
    for key in table:
        if key not in allowed:
            raise GoldenSetError(f"Unknown key {key!r} in {where}.")


def read_string(table: dict[str, Any], key: str, where: str) -> str:
    """The non-empty string ``table[key]``, or ``GoldenSetError`` naming ``key`` and ``where``."""
    value = table.get(key)
    if not isinstance(value, str):
        raise GoldenSetError(f"{where} needs a string {key!r}.")
    if not value.strip():
        raise GoldenSetError(f"{where} has an empty {key!r}.")
    return value


def check_labels(questions: list[GoldenQuestion], folder: Path) -> None:
    """Check that every label in ``questions`` can match a chunk ingested from ``folder``.

    A label can match when its document exists under ``folder`` and the document has a heading,
    outside code blocks, whose text equals the label's section. Raises ``GoldenSetError`` listing
    every label that cannot.
    """
    problems: list[str] = []
    for question in questions:
        for expected in question.expected:
            path = folder / expected.document
            if not path.is_file():
                problems.append(f"{question.id}: no document {expected.document!r}")
                continue
            headings = document_headings(path.read_text(encoding="utf-8"))
            if expected.section not in headings:
                problems.append(
                    f"{question.id}: {expected.document!r} has no heading {expected.section!r}"
                )
    if problems:
        raise GoldenSetError("Labels that no chunk can match:\n" + "\n".join(problems))


def document_headings(markdown: str) -> set[str]:
    """The text of every heading that starts a section with text in ``markdown``, or encloses one.

    These are the headings that can appear in an ingested chunk's heading path. Headings inside
    code blocks are not headings, so they never appear.
    """
    headings: set[str] = set()
    for section in parse_sections(markdown):
        for heading in section.headings:
            headings.add(heading)
    return headings
