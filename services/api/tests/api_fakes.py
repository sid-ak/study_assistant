"""Fakes for the generation lane's interfaces, used by the ``services/api`` tests."""

from api.generate import ChatMessage, ResponseSchema
from api.mcp_client import SearchHit


class ScriptedGenerator:
    """A ``Generator`` that returns prepared replies in order and records every request."""

    def __init__(self, replies: list[str], model: str = "test/scripted-model") -> None:
        """Answer successive requests with ``replies``."""
        self.replies = list(replies)
        self._model = model
        # Each request as (messages, response_schema), in the order they arrived.
        self.requests: list[tuple[list[ChatMessage], ResponseSchema | None]] = []

    @property
    def model(self) -> str:
        """The fake model's name."""
        return self._model

    def generate(
        self, messages: list[ChatMessage], *, response_schema: ResponseSchema | None = None
    ) -> str:
        """Record the request and return the next prepared reply.

        Raises ``AssertionError`` when no reply is left, so a test that expects fewer model calls
        than the code makes fails at the extra call.
        """
        self.requests.append((list(messages), response_schema))
        if not self.replies:
            raise AssertionError("ScriptedGenerator received more requests than it has replies.")
        return self.replies.pop(0)


class FakeSearchClient:
    """A ``SearchClientProtocol`` that answers each query with prepared hits and records queries."""

    def __init__(self, hits_by_query: dict[str, list[SearchHit]]) -> None:
        """Answer a query with ``hits_by_query[query]``, or no hits for an unknown query."""
        self.hits_by_query = hits_by_query
        self.queries: list[str] = []

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        """Record the query and return its prepared hits, at most ``limit`` of them."""
        self.queries.append(query)
        return self.hits_by_query.get(query, [])[:limit]
