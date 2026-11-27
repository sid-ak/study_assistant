"""Behavior of the ``study-ask`` command, with the agent run replaced by a canned answer."""

from pathlib import Path

import pytest

from api import cli
from api.config import ApiSettings
from api.generate import GenerationError
from api.graph import AgentAnswer, AgentConfig
from api.mcp_client import SearchHit

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
INSUFFICIENT = AgentAnswer(
    status="insufficient_context",
    answer="",
    cited_chunk_ids=[],
    citations=[],
    context=[],
    queries=["capital of France?", "France capital city"],
    hops=2,
)


def replace_agent(monkeypatch: pytest.MonkeyPatch, result: AgentAnswer | Exception) -> list[str]:
    """Make ``study-ask`` return ``result`` (or raise it) instead of running the agent."""
    asked: list[str] = []

    async def fake_answer(question: str, settings: ApiSettings, config: AgentConfig) -> AgentAnswer:
        """Record the question and return the canned result."""
        asked.append(question)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cli, "answer_question", fake_answer)
    return asked


def test_ask_prints_the_answer_and_its_sources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An answer is printed with each cited chunk's document and heading path."""
    asked = replace_agent(monkeypatch, ANSWERED)

    status = cli.main(["Which flag?"])

    output = capsys.readouterr().out
    assert status == 0
    assert asked == ["Which flag?"]
    assert "Run bazel test --config=asan //..." in output
    assert "[1] build_systems/bazel-basics.md > Bazel basics > Configs in .bazelrc" in output
    assert "1 search" in output


def test_ask_says_plainly_when_the_context_was_insufficient(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unanswerable question ends with a clear message, the queries tried, and status 0."""
    replace_agent(monkeypatch, INSUFFICIENT)

    status = cli.main(["capital of France?"])

    output = capsys.readouterr().out
    assert status == 0
    assert "No answer: the documents found did not answer the question." in output
    assert "France capital city" in output
    assert "2 searches" in output


def test_ask_reports_a_generation_failure_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A model failure exits with status 1 and a one-line message, not a traceback."""
    replace_agent(monkeypatch, GenerationError("rate limit resets in 3600 s"))

    status = cli.main(["Which flag?"])

    assert status == 1
    assert "rate limit resets in 3600 s" in capsys.readouterr().err


def test_agent_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``AGENT_*`` settings shape the run, and the defaults are two hops and a 0.65 threshold."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_RELEVANCE_THRESHOLD", "0.7")
    for name in ["AGENT_MAX_HOPS", "AGENT_SEARCH_LIMIT"]:
        monkeypatch.delenv(name, raising=False)

    config = cli.agent_config(ApiSettings())

    assert config == AgentConfig(max_hops=2, relevance_threshold=0.7, search_limit=5)


def test_an_invalid_agent_setting_is_a_usage_error_before_anything_starts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A setting the agent cannot honor exits 2 with one line, before the server starts."""
    asked = replace_agent(monkeypatch, ANSWERED)
    monkeypatch.setenv("AGENT_SEARCH_LIMIT", "25")

    status = cli.main(["Which flag?"])

    assert status == cli.USAGE_ERROR
    assert "search_limit" in capsys.readouterr().err
    assert asked == []
