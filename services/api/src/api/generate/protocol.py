"""The ``Generator`` interface: send chat messages to a language model and read its reply."""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    """One message of a conversation: its ``role`` (system, user, or assistant) and text."""

    role: str
    content: str


@dataclass(frozen=True)
class ResponseSchema:
    """A JSON schema the reply must match exactly, and the name it is sent under."""

    name: str
    schema: dict[str, Any]


@runtime_checkable
class GeneratorProtocol(Protocol):
    """A language model that answers a list of chat messages with one reply.

    Each call is one request to the model. With a ``response_schema``, the reply is a JSON
    document matching that schema; without one, it is free text.
    """

    @property
    def model(self) -> str:
        """The model that produces the replies."""
        ...

    def generate(
        self, messages: list[ChatMessage], *, response_schema: ResponseSchema | None = None
    ) -> str:
        """Return the model's reply to ``messages``.

        Raises ``GenerationError`` if the model cannot be reached or returns no reply.
        """
        ...
