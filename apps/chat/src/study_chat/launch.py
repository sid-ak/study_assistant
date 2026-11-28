"""The ``study-chat`` console script: start Streamlit on the chat page."""

import sys
from pathlib import Path

from streamlit.web import cli as streamlit_cli

# The page Streamlit runs, shipped inside this package.
APP = Path(__file__).parent / "app.py"

# Streamlit's defaults suit a hosted app. The study assistant is local and single-user, so the page
# listens on this machine only, sends Streamlit no usage statistics, and hides the Deploy button.
LOCAL_OPTIONS = [
    "--server.address",
    "localhost",
    "--browser.gatherUsageStats",
    "false",
    "--client.toolbarMode",
    "minimal",
]


def main() -> None:
    """Run ``streamlit run`` on the chat page until Streamlit stops."""
    # Streamlit's command line reads its arguments from sys.argv, as the streamlit command does.
    sys.argv = ["streamlit", "run", str(APP)] + LOCAL_OPTIONS
    streamlit_cli.main()
