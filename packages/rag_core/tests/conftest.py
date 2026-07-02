"""Shared pytest fixtures and test-only configuration for the rag_core test suite.

Anything reusable across test modules lives here: pytest auto-loads `conftest.py`, so test files use
these fixtures without importing them. Keep test-only settings in `IntegrationConfig` (never in the
app's `rag_core.config.Settings`), and add more test config / fixtures here as the suite grows.
"""

from collections.abc import Iterator

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag_core.store import Store


class IntegrationConfig(BaseSettings):
    """Test-only settings, separate from the app's `rag_core.config.Settings`.

    Reads `TEST_DATABASE_URL` from the environment or `.env` so integration tests connect to an
    isolated database, never the app's real `DATABASE_URL`. Add further test-only settings here.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    test_database_url: str | None = None


@pytest.fixture(scope="session")
def integration_config() -> IntegrationConfig:
    return IntegrationConfig()


@pytest.fixture
def store(integration_config: IntegrationConfig) -> Iterator[Store]:
    # Integration tests must never touch the app's real DATABASE_URL
    if integration_config.test_database_url is None:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Integration tests require an isolated test database "
            "(never the app's DATABASE_URL). Copy .env.example to .env; the test database is "
            "provisioned automatically by infra/postgres/init.sql on `docker compose up -d`."
        )
    s = Store(database_url=integration_config.test_database_url)
    s.initialize_schema()
    yield s
    # Clears them together without needing CASCADE for the chunks -> documents foreign key.
    with s.get_connection() as conn:
        conn.execute("TRUNCATE documents, chunks")
