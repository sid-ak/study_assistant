"""Shared pytest fixtures and test-only configuration for the rag_core test suite.

Anything reusable across test modules lives here: pytest auto-loads `conftest.py`, so test files use
these fixtures without importing them. Keep test-only settings in `IntegrationConfig` (never in the
app's `rag_core.config.Settings`), and add more test config / fixtures here as the suite grows.
"""

from collections.abc import Iterator

import pytest
from psycopg import sql
from pydantic_settings import BaseSettings, SettingsConfigDict
from support import EMBEDDER_A

from rag_core.store import InMemoryStore, Store, StoreProtocol
from rag_core.store.connection import connect
from rag_core.store.embedders import (
    EmbedderInfo,
    EmbedderRegistry,
    EmbedderRegistryProtocol,
    InMemoryEmbedderRegistry,
)


class IntegrationConfig(BaseSettings):
    """Test-only settings, separate from the app's `rag_core.config.Settings`.

    Reads `TEST_DATABASE_URL` from the environment or `.env` so integration tests connect to an
    isolated database, never the app's real `DATABASE_URL`. Add further test-only settings here.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    test_database_url: str | None = None


@pytest.fixture(scope="session")
def integration_config() -> IntegrationConfig:
    """Session-scoped test-only settings, read once from the environment / `.env`."""
    return IntegrationConfig()


@pytest.fixture
def database_url(integration_config: IntegrationConfig) -> Iterator[str]:
    """``TEST_DATABASE_URL`` with the schema initialized; tables and embedding columns reset after.

    The DB-backed fixtures below all build on this one, so a test that uses several of them shares
    one database and one teardown.
    """
    # Integration tests must never touch the app's real DATABASE_URL
    if integration_config.test_database_url is None:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Integration tests require an isolated test database "
            "(never the app's DATABASE_URL). Copy .env.example to .env; the test database is "
            "provisioned automatically by infra/postgres/init.sql on `docker compose up -d`."
        )
    url = integration_config.test_database_url
    Store(database_url=url, embedders=EmbedderRegistry(url)).initialize()
    yield url
    with connect(url) as conn:
        # Per-model columns outlive a TRUNCATE, so drop them first: a later test may register the
        # same model id with a different dimension.
        rows = conn.execute("SELECT column_name FROM embedding_models").fetchall()
        for row in rows:
            conn.execute(
                sql.SQL("ALTER TABLE chunks DROP COLUMN IF EXISTS {}").format(
                    sql.Identifier(row["column_name"])
                )
            )
        # Clears them together without needing CASCADE for the chunks -> documents foreign key.
        conn.execute("TRUNCATE documents, chunks, embedding_models")


@pytest.fixture
def db_embedder_registry(database_url: str) -> EmbedderRegistry:
    """Real, DB-backed ``EmbedderRegistry`` against the test database.

    For behavior only the DB registry has (the columns and indexes it adds). Shared registry
    behavior uses the parametrized ``embedder_registry`` fixture instead.
    """
    return EmbedderRegistry(database_url)


@pytest.fixture
def db_store(database_url: str, db_embedder_registry: EmbedderRegistry) -> Store:
    """Real, DB-backed ``Store`` reading the current embedder from ``db_embedder_registry``.

    For behavior only the concrete ``Store`` has (raw vector round-tripping, schema DDL). Shared
    ``StoreProtocol`` behavior uses the parametrized ``store`` fixture instead.
    """
    return Store(database_url=database_url, embedders=db_embedder_registry)


@pytest.fixture(
    params=[
        "memory",
        pytest.param("db", marks=pytest.mark.integration),
    ]
)
def backend(request: pytest.FixtureRequest) -> str:
    """Each storage backend, once each: ``memory`` or ``db``, the ``[memory]``/``[db]`` test ids.

    ``store`` and ``embedder_registry`` both follow it, so a test using both gets a matched pair.
    """
    param: str = request.param
    return param


@pytest.fixture
def embedder_registry(backend: str, request: pytest.FixtureRequest) -> EmbedderRegistryProtocol:
    """Every ``EmbedderRegistryProtocol`` implementation, once each; backs its contract suite."""
    if backend == "memory":
        return InMemoryEmbedderRegistry()
    db_registry: EmbedderRegistry = request.getfixturevalue("db_embedder_registry")
    return db_registry


@pytest.fixture
def store(
    backend: str, embedder_registry: EmbedderRegistryProtocol, request: pytest.FixtureRequest
) -> StoreProtocol:
    """Every ``StoreProtocol`` implementation, once each, wired to the matching registry.

    Backs the store contract suite.
    """
    if backend == "memory":
        return InMemoryStore(embedders=embedder_registry)
    db_store: Store = request.getfixturevalue("db_store")
    return db_store


@pytest.fixture
def embedder(embedder_registry: EmbedderRegistryProtocol) -> EmbedderInfo:
    """``EMBEDDER_A`` registered and marked current, ready for ``add_chunks``."""
    embedder_registry.register(EMBEDDER_A.model_id, EMBEDDER_A.dimension)
    embedder_registry.set_current(EMBEDDER_A.model_id)
    return EMBEDDER_A
