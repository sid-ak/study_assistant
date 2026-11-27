"""Behavior of ``study query "<text>"``."""

import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from rag_core.store import EmbedderNotFoundError
from rag_core_testing import HASHING_EMBEDDER, InMemoryStore, OverlapReranker
from study_cli import main as cli_main
from study_cli.main import main

# One result line: rank, distance, chunk id, then where the chunk comes from.
RESULT_LINE = re.compile(r"^(\d+)\. (\d\.\d{4})  ([0-9a-f-]{36})  (.+)$", re.MULTILINE)


class UnregisteredStore(InMemoryStore):
    """A store whose model has no stored vectors, as the database reports before any ingest."""

    def search_dense(
        self, query_embedding: Sequence[float], limit: int, ef_search: int | None = None
    ) -> list[dict[str, Any]]:
        """Fail the way the database store does for a model that was never registered."""
        raise EmbedderNotFoundError(f"Embedder {self.embedder.model_id!r} is not registered.")


@pytest.fixture
def ingested(
    corpus: Path, components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ``corpus`` folder ingested into the fake components, with the ingest output discarded."""
    main(["ingest", str(corpus)])
    capsys.readouterr()


@pytest.mark.usefixtures("ingested")
def test_query_prints_ranked_chunks_with_ids_and_distances(
    components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each result shows its rank, cosine distance, chunk id, and source, nearest first."""
    exit_code = main(["query", "undefined reference to pthread_create"])
    output = capsys.readouterr().out
    assert exit_code == 0
    results = RESULT_LINE.findall(output)
    assert [rank for rank, _, _, _ in results] == ["1", "2"]
    distances = [float(distance) for _, distance, _, _ in results]
    assert distances == sorted(distances)
    assert results[0][3] == "ci.md > Failure"
    assert "undefined reference to pthread_create" in output


@pytest.mark.usefixtures("ingested")
def test_query_reports_latency_in_milliseconds(capsys: pytest.CaptureFixture[str]) -> None:
    """A summary line gives the result count, the latency in ms, the model, and ef_search."""
    main(["query", "cmake preset"])
    output = capsys.readouterr().out
    pattern = (
        rf"2 results in \d+\.\d ms \({re.escape(HASHING_EMBEDDER.model_id)}, ef_search default\)"
    )
    assert re.search(pattern, output)


@pytest.mark.usefixtures("ingested")
def test_limit_and_ef_search_options(capsys: pytest.CaptureFixture[str]) -> None:
    """``--limit`` caps the results and ``--ef-search`` is reported in the summary."""
    exit_code = main(["query", "build", "--limit", "1", "--ef-search", "64"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert len(RESULT_LINE.findall(output)) == 1
    assert "ef_search 64)" in output


@pytest.mark.usefixtures("ingested")
def test_an_ef_search_below_the_limit_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    """An invalid search setting exits with status 2 and the reason on stderr."""
    exit_code = main(["query", "build", "--limit", "5", "--ef-search", "2"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "ef_search" in captured.err


def test_an_empty_index_says_to_ingest_first(
    components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """With nothing ingested, the query prints no results and points at ``study ingest``."""
    exit_code = main(["query", "build"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "0 results" in output
    assert "study ingest" in output


def test_an_unregistered_model_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    components: cli_main.Components,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Querying a model that was never ingested exits with status 2 and says to ingest first."""
    unregistered = cli_main.Components(
        embedder=components.embedder,
        store=UnregisteredStore(embedder=HASHING_EMBEDDER),
        registry=components.registry,
    )

    def build_unregistered(settings: object) -> cli_main.Components:
        """Return components whose store has no column for the model."""
        return unregistered

    monkeypatch.setattr(cli_main, "build_components", build_unregistered)
    exit_code = main(["query", "build"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "study ingest" in captured.err


@pytest.mark.usefixtures("ingested")
def test_query_reranks_when_the_components_have_a_reranker(
    components: cli_main.Components,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With a reranker configured, the summary names it and the candidate count it rescored."""
    reranked = replace(components, reranker=OverlapReranker(), rerank_candidates=20)

    def build_reranked(settings: object) -> cli_main.Components:
        """Return the components with a reranker, whatever the settings say."""
        return reranked

    monkeypatch.setattr(cli_main, "build_components", build_reranked)

    assert main(["query", "undefined reference to pthread_create"]) == 0
    output = capsys.readouterr().out
    assert "reranked by test/overlap-reranker from 20 candidates" in output
    assert RESULT_LINE.findall(output)[0][3] == "ci.md > Failure"
