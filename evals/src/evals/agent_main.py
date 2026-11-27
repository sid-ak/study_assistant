"""The ``study-eval-agent`` console script: run the golden set through the agent and save the run.

Each question is one full agent run: searches through the MCP server and model requests to the
configured generation endpoint, so a run spends free-plan quota. Cached replies make an unchanged
rerun free.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from api.cli import agent_config
from api.config import ApiSettings
from api.generate import GenerationError, OpenAICompatibleGenerator
from api.graph import AgentAnswer, AgentConfig, CompiledAgent, ask, build_graph
from api.mcp_client import McpSearchClient, SearchError, stdio_server
from evals.agent import AgentEvalRun, run_agent_eval
from evals.golden import GoldenQuestion
from evals.main import (
    USAGE_ERROR,
    add_input_arguments,
    build_components,
    check_embedded,
    load_inputs,
)
from evals.runner import write_run
from rag_core.config import Settings
from rag_core.store import EmbedderNotFoundError

# Exit status when the model or the search tool failed partway through the run.
FAILURE = 1


class GraphAnswerer:
    """Answers questions with one compiled agent graph, as ``run_agent_eval`` expects."""

    def __init__(self, graph: CompiledAgent) -> None:
        """Answer with ``graph``."""
        self.graph = graph

    async def __call__(self, question: str) -> AgentAnswer:
        """Run the agent on ``question``."""
        return await ask(self.graph, question)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for ``study-eval-agent``; default paths are from the repository root."""
    parser = argparse.ArgumentParser(
        prog="study-eval-agent",
        description="Run the golden set through the agent, check its citations, and save the run.",
    )
    add_input_arguments(parser)
    return parser


def check_store_ready() -> None:
    """Raise ``ValueError`` unless every stored chunk has a vector from the configured model.

    The MCP server searches with the same settings, so this is the model the agent will use.
    """
    components = build_components(Settings())
    check_embedded(components.store, components.embedder.info.model_id)


async def run_live(
    questions: list[GoldenQuestion], settings: ApiSettings, config: AgentConfig
) -> AgentEvalRun:
    """Start the MCP server, run the agent on every question within ``config``, and score them."""
    generator = OpenAICompatibleGenerator.from_settings(settings)
    async with McpSearchClient(stdio_server(settings.mcp_server_command, Path.cwd())) as search:
        graph = build_graph(search, generator, config=config)
        # The server reads the same settings, so these name how its searches ranked.
        retrieval = Settings()
        reranker = None
        candidates = None
        if retrieval.rerank_enabled:
            reranker = retrieval.reranker_model
            candidates = retrieval.rerank_candidates
        return await run_agent_eval(
            questions,
            answer=GraphAnswerer(graph),
            generation_model=generator.model,
            reranker=reranker,
            candidates=candidates,
        )


def print_agent_run(run: AgentEvalRun) -> None:
    """Print each question's outcome, then the grounding and citation totals."""
    for result in run.questions:
        grounded = "-" if result.grounded is None else ("yes" if result.grounded else "NO")
        print(
            f"{result.id:<28} {result.status:<21} grounded {grounded:<3}  "
            f"citation recall {result.citation_recall:.2f}  hops {result.hops}"
        )
    rate = "n/a" if run.grounding_pass_rate is None else f"{run.grounding_pass_rate:.2f}"
    print(
        f"Grounding pass rate {rate}  citation recall {run.citation_recall:.2f}  "
        f"answered {run.answered}/{run.question_count}  "
        f"latency p50 {run.latency_p50_ms:.0f} ms, p95 {run.latency_p95_ms:.0f} ms"
    )
    reranked = ""
    if run.reranker is not None:
        reranked = f", search reranked by {run.reranker} from {run.candidates} candidates"
    print(f"({run.generation_model}{reranked})")


def main(argv: list[str] | None = None) -> int:
    """Run ``study-eval-agent`` and return its status: 0, 2 for bad input, 1 if the agent failed.

    Every input is checked before the first model request, since each request spends quota.
    """
    args = build_parser().parse_args(argv)
    try:
        questions = load_inputs(args)
        # Built here, before the server starts, so a setting the agent cannot honor is one line.
        settings = ApiSettings()
        config = agent_config(settings)
        check_store_ready()
    except (ValueError, OSError, EmbedderNotFoundError) as error:
        print(error, file=sys.stderr)
        return USAGE_ERROR
    try:
        run = asyncio.run(run_live(questions, settings, config))
    except (GenerationError, SearchError) as error:
        print(f"study-eval-agent: {error}", file=sys.stderr)
        return FAILURE
    print_agent_run(run)
    path = write_run(run, args.results, name=args.name)
    print(f"Saved {path}")
    return 0
