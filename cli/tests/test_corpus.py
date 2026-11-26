"""The committed MVP corpus ingests through ``study ingest`` in full."""

from pathlib import Path

import pytest

from study_cli import main as cli_main
from study_cli.main import main

CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "release_engineering"


def test_the_whole_corpus_is_committed_and_ingests(
    components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """All 17 documents, in each of the three folders, are present and ingest without error.

    Runs on a fresh checkout in CI, so a document that git ignores, and therefore never committed,
    fails here.
    """
    exit_code = main(["ingest", str(CORPUS)])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "17 added, 0 replaced, 0 unchanged, 0 empty" in output
    for folder, count in (("build_systems/", 6), ("ci/", 7), ("releases/", 4)):
        assert output.count(f"added {folder}") == count
