"""Tests for the agent evaluation: citation grounding, citation recall, and the command.

The agent run is a plain async function from question to answer, so these tests pass prepared
answers in its place and need no model, MCP server, or database.
"""

import asyncio
import json
from pathlib import Path

import pytest

from api.config import ApiSettings
from api.graph import AgentAnswer, AgentConfig
from api.mcp_client import SearchHit
from evals import agent_main
from evals.agent import AgentEvalRun, is_grounded, run_agent_eval
from evals.golden import ExpectedSection, GoldenQuestion
from evals.runner import write_run

CACHING = SearchHit(
    "chunk-caching", "build.md", "Build > Caching", "ccache stores objects.", 0.2, 0.8
)
PRESETS = SearchHit("chunk-presets", "build.md", "Build > Presets", "Run cmake --preset.", 0.4, 0.6)


def question(question_id: str) -> GoldenQuestion:
    """A golden question labeled with the Caching section."""
    return GoldenQuestion(
        id=question_id,
        text=f"Question {question_id}?",
        expected=(ExpectedSection("build.md", "Caching"),),
    )


def answered(cited: list[str], context: list[SearchHit]) -> AgentAnswer:
    """An answered result citing ``cited`` from ``context``."""
    citations = []
    for hit in context:
        if hit.id in cited:
            citations.append(hit)
    return AgentAnswer(
        status="answered",
        answer="An answer.",
        cited_chunk_ids=cited,
        citations=citations,
        context=context,
        queries=["q"],
        hops=1,
    )


def score(questions: list[GoldenQuestion], agent: "PreparedAgent") -> AgentEvalRun:
    """Run the agent evaluation over ``questions`` with ``agent`` answering."""
    return asyncio.run(run_agent_eval(questions, answer=agent, generation_model="test/model"))


INSUFFICIENT = AgentAnswer(
    status="insufficient_context",
    answer="",
    cited_chunk_ids=[],
    citations=[],
    context=[PRESETS],
    queries=["q", "q2"],
    hops=2,
)


class PreparedAgent:
    """Answers each question text with a prepared ``AgentAnswer``, recording what it was asked."""

    def __init__(self, answers: dict[str, AgentAnswer]) -> None:
        """Answer a question whose text is a key of ``answers`` with that answer."""
        self.answers = answers
        self.asked: list[str] = []

    async def __call__(self, text: str) -> AgentAnswer:
        """Return the prepared answer for the question with this text."""
        self.asked.append(text)
        return self.answers[text]


def test_an_answer_is_grounded_when_every_cited_id_was_in_its_context() -> None:
    """Citations must name chunks the model was shown, and an answer must cite something."""
    assert is_grounded(answered(["chunk-caching"], [CACHING, PRESETS])) is True
    assert is_grounded(answered(["chunk-caching", "made-up"], [CACHING])) is False
    assert is_grounded(answered([], [CACHING])) is False
    assert is_grounded(INSUFFICIENT) is None


def test_run_agent_eval_scores_grounding_and_citation_recall() -> None:
    """Answered questions are checked for grounding; every question for citing a labeled section."""
    agent = PreparedAgent(
        {
            "Question good?": answered(["chunk-caching"], [CACHING, PRESETS]),
            "Question wrong-section?": answered(["chunk-presets"], [CACHING, PRESETS]),
            "Question ungrounded?": answered(["made-up"], [CACHING]),
            "Question none?": INSUFFICIENT,
        }
    )
    questions = [
        question("good"),
        question("wrong-section"),
        question("ungrounded"),
        question("none"),
    ]

    run = score(questions, agent)

    by_id = {}
    for result in run.questions:
        by_id[result.id] = result
    assert by_id["good"].grounded is True
    assert by_id["good"].citation_recall == 1.0
    assert by_id["wrong-section"].grounded is True
    assert by_id["wrong-section"].citation_recall == 0.0
    assert by_id["ungrounded"].grounded is False
    assert by_id["none"].grounded is None
    assert by_id["none"].citation_recall == 0.0
    assert run.answered == 3
    assert run.insufficient_context == 1
    assert run.grounding_pass_rate == pytest.approx(2 / 3)
    assert run.citation_recall == pytest.approx(1 / 4)
    assert run.generation_model == "test/model"
    assert agent.asked == [q.text for q in questions]


def test_run_agent_eval_records_each_answer_and_its_latency() -> None:
    """Each question keeps its status, answer, cited sections, searches, and time taken."""
    agent = PreparedAgent({"Question good?": answered(["chunk-caching"], [CACHING])})

    run = score([question("good")], agent)

    [result] = run.questions
    assert result.status == "answered"
    assert result.answer == "An answer."
    assert result.cited_sections == ["build.md > Build > Caching"]
    assert result.queries == ["q"]
    assert result.hops == 1
    assert result.latency_ms >= 0.0
    assert run.latency_p50_ms == result.latency_ms


