"""The approval checkpoint: what a paused run offers, and the decisions that resume it."""

from dataclasses import dataclass
from typing import Any

from api.graph.state import AgentState

# The two decisions a paused run accepts, passed back in when it is resumed.
APPROVE = "approve"
REJECT = "reject"


@dataclass(frozen=True)
class PendingSource:
    """One retrieved chunk awaiting a decision: enough to recognize it, without its text.

    ``relevance`` is what the search ranked it by, which is also what the relevance grade was
    taken from: the reranker's score when the search reranks, otherwise the cosine similarity.
    """

    id: str
    document: str
    section: str
    relevance: float


@dataclass(frozen=True)
class PendingReview:
    """A run paused after grading, waiting for its sources to be approved or rejected.

    ``thread_id`` is what a later ``resume`` names to continue this run. ``query`` is the search
    the sources came from, which is the question itself on the first hop and the model's rewrite
    after that.
    """

    thread_id: str
    question: str
    query: str
    hops: int
    sources: list[PendingSource]


def review_payload(state: AgentState) -> dict[str, Any]:
    """What the checkpoint presents for approval, as plain JSON-ready values.

    Only plain values: the payload is saved with the run and read back by whatever resumes it,
    which may be another process that has no classes of ours loaded.
    """
    sources: list[dict[str, Any]] = []
    for hit in state["hits"]:
        sources.append(
            {
                "id": hit.id,
                "document": hit.document,
                "section": hit.section,
                "relevance": hit.relevance,
            }
        )
    return {
        "question": state["question"],
        "query": state["query"],
        "hops": state["hops"],
        "sources": sources,
    }


def review_from_payload(payload: Any, thread_id: str) -> PendingReview:
    """Read a ``PendingReview`` for ``thread_id`` back from a checkpoint's payload."""
    if not isinstance(payload, dict):
        raise ValueError(f"The paused run under {thread_id} saved no sources to approve.")
    sources: list[PendingSource] = []
    for source in payload["sources"]:
        sources.append(
            PendingSource(
                id=source["id"],
                document=source["document"],
                section=source["section"],
                relevance=source["relevance"],
            )
        )
    return PendingReview(
        thread_id=thread_id,
        question=payload["question"],
        query=payload["query"],
        hops=payload["hops"],
        sources=sources,
    )


def decision_is_approval(decision: Any) -> bool:
    """Whether ``decision`` approves the sources; rejects them if it does not.

    Raises ``ValueError`` for anything that is neither, so a typo cannot pass as a rejection.
    """
    if decision == APPROVE:
        return True
    if decision == REJECT:
        return False
    raise ValueError(f"The decision must be {APPROVE!r} or {REJECT!r}, not {decision!r}.")
