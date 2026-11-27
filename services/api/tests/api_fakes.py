"""Fakes for the generation lane's interfaces, used by the ``services/api`` tests."""

from api.generate import ChatMessage, ResponseSchema


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
