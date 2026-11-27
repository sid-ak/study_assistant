"""Evaluating the agent: are its citations grounded, and do they point at the labeled sections?

Generation is judged separately from retrieval. An answered question is grounded when it cites at
least one chunk and every cited chunk was in the context the model was shown. Citation recall asks
whether the cited chunks lie in the sections the golden set labels as the answer.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from api.graph import AgentAnswer
from api.mcp_client import SearchHit
from evals.golden import GoldenQuestion
from evals.metrics import percentile, section_recall

# How the evaluation runs the agent: question text in, answer out.
AnswerFunction = Callable[[str], Awaitable[AgentAnswer]]


@dataclass(frozen=True)
class AgentQuestionResult:
    """How the agent did on one golden question.

    ``grounded`` is ``None`` when the agent gave no answer, since there is nothing to check.
    """

    id: str
    text: str
    status: str
    answer: str
    cited_chunk_ids: list[str]
    cited_sections: list[str]
    context_ids: list[str]
    grounded: bool | None
    citation_recall: float
    hops: int
    queries: list[str]
    latency_ms: float


@dataclass(frozen=True)
class AgentEvalRun:
    """One agent evaluation: its settings, every question's result, and the totals.

    ``grounding_pass_rate`` is the share of answered questions that are grounded, or ``None`` when
    nothing was answered. ``citation_recall`` is the mean over all questions, so an unanswered
    question counts as 0.
    """

    generation_model: str
    question_count: int
    answered: int
    insufficient_context: int
    grounding_pass_rate: float | None
    citation_recall: float
    latency_p50_ms: float
    latency_p95_ms: float
    questions: list[AgentQuestionResult]


def is_grounded(result: AgentAnswer) -> bool | None:
    """Whether an answer cites something and every cited id was in its context.

    ``None`` for an unanswered question, which has no citations to check.
    """
    if result.status != "answered":
        return None
    if not result.cited_chunk_ids:
        return False
    context_ids: set[str] = set()
    for hit in result.context:
        context_ids.add(hit.id)
    for chunk_id in result.cited_chunk_ids:
        if chunk_id not in context_ids:
            return False
    return True


def hit_metadata(hit: SearchHit) -> dict[str, Any]:
    """A cited chunk in the shape the retrieval metrics read: its source and heading path."""
    return {"source": hit.document, "headings": hit.section.split(" > ")}


async def run_agent_eval(
    questions: list[GoldenQuestion], *, answer: AnswerFunction, generation_model: str
) -> AgentEvalRun:
    """Ask each question through ``answer`` and score the answers.

    Questions are asked one at a time, in order, on the caller's event loop, so one open MCP
    connection serves them all. Each is timed from question to answer.
    """
    results: list[AgentQuestionResult] = []
    for question in questions:
        started = time.perf_counter()
        result = await answer(question.text)
        latency_ms = (time.perf_counter() - started) * 1000.0
        cited_metadata = [hit_metadata(citation) for citation in result.citations]
        cited_sections = [
            f"{citation.document} > {citation.section}" for citation in result.citations
        ]
        results.append(
            AgentQuestionResult(
                id=question.id,
                text=question.text,
                status=result.status,
                answer=result.answer,
                cited_chunk_ids=result.cited_chunk_ids,
                cited_sections=cited_sections,
                context_ids=[hit.id for hit in result.context],
                grounded=is_grounded(result),
                citation_recall=section_recall(cited_metadata, question.expected),
                hops=result.hops,
                queries=result.queries,
                latency_ms=latency_ms,
            )
        )
    return summarize(results, generation_model)


def summarize(results: list[AgentQuestionResult], generation_model: str) -> AgentEvalRun:
    """The run's totals from its per-question results."""
    answered = 0
    grounded = 0
    total_citation_recall = 0.0
    latencies: list[float] = []
    for result in results:
        if result.grounded is not None:
            answered += 1
            if result.grounded:
                grounded += 1
        total_citation_recall += result.citation_recall
        latencies.append(result.latency_ms)
    grounding_pass_rate = None
    if answered > 0:
        grounding_pass_rate = grounded / answered
    return AgentEvalRun(
        generation_model=generation_model,
        question_count=len(results),
        answered=answered,
        insufficient_context=len(results) - answered,
        grounding_pass_rate=grounding_pass_rate,
        citation_recall=total_citation_recall / len(results),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        questions=results,
    )
