from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for rag_core.

    Loads from environment variables or .env file.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database connection string. Required — supplied via env or .env (see .env.example);
    # no default so a missing DATABASE_URL fails loudly instead of silently using a fake one.
    database_url: str

    # Vector dimensions (pinned to bge-m3)
    embedding_dimension: int = 1024

    # Default user for single-user local scope (ADR 0003)
    default_user_id: UUID = UUID("00000000-0000-0000-0000-000000000000")


# Required fields are populated from the environment / .env by pydantic-settings at runtime,
# which mypy's dataclass-style view of the model can't see — hence the call-arg ignore.
settings = Settings()  # type: ignore[call-arg]
