"""Retrieval metrics over one question's ranked chunks, and percentiles over latencies.

The ranked chunks are given by their ``metadata``, as ingestion writes it: ``source`` is the
document path and ``headings`` the heading path from the document's top heading down.
"""

import math
from typing import Any

from evals.golden import ExpectedSection


def chunk_matches(metadata: dict[str, Any], expected: ExpectedSection) -> bool:
    """Whether a chunk comes from ``expected``'s document and lies inside its section.

    A chunk lies inside a section when the section's heading is anywhere in the chunk's heading
    path, so chunks from its subsections match too.
    """
    if metadata.get("source") != expected.document:
        return False
    return expected.section in metadata.get("headings", [])


def section_recall(ranked: list[dict[str, Any]], expected: tuple[ExpectedSection, ...]) -> float:
    """The share of ``expected`` sections that at least one of the ``ranked`` chunks matches.

    Raises ``ValueError`` if ``expected`` is empty, since there is nothing to find.
    """
    if not expected:
        raise ValueError("Recall needs at least one expected section.")
    found = 0
    for section in expected:
        for metadata in ranked:
            if chunk_matches(metadata, section):
                found += 1
                # One matching chunk is enough; more chunks from the same section add nothing.
                break
    return found / len(expected)


def reciprocal_rank(ranked: list[dict[str, Any]], expected: tuple[ExpectedSection, ...]) -> float:
    """One over the rank of the first chunk matching any ``expected`` section, or 0 if none does.

    Ranks count from 1, so a match in first place scores 1.0 and in second place 0.5.
    """
    for rank, metadata in enumerate(ranked, start=1):
        for section in expected:
            if chunk_matches(metadata, section):
                return 1.0 / rank
    return 0.0


def percentile(values: list[float], percent: float) -> float:
    """The ``percent``-th percentile of ``values`` by the nearest-rank method.

    The result is the smallest value that at least ``percent`` percent of the values are at or
    below, so it is always one of the measured values. Raises ``ValueError`` if ``values`` is empty
    or ``percent`` is not above 0 and at most 100.
    """
    if not values:
        raise ValueError("A percentile needs at least one value.")
    if percent <= 0 or percent > 100:
        raise ValueError(f"percent must be above 0 and at most 100, not {percent}.")
    ordered = sorted(values)
    # The rank, counting from 1, of the smallest value with percent% of the values at or below it.
    # Multiplying before dividing keeps whole-number cases exact: 95 * 20 / 100 is exactly 19.
    rank = math.ceil(percent * len(ordered) / 100)
    return ordered[rank - 1]
