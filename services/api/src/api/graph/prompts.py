"""The messages and the answer schema the agent sends to the model."""

from typing import Any

from api.generate import ChatMessage, ResponseSchema
from api.mcp_client import SearchHit

REWRITE_INSTRUCTIONS = (
    "You turn questions into search queries for a collection of release-engineering documents: "
    "CMake and Bazel build guides, CI failure write-ups, and release notes. Reply with the query "
    "only, on one line, with no quotes and no explanation."
)

ANSWER_INSTRUCTIONS = (
    "Answer the question using only the context below. Each context chunk starts with its id in "
    "square brackets. Put the id of every chunk your answer relies on in cited_chunk_ids. Never "
    "write chunk ids, brackets, or source names in the answer text itself. If the context does not "
    "answer the question, set answerable to false, answer to an empty string, and cited_chunk_ids "
    "to an empty list. Keep the answer to one to three sentences."
)


def rewrite_messages(question: str, previous_query: str) -> list[ChatMessage]:
    """Ask for a better search query for ``question``, after ``previous_query`` found nothing."""
    request = (
        f"Question: {question}\n"
        f"The search query {previous_query!r} found nothing relevant. Write a different query, "
        "using the words a document answering the question would likely contain."
    )
    return [ChatMessage("system", REWRITE_INSTRUCTIONS), ChatMessage("user", request)]


def answer_messages(question: str, context: list[SearchHit]) -> list[ChatMessage]:
    """Ask for an answer to ``question`` from ``context`` only, citing chunks by id."""
    blocks: list[str] = []
    for hit in context:
        blocks.append(f"[{hit.id}] ({hit.document}: {hit.section})\n{hit.content}")
    request = "Context:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
    return [ChatMessage("system", ANSWER_INSTRUCTIONS), ChatMessage("user", request)]


def answer_schema(context: list[SearchHit]) -> ResponseSchema:
    """The strict schema of the answer: answerable, the answer, and ids from ``context`` only.

    The cited ids are an ``enum`` of the context's chunk ids, so with strict structured output the
    model cannot cite a chunk it was not shown.
    """
    context_ids = [hit.id for hit in context]
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean"},
            "answer": {"type": "string"},
            "cited_chunk_ids": {"type": "array", "items": {"type": "string", "enum": context_ids}},
        },
        "required": ["answerable", "answer", "cited_chunk_ids"],
        "additionalProperties": False,
    }
    return ResponseSchema(name="cited_answer", schema=schema)
