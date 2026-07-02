#!/usr/bin/env python3
"""Append a row to ``docs/checkpoints.md`` when a pull request is merged into the default branch.

Run by ``.github/workflows/sync-checkpoints.yaml`` on ``pull_request`` closed+merged. A row is
added when the merged PR either:

* closes a ``phase``-labeled issue → checkpoint = the PR title, or
* carries a commit whose subject is ``checkpoint: <text>`` → checkpoint = ``<text>`` (one row per
  such commit). An optional ``#<number>-`` / ``<number>-`` prefix (e.g. ``#2-checkpoint:``) sets the
  Issue column; without it the Issue comes from the PR branch's leading number.

Recording only on merge means a checkpoint lands in the log exactly when its commit reaches the
default branch — never while it is still on a feature branch. Columns:
``Date | Branch | Issue | Checkpoint``; Branch is the PR head ref. Appends are idempotent: an
identical row is not added twice.
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
# Checkpoint commit subjects look like `checkpoint: drafted store schema`, optionally with an
# issue-number prefix like `#1-checkpoint: ...` or `1-checkpoint: ...` (the `#` and the `<n>-` are
# both optional; `#<n>` auto-links the issue on GitHub). The number, when present, sets the Issue
# column; otherwise it falls back to the PR branch.
CHECKPOINT_RE = re.compile(r"^(?:#?(?P<issue>\d+)-)?checkpoint:\s*(?P<text>.*)$", re.IGNORECASE)


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


def pr_checkpoint_commits(repo: str, pr_number: str) -> list[tuple[str, str]]:
    """(issue, text) for each commit on the PR whose subject is a ``checkpoint:`` commit.

    Reads the PR's own commits, so it is unaffected by the merge strategy (merge/squash/rebase).
    """
    raw = gh("pr", "view", pr_number, "--repo", repo, "--json", "commits")
    commits = json.loads(raw)["commits"]
    out: list[tuple[str, str]] = []
    for commit in commits:
        match = CHECKPOINT_RE.match(commit.get("messageHeadline", "").strip())
        if match:
            out.append((match.group("issue") or "", match.group("text").strip()))
    return out


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
    repo = os.environ["GITHUB_REPOSITORY"]
    pr_number = os.environ["PR_NUMBER"]
    branch = os.environ["PR_HEAD_REF"]
    title = os.environ["PR_TITLE"]
    today = date.today().isoformat()

    recorded = False

    # A merged PR that closes a phase-labeled issue → one row built from the PR itself.
    if pr_closes_phase_issue(repo, pr_number):
        append_row(today, branch, issue_from_branch(branch), title)
        recorded = True

    # Any `checkpoint:` commit that rode in on the PR → one row each. Issue comes from the commit's
    # own `#<n>-` prefix when present, else the PR branch's leading number.
    for issue, text in pr_checkpoint_commits(repo, pr_number):
        append_row(today, branch, issue or issue_from_branch(branch), text)
        recorded = True

    if not recorded:
        print("PR closes no phase issue and has no checkpoint commit; nothing to record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
