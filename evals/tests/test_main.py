"""Tests for the ``study-eval`` command, run against the in-memory store and hashing embedder."""

import json
from pathlib import Path

import pytest

from evals import main as eval_main
from rag_core.store.embedders import EmbedderInfo
from rag_core_testing import HashingEmbedder, InMemoryStore


@pytest.fixture
def components(
    monkeypatch: pytest.MonkeyPatch, embedder: HashingEmbedder, store: InMemoryStore
) -> eval_main.Components:
    """Fake components that ``main`` uses in place of the real model and database."""
    fakes = eval_main.Components(embedder=embedder, store=store)

    def build_fakes(settings: object) -> eval_main.Components:
        """Return the fakes whatever the settings say."""
        return fakes

    monkeypatch.setattr(eval_main, "build_components", build_fakes)
    return fakes


def run_command(name: str, golden: Path, corpus: Path, results: Path, *extra: str) -> int:
    """Run ``study-eval`` with explicit paths, one repeat, and ``extra`` arguments."""
    arguments = [name, "--golden", str(golden), "--corpus", str(corpus), "--results", str(results)]
    arguments.extend(["--repeats", "1"])
    arguments.extend(extra)
    return eval_main.main(arguments)


def test_eval_scores_the_golden_set_and_saves_the_run(
    components: eval_main.Components,
    golden_file: Path,
    corpus: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command prints each question and the totals, then saves the run under its name."""
    results = tmp_path / "results"

    status = run_command("smoke", golden_file, corpus, results, "--k", "1")

    assert status == 0
    output = capsys.readouterr().out
    assert "caching" in output
    assert "pthread" in output
    assert "Recall@1 1.00" in output
    assert "MRR 1.00" in output
    saved = json.loads((results / "smoke.json").read_text())
    assert saved["recall_at_k"] == 1.0
    assert saved["k"] == 1


def test_eval_stops_before_retrieval_when_a_label_cannot_match(
    components: eval_main.Components,
    corpus: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A label naming a missing heading exits with status 2, names it, and saves nothing."""
    golden = tmp_path / "bad.toml"
    golden.write_text(
        '[[questions]]\nid = "typo"\ntext = "ccache"\n'
        'expected = [{ document = "build.md", section = "Cachin" }]\n'
    )
    results = tmp_path / "results"

    status = run_command("smoke", golden, corpus, results)

    assert status == eval_main.USAGE_ERROR
    assert "Cachin" in capsys.readouterr().err
    assert not (results / "smoke.json").exists()


def test_eval_refuses_a_run_name_already_saved(
    components: eval_main.Components,
    golden_file: Path,
    corpus: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reusing a saved run's name exits with status 2 and leaves the saved file alone."""
    results = tmp_path / "results"
    assert run_command("smoke", golden_file, corpus, results) == 0
    before = (results / "smoke.json").read_text()

    status = run_command("smoke", golden_file, corpus, results)

    assert status == eval_main.USAGE_ERROR
    assert "smoke" in capsys.readouterr().err
    assert (results / "smoke.json").read_text() == before


def test_eval_refuses_a_model_with_chunks_it_has_not_embedded(
    monkeypatch: pytest.MonkeyPatch,
    store: InMemoryStore,
    golden_file: Path,
    corpus: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A model missing vectors would score zero, so the run stops and points to ``study embed``."""
    second_model = EmbedderInfo(model_id="test/hashing-embedder-second", dimension=32)
    unembedded = eval_main.Components(
        embedder=HashingEmbedder(second_model), store=store.with_embedder(second_model)
    )

    def build_unembedded(settings: object) -> eval_main.Components:
        """Return components for a model the store holds no vectors from."""
        return unembedded

    monkeypatch.setattr(eval_main, "build_components", build_unembedded)
    results = tmp_path / "results"

    status = run_command("smoke", golden_file, corpus, results)

    assert status == eval_main.USAGE_ERROR
    error = capsys.readouterr().err
    assert "test/hashing-embedder-second" in error
    assert "study embed" in error
    assert not (results / "smoke.json").exists()
