"""Behavior of ``study embed``: filling the configured model's vectors for chunks already stored."""

from pathlib import Path

import pytest

from rag_core.ingest import ingest_folder
from rag_core.store.embedders import EmbedderInfo
from rag_core_testing import HASHING_EMBEDDER, HashingEmbedder
from study_cli import main as cli_main
from study_cli.main import main

# A model registered after the corpus was ingested with the hashing embedder.
SECOND_MODEL = EmbedderInfo(model_id="test/hashing-embedder-second", dimension=32)


@pytest.fixture
def second_model_components(
    monkeypatch: pytest.MonkeyPatch, components: cli_main.Components, corpus: Path
) -> cli_main.Components:
    """Components configured for a second model, over a store the first model already filled."""
    components.registry.register(HASHING_EMBEDDER.model_id, HASHING_EMBEDDER.dimension)
    components.registry.set_current(HASHING_EMBEDDER.model_id)
    ingest_folder(corpus, store=components.store, embedder=components.embedder)
    second = cli_main.Components(
        embedder=HashingEmbedder(SECOND_MODEL),
        store=components.store.with_embedder(SECOND_MODEL),
        registry=components.registry,
    )

    def build_second(settings: object) -> cli_main.Components:
        """Return the second model's components whatever the settings say."""
        return second

    monkeypatch.setattr(cli_main, "build_components", build_second)
    return second


def test_embed_fills_the_configured_models_vectors(
    second_model_components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every stored chunk is embedded with the configured model, and the count is printed."""
    exit_code = main(["embed"])

    assert exit_code == 0
    assert "2 chunks embedded with test/hashing-embedder-second" in capsys.readouterr().out
    assert second_model_components.store.get_unembedded_chunks(limit=10) == []


def test_embed_registers_the_model_without_making_it_current(
    second_model_components: cli_main.Components,
) -> None:
    """A model embedded beside the current one is registered, and the current model stays."""
    main(["embed"])

    registry = second_model_components.registry
    assert registry.get_current() == HASHING_EMBEDDER
    # set_current accepts only a registered model, so this succeeding shows the registration.
    registry.set_current(SECOND_MODEL.model_id)
    assert registry.get_current() == SECOND_MODEL


def test_embed_again_finds_nothing_to_do(
    second_model_components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second run embeds nothing and says so."""
    main(["embed"])
    capsys.readouterr()

    assert main(["embed"]) == 0
    assert "0 chunks embedded with test/hashing-embedder-second" in capsys.readouterr().out
