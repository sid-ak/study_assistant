"""The ``study-ask`` console script: answer one question, or pause it for approval first."""

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from uuid import uuid4

from api.config import ApiSettings
from api.generate import GenerationError, OpenAICompatibleGenerator
from api.graph import (
    APPROVE,
    REJECT,
    AgentAnswer,
    AgentConfig,
    AgentOutcome,
    CompiledAgent,
    PendingReview,
    ask,
    build_graph,
    resume,
    start,
)
from api.graph.checkpoint import postgres_checkpointer
from api.mcp_client import McpSearchClient, SearchError, stdio_server

# Exit status when the model or the search tool failed.
FAILURE = 1
# Exit status for settings the agent cannot honor, as argparse uses for bad arguments.
USAGE_ERROR = 2


def agent_config(settings: ApiSettings, *, require_approval: bool = False) -> AgentConfig:
    """The agent's bounds from the ``AGENT_*`` settings, pausing for approval if asked."""
    return AgentConfig(
        max_hops=settings.agent_max_hops,
        relevance_threshold=settings.agent_relevance_threshold,
        search_limit=settings.agent_search_limit,
        require_approval=require_approval,
    )


def checkpoint_database_url(settings: ApiSettings) -> str:
    """Where paused runs are saved, or a usage error when no database is configured."""
    if settings.database_url is None or not settings.database_url.strip():
        raise ValueError(
            "Pausing a question for approval needs somewhere to save the run; set DATABASE_URL."
        )
    return settings.database_url


@asynccontextmanager
async def open_agent(settings: ApiSettings, config: AgentConfig) -> AsyncIterator[CompiledAgent]:
    """Start what a run needs and yield the compiled agent, stopping it all afterwards.

    The MCP server is started in the current folder, so it reads the same ``.env`` as this
    command. A run that pauses also needs the saver for its state, so the two are opened on one
    stack and closed in reverse.
    """
    generator = OpenAICompatibleGenerator.from_settings(settings)
    server = stdio_server(settings.mcp_server_command, Path.cwd())
    async with AsyncExitStack() as stack:
        search = await stack.enter_async_context(McpSearchClient(server))
        checkpointer = None
        if config.require_approval:
            checkpointer = await stack.enter_async_context(
                postgres_checkpointer(checkpoint_database_url(settings))
            )
        yield build_graph(search, generator, config=config, checkpointer=checkpointer)


async def answer_question(question: str, settings: ApiSettings, config: AgentConfig) -> AgentAnswer:
    """Run the agent on ``question`` from start to answer."""
    async with open_agent(settings, config) as graph:
        return await ask(graph, question)


async def start_question(
    question: str, settings: ApiSettings, config: AgentConfig, *, thread_id: str
) -> AgentOutcome:
    """Run the agent on ``question`` until it answers or pauses for approval under ``thread_id``."""
    async with open_agent(settings, config) as graph:
        return await start(graph, question, thread_id=thread_id)


async def resume_question(
    decision: str, settings: ApiSettings, config: AgentConfig, *, thread_id: str
) -> AgentOutcome:
    """Carry ``decision`` to the run paused under ``thread_id``."""
    async with open_agent(settings, config) as graph:
        return await resume(graph, decision, thread_id=thread_id)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for ``study-ask``."""
    parser = argparse.ArgumentParser(
        prog="study-ask",
        description=(
            "Answer a question from the ingested documents, citing the chunks used. With "
            "--review the run pauses first and lists the sources it would answer from, and a "
            "later --resume carries the decision."
        ),
    )
    parser.add_argument("question", nargs="?", help="The question to answer.")
    parser.add_argument(
        "--review",
        action="store_true",
        help="Pause after retrieval and list the sources for approval instead of answering.",
    )
    parser.add_argument(
        "--thread-id",
        help="Name the paused run; a fresh name is chosen when this is left out.",
    )
    parser.add_argument(
        "--resume",
        metavar="THREAD_ID",
        help="Continue the run paused under this thread id.",
    )
    decision = parser.add_mutually_exclusive_group()
    decision.add_argument(
        "--approve", action="store_true", help="Answer from the paused run's sources."
    )
    decision.add_argument(
        "--reject", action="store_true", help="Search again instead, within the hop limit."
    )
    return parser


def decision_of(args: argparse.Namespace) -> str:
    """The decision the arguments carry, raising ``ValueError`` when they carry neither.

    The flags are mutually exclusive, so at most one of them is set.
    """
    if args.approve:
        return APPROVE
    if args.reject:
        return REJECT
    raise ValueError("A resumed run needs a decision: --approve or --reject.")


def check_arguments(args: argparse.Namespace) -> None:
    """Raise ``ValueError`` for a combination of arguments the command cannot act on."""
    decided = args.approve or args.reject
    if args.question is not None and args.resume is not None:
        raise ValueError("Give a question to ask or --resume a paused run, not both.")
    if args.question is None and args.resume is None:
        raise ValueError("Give a question to ask, or --resume a paused run with a decision.")
    if args.resume is not None:
        # Raises when neither flag was given, with the same message the resume itself would use.
        decision_of(args)
    if args.resume is None and decided:
        raise ValueError("--approve and --reject decide a paused run, so they need --resume.")
    if args.resume is None and args.thread_id is not None and not args.review:
        raise ValueError("--thread-id names a run paused by --review.")


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


def print_pending(pending: PendingReview) -> None:
    """Print the sources a paused run offers and the two commands that continue it."""
    count = len(pending.sources)
    sources = "source" if count == 1 else "sources"
    searches = "search" if pending.hops == 1 else "searches"
    print(f"Paused for approval of {count} {sources}, after {pending.hops} {searches}.")
    print(f"Searched: {pending.query}")
    print()
    for number, source in enumerate(pending.sources, start=1):
        print(f"[{number}] {source.document} > {source.section} (relevance {source.relevance:.3f})")
    print()
    print(f"Thread: {pending.thread_id}")
    print(f"Approve: study-ask --resume {pending.thread_id} --approve")
    print(f"Reject:  study-ask --resume {pending.thread_id} --reject")


def print_outcome(outcome: AgentOutcome) -> None:
    """Print a finished run's answer, or the checkpoint a paused one stopped at."""
    if isinstance(outcome, PendingReview):
        print_pending(outcome)
    else:
        print_answer(outcome)


def main(argv: list[str] | None = None) -> int:
    """Run ``study-ask`` and return its exit status.

    0 on success, 2 for arguments or settings the agent cannot honor, found before the server
    starts, and 1 if the model or the search tool failed.
    """
    args = build_parser().parse_args(argv)
    try:
        check_arguments(args)
        settings = ApiSettings()
        in_review = args.review or args.resume is not None
        config = agent_config(settings, require_approval=in_review)
        if in_review:
            checkpoint_database_url(settings)
    except ValueError as error:
        print(f"study-ask: {error}", file=sys.stderr)
        return USAGE_ERROR
    try:
        if args.resume is not None:
            outcome = asyncio.run(
                resume_question(decision_of(args), settings, config, thread_id=args.resume)
            )
        elif args.review:
            thread_id = args.thread_id or uuid4().hex
            outcome = asyncio.run(
                start_question(args.question, settings, config, thread_id=thread_id)
            )
        else:
            outcome = asyncio.run(answer_question(args.question, settings, config))
    except (GenerationError, SearchError) as error:
        print(f"study-ask: {error}", file=sys.stderr)
        return FAILURE
    except ValueError as error:
        print(f"study-ask: {error}", file=sys.stderr)
        return USAGE_ERROR
    print_outcome(outcome)
    return 0
