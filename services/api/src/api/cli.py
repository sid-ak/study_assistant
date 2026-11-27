"""The ``study-ask`` console script: answer one question with the agent and print its sources."""

import argparse
import asyncio
import sys
from pathlib import Path

from api.config import ApiSettings
from api.generate import GenerationError, OpenAICompatibleGenerator
from api.graph import AgentAnswer, AgentConfig, ask, build_graph
from api.mcp_client import McpSearchClient, SearchError, stdio_server

# Exit status when the model or the search tool failed.
FAILURE = 1


def agent_config(settings: ApiSettings) -> AgentConfig:
    """The agent's bounds from the ``AGENT_*`` settings."""
    return AgentConfig(
        max_hops=settings.agent_max_hops,
        relevance_threshold=settings.agent_relevance_threshold,
        search_limit=settings.agent_search_limit,
    )


async def answer_question(question: str, settings: ApiSettings) -> AgentAnswer:
    """Start the MCP server, run the agent on ``question``, and stop the server.

    The server is started in the current folder, so it reads the same ``.env`` as this command.
    """
    generator = OpenAICompatibleGenerator.from_settings(settings)
    server = stdio_server(settings.mcp_server_command, Path.cwd())
    async with McpSearchClient(server) as search:
        graph = build_graph(search, generator, config=agent_config(settings))
        return await ask(graph, question)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for ``study-ask``."""
    parser = argparse.ArgumentParser(
        prog="study-ask",
        description="Answer a question from the ingested documents, citing the chunks used.",
    )
    parser.add_argument("question", help="The question to answer.")
    return parser


def print_answer(result: AgentAnswer) -> None:
    """Print the answer or the insufficient-context message, its sources, and the searches."""
    if result.status == "answered":
        print(result.answer)
        print()
        print("Sources:")
        for number, citation in enumerate(result.citations, start=1):
            print(f"[{number}] {citation.document} > {citation.section}")
    else:
        print("No answer: the documents found did not answer the question.")
    searches = "search" if result.hops == 1 else "searches"
    print()
    print(f"{result.hops} {searches}: " + "; ".join(result.queries))


def main(argv: list[str] | None = None) -> int:
    """Run ``study-ask`` and return its exit status: 0, or 1 if the model or search failed."""
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(answer_question(args.question, ApiSettings()))
    except (GenerationError, SearchError) as error:
        print(f"study-ask: {error}", file=sys.stderr)
        return FAILURE
    print_answer(result)
    return 0
