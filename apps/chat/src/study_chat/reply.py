"""The reply to one chat question: the answer as Markdown, or the error that stopped the run."""

import asyncio
from dataclasses import dataclass

from api.cli import NO_ANSWER, agent_config, answer_question, searches_line
from api.config import ApiSettings
from api.generate import GenerationError
from api.graph import AgentAnswer
from api.mcp_client import SearchError

__all__ = ["Reply", "answer_question", "format_answer", "respond"]


@dataclass(frozen=True)
class Reply:
    """What the page shows for one question.

    ``text`` is Markdown for an answer, or the error message when ``failed`` is true.
    """

    text: str
    failed: bool


def format_answer(answer: AgentAnswer) -> str:
    """The answer, or the no-answer line, then its numbered sources, then the searches made."""
    paragraphs: list[str] = []
    if answer.status == "answered":
        paragraphs.append(answer.answer)
        sources: list[str] = []
        for number, citation in enumerate(answer.citations, start=1):
            sources.append(f"{number}. {citation.document} > {citation.section}")
        # Markdown needs a blank line before a list, or the first item joins the line above it.
        paragraphs.append("Sources:\n\n" + "\n".join(sources))
    else:
        paragraphs.append(NO_ANSWER)
    paragraphs.append(searches_line(answer))
    return "\n\n".join(paragraphs)


def respond(question: str) -> Reply:
    """Run the agent once on ``question`` and return its formatted answer, or the error.

    Each call starts the search server and stops it again, as one ``study-ask`` does. Opening it
    takes about a second, which is small next to generation, so no connection is kept between
    questions.
    """
    try:
        settings = ApiSettings()
        config = agent_config(settings)
        answer = asyncio.run(answer_question(question, settings, config))
    except (GenerationError, SearchError, ValueError) as error:
        # The same failures study-ask reports in one line; a settings error is a ValueError.
        return Reply(text=str(error), failed=True)
    return Reply(text=format_answer(answer), failed=False)
