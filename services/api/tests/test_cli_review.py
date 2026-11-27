"""Behavior of ``study-ask``'s approval flow, with the agent run replaced by a canned outcome.

The flow has two halves: a question started with ``--review`` stops and prints what it would
answer from, and a later ``--resume`` carries the decision. These tests fix what the agent returns
and check what the command prints, which exit status it uses, and what it refuses before starting.
"""

from pathlib import Path

import pytest

from api import cli
from api.config import ApiSettings
from api.graph import AgentAnswer, AgentConfig, AgentOutcome, PendingReview, PendingSource
from api.mcp_client import SearchHit

THREAD = "0f9c2b1e"
CITED = SearchHit(
    id="chunk-asan",
    document="build_systems/bazel-basics.md",
    section="Bazel basics > Configs in .bazelrc",
    content="bazel test --config=asan //...",
    distance=0.25,
    relevance=0.75,
)
ANSWERED = AgentAnswer(
    status="answered",
    answer="Run bazel test --config=asan //...",
    cited_chunk_ids=["chunk-asan"],
    citations=[CITED],
    context=[CITED],
    queries=["Which flag?"],
    hops=1,
)
PENDING = PendingReview(
    thread_id=THREAD,
    question="Which flag?",
    query="Which flag?",
    hops=1,
    sources=[
        PendingSource(
            id="chunk-asan",
            document="build_systems/bazel-basics.md",
            section="Bazel basics > Configs in .bazelrc",
            relevance=0.91,
        ),
        PendingSource(
            id="chunk-cache",
            document="build_systems/bazel-basics.md",
            section="Bazel basics > Remote cache",
            relevance=0.42,
        ),
    ],
)
PENDING_AGAIN = PendingReview(
    thread_id=THREAD,
    question="Which flag?",
    query="bazel asan config flag",
    hops=2,
    sources=[
        PendingSource(
            id="chunk-asan-2",
            document="tooling/sanitizers.md",
            section="Sanitizers > Address",
            relevance=0.88,
        )
    ],
)


class Calls:
    """What the command asked the agent to do, in order, instead of running it."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.started: list[tuple[str, str, AgentConfig]] = []
        self.resumed: list[tuple[str, str, AgentConfig]] = []


def replace_review_flow(
    monkeypatch: pytest.MonkeyPatch, outcome: AgentOutcome | Exception
) -> Calls:
    """Make the approval flow return ``outcome`` (or raise it) instead of running the agent."""
    calls = Calls()

    async def fake_start(
        question: str, settings: ApiSettings, config: AgentConfig, *, thread_id: str
    ) -> AgentOutcome:
        """Record the started question and return the canned outcome."""
        calls.started.append((question, thread_id, config))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def fake_resume(
        decision: str, settings: ApiSettings, config: AgentConfig, *, thread_id: str
    ) -> AgentOutcome:
        """Record the decision and return the canned outcome."""
        calls.resumed.append((decision, thread_id, config))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(cli, "start_question", fake_start)
    monkeypatch.setattr(cli, "resume_question", fake_resume)
    return calls


@pytest.fixture
def saved_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A working folder with a database for saved runs and no other settings to read."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://study:change-me@localhost:5432/study_assistant"
    )


def test_review_prints_the_pending_sources_and_how_to_decide(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """A paused question lists what it would answer from and both commands that continue it."""
    calls = replace_review_flow(monkeypatch, PENDING)

    status = cli.main(["Which flag?", "--review"])

    output = capsys.readouterr().out
    assert status == 0
    assert "[1] build_systems/bazel-basics.md > Bazel basics > Configs in .bazelrc" in output
    assert "[2] build_systems/bazel-basics.md > Bazel basics > Remote cache" in output
    # The relevance each source was ranked by, which is what the grade was taken from.
    assert "relevance 0.910" in output
    assert "relevance 0.420" in output
    assert f"study-ask --resume {THREAD} --approve" in output
    assert f"study-ask --resume {THREAD} --reject" in output
    assert [question for question, _, _ in calls.started] == ["Which flag?"]


def test_review_asks_for_approval_and_a_plain_question_does_not(
    monkeypatch: pytest.MonkeyPatch, saved_runs: None
) -> None:
    """``--review`` is what turns the checkpoint on, so a plain question still answers in one go."""
    calls = replace_review_flow(monkeypatch, PENDING)

    cli.main(["Which flag?", "--review"])

    assert calls.started[0][2].require_approval is True
    assert cli.agent_config(ApiSettings()).require_approval is False


def test_review_uses_the_given_thread_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """A thread id can be chosen, so a script knows the name of the run it just started."""
    calls = replace_review_flow(monkeypatch, PENDING)

    cli.main(["Which flag?", "--review", "--thread-id", THREAD])

    assert calls.started[0][1] == THREAD
    assert THREAD in capsys.readouterr().out


def test_review_names_a_fresh_thread_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch, saved_runs: None
) -> None:
    """Two paused questions must not share a thread id, or one would resume the other."""
    calls = replace_review_flow(monkeypatch, PENDING)

    cli.main(["Which flag?", "--review"])
    cli.main(["Which other flag?", "--review"])

    first, second = calls.started[0][1], calls.started[1][1]
    assert first != second
    assert first and second


def test_a_question_that_needs_no_approval_is_answered_while_reviewing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """Nothing relevant was found, so there was nothing to approve and the run ended on its own."""
    replace_review_flow(monkeypatch, ANSWERED)

    status = cli.main(["Which flag?", "--review"])

    assert status == 0
    assert "Run bazel test --config=asan //..." in capsys.readouterr().out


def test_resume_with_approval_prints_the_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """The decision reaches the saved run and the answer comes back with its sources."""
    calls = replace_review_flow(monkeypatch, ANSWERED)

    status = cli.main(["--resume", THREAD, "--approve"])

    output = capsys.readouterr().out
    assert status == 0
    assert calls.resumed == [("approve", THREAD, calls.resumed[0][2])]
    assert calls.resumed[0][2].require_approval is True
    assert "Run bazel test --config=asan //..." in output
    assert "[1] build_systems/bazel-basics.md > Bazel basics > Configs in .bazelrc" in output


def test_resume_with_a_rejection_can_pause_again_on_the_rewritten_search(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """A rejection spends a hop and offers the next search's sources under the same thread id."""
    calls = replace_review_flow(monkeypatch, PENDING_AGAIN)

    status = cli.main(["--resume", THREAD, "--reject"])

    output = capsys.readouterr().out
    assert status == 0
    assert calls.resumed[0][0] == "reject"
    assert "[1] tooling/sanitizers.md > Sanitizers > Address" in output
    assert "bazel asan config flag" in output
    assert f"study-ask --resume {THREAD} --approve" in output


