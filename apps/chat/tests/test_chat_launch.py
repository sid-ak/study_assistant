"""The ``study-chat`` command: start Streamlit on the chat page."""

import sys
from pathlib import Path

import pytest
from streamlit.web import cli as streamlit_cli

import study_chat
from study_chat import launch


def test_study_chat_runs_streamlit_on_the_app_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main`` runs the page on localhost only, with no usage statistics and no Deploy button."""
    seen: list[list[str]] = []

    def fake_streamlit_main() -> None:
        """Record the command line Streamlit would parse."""
        seen.append(list(sys.argv))

    monkeypatch.setattr(streamlit_cli, "main", fake_streamlit_main)
    monkeypatch.setattr(sys, "argv", ["study-chat"])

    launch.main()

    app = Path(study_chat.__file__).parent / "app.py"
    assert seen == [
        [
            "streamlit",
            "run",
            str(app),
            "--server.address",
            "localhost",
            "--browser.gatherUsageStats",
            "false",
            "--client.toolbarMode",
            "minimal",
        ]
    ]
    assert app.is_file()
