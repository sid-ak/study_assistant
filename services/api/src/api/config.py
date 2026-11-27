"""Settings for the generation lane, read from the environment or a ``.env`` file."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """Configuration for the agent: the generation endpoint and model.

    Each field reads the environment variable of the same name in capitals, such as
    ``GENERATION_MODEL``.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Any endpoint that speaks the OpenAI-compatible chat-completions protocol.
    generation_base_url: str = "https://api.groq.com/openai/v1"
    generation_model: str = "qwen/qwen3.8-27b"
    # None for a local runtime that needs no key. SecretStr keeps the key out of reprs and logs.
    generation_api_key: SecretStr | None = None
    # Where replies are cached, relative to the working folder.
    generation_cache_dir: Path | None = Path(".cache/generation")
