#!/usr/bin/env python3
"""Append a row to ``docs/checkpoints.md`` for major project iterations.

Run by ``.github/workflows/sync-checkpoints.yaml``. Two paths:

* **pull_request** closed + merged that closes a ``phase``-labeled issue → a row built from
  the PR (branch = head ref, checkpoint = PR title).
* **push** whose head commit message is ``#<number>-checkpoint: <text>`` → a manual checkpoint
  row built from that commit (checkpoint = ``<text>``).

Columns: ``Date | Branch | Issue | Checkpoint``. The Issue cell is the leading number of the
branch name, which must be the GitHub issue number (e.g. ``1-foundations`` → ``1``), or empty
when the branch starts with no number. Appends are idempotent: an identical row is not added twice.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

DEFAULT_DOC = Path(__file__).resolve().parents[2] / "docs" / "checkpoints.md"
DOC = Path(os.environ.get("CHECKPOINTS_FILE", str(DEFAULT_DOC)))
# Checkpoint commits look like `#1-checkpoint: drafted store schema` (the leading `#` is
# optional; `#<n>` auto-links the issue on GitHub).
CHECKPOINT_RE = re.compile(r"^#?\d+-checkpoint:\s*(?P<text>.*)$", re.IGNORECASE)


def gh(*args: str) -> str:
    """Run a ``gh`` command and return stdout."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def issue_from_branch(branch: str) -> str:
    """Leading issue number of the branch name, or '' (e.g. ``1-foundations`` → ``1``)."""
    match = re.match(r"(\d+)", branch)
    return match.group(1) if match else ""


def pr_closes_phase_issue(repo: str, pr_number: str) -> bool:
    """True if the PR closes at least one issue carrying the ``phase`` label."""
    refs = json.loads(
        gh("pr", "view", pr_number, "--repo", repo, "--json", "closingIssuesReferences")
    )["closingIssuesReferences"]
    for ref in refs:
        labels = json.loads(
            gh("issue", "view", str(ref["number"]), "--repo", repo, "--json", "labels")
        )["labels"]
        if any(label["name"] == "phase" for label in labels):
            return True
    return False


def esc(value: str) -> str:
    """Flatten and escape text so it stays inside one table cell."""
    return value.replace("|", "\\|").replace("\n", " ").strip()


def append_row(when: str, branch: str, issue: str, checkpoint: str) -> None:
    row = f"| {when} | `{branch}` | {issue} | {esc(checkpoint)} |"
    text = DOC.read_text()
    if row in text:
        print("Checkpoint row already present; skipping.")
        return
    if not text.endswith("\n"):
        text += "\n"
    DOC.write_text(text + row + "\n")
    print(f"Appended checkpoint: {row}")


def main() -> int:
    event = os.environ["GITHUB_EVENT_NAME"]
    repo = os.environ["GITHUB_REPOSITORY"]
    today = date.today().isoformat()

    if event == "pull_request":
        # The workflow only invokes this for merged PRs.
        pr_number = os.environ["PR_NUMBER"]
        branch = os.environ["PR_HEAD_REF"]
        title = os.environ["PR_TITLE"]
        if not pr_closes_phase_issue(repo, pr_number):
            print("Merged PR closes no phase issue; nothing to record.")
            return 0
        append_row(today, branch, issue_from_branch(branch), title)
        return 0

    if event == "push":
        branch = os.environ["BRANCH"]
        lines = os.environ.get("HEAD_COMMIT_MESSAGE", "").splitlines()
        first = lines[0] if lines else ""
        match = CHECKPOINT_RE.match(first.strip())
        if not match:
            print("Head commit is not a `#<n>-checkpoint:` commit; nothing to record.")
            return 0
        description = match.group("text").strip()
        append_row(today, branch, issue_from_branch(branch), description)
        return 0

    print(f"Unhandled event: {event}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
