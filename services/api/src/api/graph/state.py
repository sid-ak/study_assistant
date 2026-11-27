"""The state the agent graph carries from one step to the next."""

from typing import TypedDict

from api.mcp_client import SearchHit


class AgentState(TypedDict, total=False):
    """Everything one run of the agent knows so far.

    ``total=False``: a step returns only the keys it changes, and the graph merges them in.
    """

    question: str
    # The query the next search uses: the question, then the model's rewrite of it.
    query: str
    # Every query searched so far, one per hop.
    queries: list[str]
    hops: int
    # The latest search's hits, nearest first, and whether the best of them clears the threshold.
    hits: list[SearchHit]
    relevant: bool
    # The chunks the answer step was shown, or the latest hits when it was never reached.
    context: list[SearchHit]
    status: str
    answer: str
    cited_chunk_ids: list[str]
