"""Behavior of ``study ingest <folder>``."""

from importlib.metadata import entry_points
from pathlib import Path

import pytest

from rag_core_testing import HASHING_EMBEDDER
from study_cli import main as cli_main
from study_cli.main import main


def test_ingest_loads_the_folder_and_reports_counts(
    corpus: Path, components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """A first run adds every file and prints how many files and chunks it wrote."""
    exit_code = main(["ingest", str(corpus)])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "added build.md" in output
    assert "added ci.md" in output
    assert "2 added, 0 replaced, 0 unchanged, 0 empty; 2 chunks written" in output


def test_ingest_marks_the_model_current_on_the_first_run(
    corpus: Path, components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first run registers the configured model, makes it current, and says so once."""
    main(["ingest", str(corpus)])
    first = capsys.readouterr().out
    main(["ingest", str(corpus)])
    second = capsys.readouterr().out
    assert components.registry.get_current() == HASHING_EMBEDDER
    assert f"{HASHING_EMBEDDER.model_id} is now the current embedding model" in first
    assert "current embedding model" not in second


def test_ingest_twice_writes_nothing_the_second_time(
    corpus: Path, components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """Re-running over an unchanged folder reports every file unchanged and writes no chunks."""
    main(["ingest", str(corpus)])
    capsys.readouterr()
    exit_code = main(["ingest", str(corpus)])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "0 added, 0 replaced, 2 unchanged, 0 empty; 0 chunks written" in output


def test_ingest_a_missing_folder_fails_with_a_message(
    tmp_path: Path, components: cli_main.Components, capsys: pytest.CaptureFixture[str]
) -> None:
    """A path that is not a folder exits with status 2 and explains why on stderr."""
    exit_code = main(["ingest", str(tmp_path / "missing")])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "is not a folder" in captured.err


def test_a_command_is_required() -> None:
    """Running ``study`` with no command is a usage error."""
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2


def test_the_study_console_script_runs_main() -> None:
    """Installing the package provides a ``study`` command that calls ``main``."""
    scripts = entry_points(group="console_scripts", name="study")
    assert [script.value for script in scripts] == ["study_cli.main:main"]
