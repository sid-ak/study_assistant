"""Builders for the agent results the chat tests hand to the page."""

from api.graph import AgentAnswer
from api.mcp_client import SearchHit


def hit(document: str, section: str) -> SearchHit:
    """A search hit located at ``document > section``, with placeholder text and scores."""
    return SearchHit(
        id=f"{document}:{section}",
        document=document,
        section=section,
        content="placeholder chunk text",
        distance=0.2,
        relevance=0.8,
    )


def answered(answer: str, citations: list[SearchHit], queries: list[str]) -> AgentAnswer:
    """A run that answered with ``answer``, citing ``citations``, after one hop per query."""
    return AgentAnswer(
        status="answered",
        answer=answer,
        cited_chunk_ids=[citation.id for citation in citations],
        citations=citations,
        context=citations,
        queries=queries,
        hops=len(queries),
    )


def unanswered(queries: list[str]) -> AgentAnswer:
    """A run that found nothing relevant enough to answer from, after one hop per query."""
    return AgentAnswer(
        status="insufficient_context",
        answer="",
        cited_chunk_ids=[],
        citations=[],
        context=[],
        queries=queries,
        hops=len(queries),
    )
