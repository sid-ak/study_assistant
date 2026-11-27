"""Where paused runs are saved: a Postgres checkpointer for the agent graph.

The database holds the state of runs waiting for a decision, so a pause outlives the process that
started it. It is the same database the corpus lives in, but this lane never reads the corpus from
it: retrieval stays behind the search tool.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from api.mcp_client import SearchHit


class CheckpointError(Exception):
    """The database holding paused runs failed, while connecting or during a run."""


def checkpoint_serializer() -> JsonPlusSerializer:
    """The serializer saved runs use, told about the types the graph's state carries.

    A type the serializer does not know is restored as a plain dictionary, which the answer step
    would only trip over later, so every such type is listed here.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=(SearchHit,))


@asynccontextmanager
async def postgres_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    """Open a saver for paused runs on ``database_url``, creating its tables on first use.

    Raises ``ValueError`` without a connection string, so a run cannot reach its pause before
    finding out that there is nowhere to save it, and ``CheckpointError`` when the database cannot
    be used, whether it refuses the connection or fails later in the run, so the caller can report
    one line instead of a driver traceback.
    """
    if not database_url.strip():
        raise ValueError(
            "Saving a paused run needs a database connection string; set DATABASE_URL."
        )
    try:
        async with AsyncPostgresSaver.from_conn_string(
            database_url, serde=checkpoint_serializer()
        ) as saver:
            # Idempotent: it creates the tables the first time and checks them after that.
            await saver.setup()
            yield saver
    except psycopg.OperationalError as error:
        raise CheckpointError(f"The database holding paused runs failed: {error}") from error
