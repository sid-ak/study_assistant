"""Fixtures shared by the ``services/api`` tests, including the checkpoint test database."""

from collections.abc import Iterator

import psycopg
import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

# The tables LangGraph's Postgres checkpointer creates, dropped after a test that used them.
CHECKPOINT_TABLES = "checkpoint_writes, checkpoint_blobs, checkpoints, checkpoint_migrations"


class IntegrationConfig(BaseSettings):
    """Test-only settings, separate from the app's ``api.config.ApiSettings``.

    Reads ``TEST_DATABASE_URL`` from the environment or ``.env`` so integration tests save their
    checkpoints to an isolated database, never the app's real ``DATABASE_URL``.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    test_database_url: str | None = None


@pytest.fixture
def checkpoint_database_url() -> Iterator[str]:
    """``TEST_DATABASE_URL`` for saved runs; the checkpoint tables are dropped after the test.

    The checkpointer creates its own tables on first use, so nothing is set up here. They are
    dropped afterwards rather than emptied, so one test's threads cannot reach another's.
    """
    config = IntegrationConfig()
    if config.test_database_url is None:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Integration tests require an isolated test database "
            "(never the app's DATABASE_URL). Copy .env.example to .env; the test database is "
            "provisioned automatically on the first `docker compose up -d`."
        )
    url = config.test_database_url
    yield url
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(f"DROP TABLE IF EXISTS {CHECKPOINT_TABLES}")
