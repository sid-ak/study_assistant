"""The ``Reranker`` interface: score how well each candidate passage answers a query."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class RerankerProtocol(Protocol):
    """Scores query and passage pairs by reading each pair together.

    Scores are relevance from 0 (unrelated) to 1 (answers the query), one per passage in the order
    given, so callers can sort by them and compare them with a fixed threshold.
    """

    @property
    def model_id(self) -> str:
        """The model that produces the scores."""
        ...

    def score(self, query: str, documents: list[str]) -> list[float]:
        """The relevance of each of ``documents`` to ``query``, in the same order."""
        ...
