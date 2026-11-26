"""Tests for the retrieval metrics: label matching, recall, reciprocal rank, and percentiles."""

from typing import Any

import pytest

from evals.golden import ExpectedSection
from evals.metrics import chunk_matches, percentile, reciprocal_rank, section_recall

CACHING = ExpectedSection("build.md", "Caching")
CAUSE = ExpectedSection("ci/pthread.md", "Cause")


def chunk(source: str, *headings: str) -> dict[str, Any]:
    """Chunk metadata as ingestion writes it, for a chunk under ``headings`` in ``source``."""
    return {"source": source, "headings": list(headings), "section": " > ".join(headings)}


@pytest.mark.parametrize(
    ("metadata", "matched"),
    [
        (chunk("build.md", "Build", "Caching"), True),
        (chunk("build.md", "Build", "Caching", "Hit rate"), True),
        (chunk("build.md", "Build", "Presets"), False),
        (chunk("other.md", "Build", "Caching"), False),
        (chunk("build.md"), False),
    ],
    ids=["in the section", "in a subsection", "other section", "other document", "no headings"],
)
def test_chunk_matches_a_label_inside_its_section(metadata: dict[str, Any], matched: bool) -> None:
    """A chunk matches when it is from the labeled document and under the labeled heading."""
    assert chunk_matches(metadata, CACHING) is matched


def test_section_recall_is_the_share_of_labels_found() -> None:
    """Recall counts each label once, however many retrieved chunks fall in its section."""
    ranked = [chunk("build.md", "Build", "Caching"), chunk("build.md", "Build", "Caching")]

    assert section_recall(ranked, (CACHING,)) == 1.0
    assert section_recall(ranked, (CACHING, CAUSE)) == 0.5
    assert section_recall([], (CACHING, CAUSE)) == 0.0


def test_reciprocal_rank_uses_the_first_matching_chunk() -> None:
    """Reciprocal rank is one over the rank of the first chunk that matches any label."""
    ranked = [
        chunk("build.md", "Build", "Presets"),
        chunk("ci/pthread.md", "Failure", "Cause"),
        chunk("build.md", "Build", "Caching"),
    ]

    assert reciprocal_rank(ranked, (CACHING, CAUSE)) == 0.5
    assert reciprocal_rank(ranked, (CACHING,)) == pytest.approx(1 / 3)
    assert reciprocal_rank(ranked[:1], (CACHING,)) == 0.0


@pytest.mark.parametrize(
    ("values", "percent", "expected"),
    [
        ([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], 50, 5.0),
        ([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], 95, 10.0),
        ([40.0, 10.0, 30.0, 20.0], 50, 20.0),
        ([40.0, 10.0, 30.0, 20.0], 95, 40.0),
        ([7.5], 50, 7.5),
        ([7.5], 100, 7.5),
    ],
)
def test_percentile_is_the_nearest_rank_value(
    values: list[float], percent: float, expected: float
) -> None:
    """The p-th percentile is the smallest value with p percent of the values at or below it."""
    assert percentile(values, percent) == expected


@pytest.mark.parametrize(("values", "percent"), [([], 50), ([1.0], 0), ([1.0], 101)])
def test_percentile_rejects_empty_values_or_a_percent_out_of_range(
    values: list[float], percent: float
) -> None:
    """A percentile needs at least one value and a percent above 0 and at most 100."""
    with pytest.raises(ValueError):
        percentile(values, percent)
