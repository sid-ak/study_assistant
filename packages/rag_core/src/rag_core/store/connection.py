"""Postgres connection handling shared by every DB-backed class in the store package."""

from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from rag_core.config import settings


def resolve_database_url(database_url: str | None) -> str:
    """Return ``database_url``, or ``settings.database_url``, raising if neither is set."""
    url = database_url or settings.database_url
    if url is None:
        raise RuntimeError(
            "No database URL configured. Pass database_url=... or set DATABASE_URL "
            "in the environment / .env (see .env.example)."
        )
    return url


def connect(database_url: str) -> psycopg.Connection[Any]:
    """Open a connection that returns dict rows and (de)serializes ``vector`` columns."""
    conn = psycopg.connect(database_url, row_factory=dict_row)
    register_vector(conn)
    return conn
