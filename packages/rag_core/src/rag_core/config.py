"""Application configuration for rag_core, loaded from the environment / ``.env``."""

from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for rag_core.

    Loads from environment variables or .env file.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Optional so components (docs, tests, etc.) can build without a real database.
    database_url: str | None = None

    # Vector dimensions (pinned to bge-m3)
    embedding_dimension: int = 1024

    # Default user for single-user local scope
    default_user_id: UUID = UUID("00000000-0000-0000-0000-000000000000")


settings = Settings()
