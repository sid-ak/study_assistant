"""Generation: the ``Generator`` interface and its OpenAI-compatible adapter."""

from api.generate.cache import FileResponseCache, ResponseCacheProtocol
from api.generate.errors import GenerationError, RateLimitError
from api.generate.openai_compatible import OpenAICompatibleGenerator
from api.generate.protocol import ChatMessage, GeneratorProtocol, ResponseSchema
from api.generate.rate_limit import parse_duration

__all__ = [
    "ChatMessage",
    "FileResponseCache",
    "GenerationError",
    "GeneratorProtocol",
    "OpenAICompatibleGenerator",
    "RateLimitError",
    "ResponseCacheProtocol",
    "ResponseSchema",
    "parse_duration",
]
