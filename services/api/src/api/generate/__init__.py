"""Generation: the ``Generator`` interface and its OpenAI-compatible adapter."""

from api.generate.errors import GenerationError
from api.generate.openai_compatible import OpenAICompatibleGenerator
from api.generate.protocol import ChatMessage, GeneratorProtocol, ResponseSchema

__all__ = [
    "ChatMessage",
    "GenerationError",
    "GeneratorProtocol",
    "OpenAICompatibleGenerator",
    "ResponseSchema",
]