def test_resume_without_a_decision_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """A resume with no decision has nothing to tell the paused run, so nothing is started."""
    calls = replace_review_flow(monkeypatch, ANSWERED)

    status = cli.main(["--resume", THREAD])

    assert status == cli.USAGE_ERROR
    assert "--approve" in capsys.readouterr().err
    assert calls.resumed == []


def test_a_question_and_a_resume_together_are_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """Either a new question or a decision on a saved one, never both in one command."""
    calls = replace_review_flow(monkeypatch, ANSWERED)

    status = cli.main(["Which flag?", "--resume", THREAD, "--approve"])

    assert status == cli.USAGE_ERROR
    assert capsys.readouterr().err != ""
    assert calls.started == []
    assert calls.resumed == []


def test_no_question_and_no_resume_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """The command needs something to do."""
    status = cli.main([])

    assert status == cli.USAGE_ERROR
    assert capsys.readouterr().err != ""


def test_a_decision_without_a_resume_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """A decision belongs to a saved run, so it needs the thread id of one."""
    calls = replace_review_flow(monkeypatch, ANSWERED)

    status = cli.main(["Which flag?", "--approve"])

    assert status == cli.USAGE_ERROR
    assert calls.started == []


@pytest.mark.parametrize(
    "argv",
    [["Which flag?", "--review"], ["--resume", THREAD, "--approve"]],
    ids=["review", "resume"],
)
def test_the_approval_flow_without_a_database_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    argv: list[str],
) -> None:
    """A pause with nowhere to be saved is refused before the server or the model is reached."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    calls = replace_review_flow(monkeypatch, PENDING)

    status = cli.main(argv)

    assert status == cli.USAGE_ERROR
    assert "DATABASE_URL" in capsys.readouterr().err
    assert calls.started == []
    assert calls.resumed == []


def test_resuming_a_thread_that_is_not_paused_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], saved_runs: None
) -> None:
    """A stale or mistyped thread id is reported, not answered as a new question."""
    replace_review_flow(monkeypatch, ValueError(f"No run under thread id {THREAD!r} is waiting."))

    status = cli.main(["--resume", THREAD, "--approve"])

    assert status == cli.USAGE_ERROR
    assert THREAD in capsys.readouterr().err
