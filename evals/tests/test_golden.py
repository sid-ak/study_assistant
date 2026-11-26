"""Tests for reading a golden set: labeled questions with the sections that answer them."""

from pathlib import Path

import pytest

from evals.golden import ExpectedSection, GoldenQuestion, GoldenSetError, load_golden

TWO_QUESTIONS = """
[[questions]]
id = "asan"
text = "How do I turn on AddressSanitizer?"
expected = [
    { document = "build_systems/sanitizers.md", section = "AddressSanitizer" },
]

[[questions]]
id = "pthread"
text = "Why does the link fail with undefined reference to pthread_create?"
expected = [
    { document = "ci/undefined-reference-pthread-create.md", section = "Cause" },
    { document = "build_systems/cmake-dependencies.md", section = "Threads" },
]
"""


def write_golden(folder: Path, text: str) -> Path:
    """Write ``text`` to a golden-set file in ``folder`` and return its path."""
    path = folder / "questions.toml"
    path.write_text(text)
    return path


def test_load_golden_reads_questions_in_file_order(tmp_path: Path) -> None:
    """Questions come back in the order the file lists them, with every expected section."""
    questions = load_golden(write_golden(tmp_path, TWO_QUESTIONS))

    assert questions == [
        GoldenQuestion(
            id="asan",
            text="How do I turn on AddressSanitizer?",
            expected=(ExpectedSection("build_systems/sanitizers.md", "AddressSanitizer"),),
        ),
        GoldenQuestion(
            id="pthread",
            text="Why does the link fail with undefined reference to pthread_create?",
            expected=(
                ExpectedSection("ci/undefined-reference-pthread-create.md", "Cause"),
                ExpectedSection("build_systems/cmake-dependencies.md", "Threads"),
            ),
        ),
    ]


INVALID_GOLDEN_SETS = {
    "no questions": ("", "no questions"),
    "duplicate id": (
        """
[[questions]]
id = "asan"
text = "First?"
expected = [{ document = "a.md", section = "A" }]

[[questions]]
id = "asan"
text = "Second?"
expected = [{ document = "b.md", section = "B" }]
""",
        "asan",
    ),
    "no expected sections": (
        """
[[questions]]
id = "asan"
text = "How do I turn on AddressSanitizer?"
expected = []
""",
        "asan",
    ),
    "missing text": (
        """
[[questions]]
id = "asan"
expected = [{ document = "a.md", section = "A" }]
""",
        "text",
    ),
    "empty text": (
        """
[[questions]]
id = "asan"
text = "  "
expected = [{ document = "a.md", section = "A" }]
""",
        "asan",
    ),
    "unknown question key": (
        """
[[questions]]
id = "asan"
text = "How do I turn on AddressSanitizer?"
expect = [{ document = "a.md", section = "A" }]
""",
        "expect",
    ),
    "expected section without document": (
        """
[[questions]]
id = "asan"
text = "How do I turn on AddressSanitizer?"
expected = [{ section = "A" }]
""",
        "document",
    ),
    "unknown expected key": (
        """
[[questions]]
id = "asan"
text = "How do I turn on AddressSanitizer?"
expected = [{ document = "a.md", section = "A", heading = "B" }]
""",
        "heading",
    ),
    "questions not a list of tables": ('questions = "asan"\n', "questions"),
    "expected not a list of tables": (
        """
[[questions]]
id = "asan"
text = "How do I turn on AddressSanitizer?"
expected = "build_systems/sanitizers.md"
""",
        "expected",
    ),
    "non-string field": (
        """
[[questions]]
id = 7
text = "How do I turn on AddressSanitizer?"
expected = [{ document = "a.md", section = "A" }]
""",
        "id",
    ),
}


@pytest.mark.parametrize(
    ("text", "named"), INVALID_GOLDEN_SETS.values(), ids=INVALID_GOLDEN_SETS.keys()
)
def test_load_golden_rejects_an_invalid_set(tmp_path: Path, text: str, named: str) -> None:
    """A malformed golden set raises ``GoldenSetError`` naming the field or question at fault."""
    with pytest.raises(GoldenSetError, match=named):
        load_golden(write_golden(tmp_path, text))


def test_load_golden_rejects_invalid_toml(tmp_path: Path) -> None:
    """A file that is not valid TOML raises ``GoldenSetError`` rather than a parser error."""
    with pytest.raises(GoldenSetError):
        load_golden(write_golden(tmp_path, "[[questions]\nid = "))
