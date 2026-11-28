"""The reply to one chat question: the answer as Markdown, or the error that stopped the run."""

import pytest
from chat_fakes import answered, hit, unanswered

from api.cli import NO_ANSWER
from api.generate import GenerationError
from api.graph import AgentAnswer
from api.mcp_client import SearchError
from study_chat import reply
from study_chat.reply import Reply, format_answer, respond


def test_an_answer_lists_its_sources_in_citation_order() -> None:
    """The answer comes first, then each cited source as a numbered Markdown list item."""
    answer = answered(
        "A hash map stores key-value pairs [1][2].",
        [hit("Week 3", "Hash maps"), hit("Week 3", "Collisions")],
        ["what is a hash map"],
    )

    text = format_answer(answer)

    assert text.startswith("A hash map stores key-value pairs [1][2].")
    assert "1. Week 3 > Hash maps\n2. Week 3 > Collisions" in text
    assert text.index("Sources") < text.index("1. Week 3 > Hash maps")


def test_an_answer_ends_with_the_searches_made() -> None:
    """The last line names how many searches ran and what each searched for."""
    answer = answered("Answer [1].", [hit("Notes", "Intro")], ["first query", "second query"])

    assert format_answer(answer).endswith("2 searches: first query; second query")


def test_a_single_search_is_singular() -> None:
    """One search reads ``1 search``, not ``1 searches``."""
    answer = answered("Answer [1].", [hit("Notes", "Intro")], ["only query"])

    assert format_answer(answer).endswith("1 search: only query")


def test_an_unanswered_question_says_so_without_sources() -> None:
    """A run without enough context shows the no-answer line and the searches, and no sources."""
    text = format_answer(unanswered(["q1", "q2"]))

    assert text.startswith(NO_ANSWER)
    assert "Sources" not in text
    assert text.endswith("2 searches: q1; q2")


def test_respond_asks_the_agent_and_formats_its_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """``respond`` runs the agent on the question and replies with the formatted answer."""
    answer = answered("Binary search halves the range [1].", [hit("Week 2", "Search")], ["bs"])
    asked: list[str] = []

    async def fake_answer_question(question: str, *args: object, **kwargs: object) -> AgentAnswer:
        """Record the question and return the scripted answer."""
        asked.append(question)
        return answer

    monkeypatch.setattr(reply, "answer_question", fake_answer_question)

    result = respond("explain binary search")

    assert asked == ["explain binary search"]
    assert result == Reply(text=format_answer(answer), failed=False)


@pytest.mark.parametrize(
    "error",
    [
        GenerationError("the model endpoint refused the request"),
        SearchError("Could not start or connect to the MCP server"),
        ValueError("AGENT_MAX_HOPS must be at least 1"),
    ],
)
def test_respond_turns_a_failed_run_into_a_failed_reply(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """A model, search, or settings error becomes a failed reply carrying its message."""

    async def failing_answer_question(*args: object, **kwargs: object) -> AgentAnswer:
        """Raise the parametrized error, as a failed run would."""
        raise error

    monkeypatch.setattr(reply, "answer_question", failing_answer_question)

    assert respond("anything") == Reply(text=str(error), failed=True)