def test_with_nothing_answered_the_pass_rate_is_undefined() -> None:
    """No answered question means no grounding rate, rather than a misleading 0 or 1."""
    agent = PreparedAgent({"Question none?": INSUFFICIENT})

    run = score([question("none")], agent)

    assert run.answered == 0
    assert run.grounding_pass_rate is None


def test_an_agent_run_is_saved_like_a_retrieval_run(tmp_path: Path) -> None:
    """``write_run`` saves agent runs too, with the grounding figures in the file."""
    agent = PreparedAgent({"Question good?": answered(["chunk-caching"], [CACHING])})
    run = score([question("good")], agent)

    path = write_run(run, tmp_path, name="agent-smoke")

    saved = json.loads(path.read_text())
    assert saved["grounding_pass_rate"] == 1.0
    assert saved["questions"][0]["cited_sections"] == ["build.md > Build > Caching"]


def test_the_command_scores_the_golden_set_and_saves_the_run(
    monkeypatch: pytest.MonkeyPatch,
    golden_file: Path,
    corpus: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``study-eval-agent`` prints each question and the grounding totals, then saves the run."""
    asked: list[str] = []

    async def fake_live_run(
        questions: list[GoldenQuestion], settings: ApiSettings, config: AgentConfig
    ) -> AgentEvalRun:
        """Score ``questions`` against prepared answers instead of the live agent."""
        for item in questions:
            asked.append(item.id)
        agent = PreparedAgent(
            {
                "ccache compiled objects": answered(["chunk-caching"], [CACHING]),
                "libpthread linked oldest image": INSUFFICIENT,
            }
        )
        return await run_agent_eval(questions, answer=agent, generation_model="test/model")

    def store_is_ready() -> None:
        """Skip the database check: the prepared answers need no stored chunks."""

    monkeypatch.setattr(agent_main, "run_live", fake_live_run)
    monkeypatch.setattr(agent_main, "check_store_ready", store_is_ready)
    results = tmp_path / "results"

    status = agent_main.main(
        ["smoke", "--golden", str(golden_file), "--corpus", str(corpus), "--results", str(results)]
    )

    assert status == 0
    output = capsys.readouterr().out
    assert "Grounding pass rate 1.00" in output
    assert asked == ["caching", "pthread"]
    assert json.loads((results / "smoke.json").read_text())["answered"] == 1


def test_the_command_checks_labels_before_asking_anything(
    monkeypatch: pytest.MonkeyPatch,
    corpus: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A label that names no heading exits with status 2 before any model request."""
    golden = tmp_path / "bad.toml"
    golden.write_text(
        '[[questions]]\nid = "typo"\ntext = "ccache"\n'
        'expected = [{ document = "build.md", section = "Cachin" }]\n'
    )

    status = agent_main.main(
        ["smoke", "--golden", str(golden), "--corpus", str(corpus), "--results", str(tmp_path)]
    )

    assert status == 2
    assert "Cachin" in capsys.readouterr().err


def test_the_command_refuses_an_invalid_agent_setting_before_asking(
    monkeypatch: pytest.MonkeyPatch,
    golden_file: Path,
    corpus: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A setting the agent cannot honor exits with status 2 before any model request."""

    def store_is_ready() -> None:
        """Skip the database check."""

    monkeypatch.setattr(agent_main, "check_store_ready", store_is_ready)
    monkeypatch.setenv("AGENT_SEARCH_LIMIT", "25")

    status = agent_main.main(
        ["smoke", "--golden", str(golden_file), "--corpus", str(corpus), "--results", str(tmp_path)]
    )

    assert status == 2
    assert "search_limit" in capsys.readouterr().err


def test_an_agent_run_records_how_retrieval_ranked() -> None:
    """The run names the reranker and its candidates, or None for both when search was dense."""
    agent = PreparedAgent({"Question good?": answered(["chunk-caching"], [CACHING])})

    reranked = asyncio.run(
        run_agent_eval(
            [question("good")],
            answer=agent,
            generation_model="test/model",
            reranker="jinaai/jina-reranker-v1-tiny-en",
            candidates=20,
            hybrid=True,
        )
    )
    dense = score([question("good")], agent)

    assert reranked.reranker == "jinaai/jina-reranker-v1-tiny-en"
    assert reranked.candidates == 20
    assert reranked.hybrid is True
    assert dense.hybrid is False
    assert dense.reranker is None
    assert dense.candidates is None
