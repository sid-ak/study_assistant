"""Resume a paused agent run and print its outcome as JSON: the child half of a checkpoint test.

Run as ``python resume_child.py <thread-id> <database-url> <decision>``. It builds the same graph
over fakes that the test did, reads the paused run out of Postgres, and carries the decision. Its
search client knows no answers, so anything it cites must come from the saved state.
"""

import asyncio
import json
import sys

from api_fakes import FakeSearchClient, ScriptedGenerator

from api.graph import AgentAnswer, AgentConfig, build_graph, resume
from api.graph.checkpoint import postgres_checkpointer

# The answer the child's model returns, which the test looks for in its output.
CHILD_ANSWER = "Use --config=asan, from the saved sources."
REVIEW_CONFIG = AgentConfig(
    max_hops=2, relevance_threshold=0.65, search_limit=5, require_approval=True
)


def answer_reply(answer: str, cited: list[str]) -> str:
    """The JSON the model returns for the answer step."""
    return json.dumps({"answerable": True, "answer": answer, "cited_chunk_ids": cited})


async def finish(thread_id: str, database_url: str, decision: str) -> dict[str, object]:
    """Carry ``decision`` to the run paused under ``thread_id`` and describe what came back."""
    search = FakeSearchClient({})
    generator = ScriptedGenerator([answer_reply(CHILD_ANSWER, ["chunk-asan"])])
    async with postgres_checkpointer(database_url) as saver:
        graph = build_graph(search, generator, config=REVIEW_CONFIG, checkpointer=saver)
        outcome = await resume(graph, decision, thread_id=thread_id)
    if not isinstance(outcome, AgentAnswer):
        raise AssertionError(f"The run paused again instead of answering: {outcome}.")
    citations: list[dict[str, object]] = []
    for citation in outcome.citations:
        citations.append(
            {
                "id": citation.id,
                "document": citation.document,
                "section": citation.section,
                "relevance": citation.relevance,
            }
        )
    return {
        "status": outcome.status,
        "answer": outcome.answer,
        "citations": citations,
        # The class names of the restored hits, so the test can see they are not plain dicts.
        "hit_types": [type(hit).__name__ for hit in outcome.context],
        "searched": search.queries,
    }


def main() -> int:
    """Read the thread id, database URL, and decision from the arguments and print the outcome."""
    thread_id, database_url, decision = sys.argv[1], sys.argv[2], sys.argv[3]
    print(json.dumps(asyncio.run(finish(thread_id, database_url, decision))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
