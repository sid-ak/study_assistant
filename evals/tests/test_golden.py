"""Tests for reading a golden set: labeled questions with the sections that answer them."""

from pathlib import Path

import pytest

from evals.golden import (
    ExpectedSection,
    GoldenQuestion,
    GoldenSetError,
    check_labels,
    load_golden,
)

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


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_GOLDEN = REPO_ROOT / "evals" / "golden" / "questions.toml"
COMMITTED_CORPUS = REPO_ROOT / "corpus" / "release_engineering"


def question(question_id: str, document: str, section: str) -> GoldenQuestion:
    """A golden question with one expected section."""
    return GoldenQuestion(
        id=question_id, text="Any question?", expected=(ExpectedSection(document, section),)
    )


@pytest.fixture
def small_corpus(tmp_path: Path) -> Path:
    """A folder with one document whose code block holds a line that looks like a heading."""
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "failure.md").write_text(
        "# Failure\n\nIntro.\n\n## Fix\n\n```bash\n# Not a heading\nmake\n```\n"
    )
    return tmp_path


def test_check_labels_accepts_headings_of_existing_documents(small_corpus: Path) -> None:
    """Labels naming a document's top heading or a nested heading are both valid."""
    check_labels(
        [question("top", "ci/failure.md", "Failure"), question("fix", "ci/failure.md", "Fix")],
        small_corpus,
    )


@pytest.mark.parametrize(
    ("label", "named"),
    [
        (("missing", "ci/absent.md", "Fix"), "ci/absent.md"),
        (("typo", "ci/failure.md", "Fixes"), "Fixes"),
        (("fenced", "ci/failure.md", "Not a heading"), "Not a heading"),
    ],
    ids=["missing document", "missing heading", "heading inside a code block"],
)
def test_check_labels_rejects_a_label_nothing_can_match(
    small_corpus: Path, label: tuple[str, str, str], named: str
) -> None:
    """A label whose document or heading does not exist raises ``GoldenSetError`` naming it."""
    question_id, document, section = label
    with pytest.raises(GoldenSetError, match=named):
        check_labels([question(question_id, document, section)], small_corpus)


def test_check_labels_reports_every_bad_label_at_once(small_corpus: Path) -> None:
    """One error lists every bad label, so a broken golden set is fixed in one pass."""
    with pytest.raises(GoldenSetError) as raised:
        check_labels(
            [
                question("first", "ci/absent.md", "Fix"),
                question("second", "ci/failure.md", "Fixes"),
            ],
            small_corpus,
        )
    assert "first" in str(raised.value)
    assert "second" in str(raised.value)


def test_committed_golden_set_labels_match_the_committed_corpus() -> None:
    """Every label in the committed golden set names a heading of a committed corpus document."""
    questions = load_golden(COMMITTED_GOLDEN)

    check_labels(questions, COMMITTED_CORPUS)
    assert len(questions) == 10
