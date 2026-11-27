"""The agent's way to retrieval: a client for the MCP server's ``search`` tool."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer

# Environment variables the MCP server reads, by prefix. Only these are passed to its process, on
# top of the MCP SDK's safe defaults (PATH, HOME, and the like); the generation key is not.
# "RERANK" covers RERANK_ENABLED, RERANK_CANDIDATES, and RERANKER_MODEL: the server decides
# whether its searches are reranked.
SERVER_ENVIRONMENT_PREFIXES = ("DATABASE_", "EMBEDDING_", "FASTEMBED_", "RERANK")
# Variables passed by exact name. fastembed keeps its default model cache in the temporary folder,
# so without TMPDIR the server would use /tmp and download a second copy of the model.
SERVER_ENVIRONMENT_NAMES = ("TMPDIR",)
# The most results the search tool returns per call, as its server documents and enforces.
MAX_SEARCH_LIMIT = 20


class SearchError(Exception):
    """The search tool refused the request or returned something unreadable."""


@dataclass(frozen=True)
class SearchHit:
    """One chunk the search tool returned: its id, location, text, distance, and relevance.

    ``relevance`` is what the server ranked by: the reranker's score from 0 to 1 when it reranks,
    otherwise the cosine similarity, 1 minus ``distance``.
    """

    id: str
    document: str
    section: str
    content: str
    distance: float
    relevance: float


@runtime_checkable
class SearchClientProtocol(Protocol):
    """Searches the corpus for the chunks nearest to a query."""

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        """The ``limit`` chunks nearest to ``query``, nearest first."""
        ...


class McpSearchClient:
    """A ``SearchClientProtocol`` that calls the MCP server's ``search`` tool.

    Use it as an async context manager: entering opens one MCP connection, which every search
    reuses, and leaving closes it. ``server`` is either the parameters for starting the server as a
    subprocess over stdio, or, in tests, a server object to connect to in-process.
    """

    def __init__(self, server: StdioServerParameters | MCPServer) -> None:
        """Connect to ``server`` when entered."""
        self.client = Client(server)

    async def __aenter__(self) -> "McpSearchClient":
        """Open the connection; raise ``SearchError`` if the server cannot start or be reached."""
        try:
            await self.client.__aenter__()
        except Exception as error:
            # A missing command raises FileNotFoundError, and a server that exits during startup
            # raises from the SDK; either way the agent has no search tool.
            raise SearchError(f"Could not start or connect to the MCP server: {error}") from error
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the connection, letting any exception from the ``async with`` body pass unchanged.

        The SDK's client runs a task group, which wraps an exception from the body in an
        ``ExceptionGroup``. Closing as if the body had finished cleanly avoids that, and Python then
        re-raises the original exception, so callers can catch ``SearchError`` as it is.
        """
        await self.client.__aexit__(None, None, None)

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        """Call the ``search`` tool; raise ``SearchError`` if it reports an error."""
        result = await self.client.call_tool("search", {"query": query, "limit": limit})
        if result.is_error:
            raise SearchError(error_text(result.content))
        try:
            records = result.structured_content["result"]
            hits: list[SearchHit] = []
            for record in records:
                hits.append(
                    SearchHit(
                        id=str(record["id"]),
                        document=str(record["document"]),
                        section=str(record["section"]),
                        content=str(record["content"]),
                        distance=float(record["distance"]),
                        relevance=float(record["relevance"]),
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise SearchError("The search tool returned an unreadable result.") from error
        return hits


def error_text(content: list[Any]) -> str:
    """The text of a tool error result, joined from its text parts."""
    parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    if not parts:
        return "The search tool reported an error."
    return " ".join(parts)


def server_environment(parent: Mapping[str, str]) -> dict[str, str]:
    """The variables of ``parent`` the MCP server needs: database, models, and model cache."""
    environment: dict[str, str] = {}
    for name, value in parent.items():
        if name.startswith(SERVER_ENVIRONMENT_PREFIXES) or name in SERVER_ENVIRONMENT_NAMES:
            environment[name] = value
    return environment


def stdio_server(command: str, cwd: Path) -> StdioServerParameters:
    """Parameters for starting the MCP server with ``command`` in ``cwd``, where its ``.env`` is."""
    # The SDK merges ``env`` over its own safe defaults, such as PATH and HOME.
    return StdioServerParameters(command=command, cwd=cwd, env=server_environment(os.environ))
