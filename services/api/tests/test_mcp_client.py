"""Behavior of ``McpSearchClient``, connected in-process to the real MCP server over fakes.

The server is ``mcp_server``'s own ``build_server`` over the hashing embedder and the in-memory
store, so each search crosses the real MCP protocol between the two packages. Tests may import
``rag_core`` to build that server; the boundary check covers only the ``api`` source.
"""

import asyncio
from pathlib import Path

import pytest
from api_fakes import FakeSearchClient
from mcp.server.mcpserver import MCPServer

from api.mcp_client import (
    MAX_SEARCH_LIMIT,
    McpSearchClient,
    SearchClientProtocol,
    SearchError,
    SearchHit,
    server_environment,
    stdio_server,
)
from mcp_server.server import build_server
from rag_core.ingest import ingest_folder
from rag_core_testing import HASHING_EMBEDDER, HashingEmbedder, InMemoryStore


@pytest.fixture
def server(tmp_path: Path) -> MCPServer:
    """The MCP server over an in-memory store holding two small documents."""
    (tmp_path / "build.md").write_text("# Build\n\n## Caching\n\nccache stores compiled objects.\n")
    (tmp_path / "ci.md").write_text("# Failure\n\n## Cause\n\nlibpthread was not linked.\n")
    store = InMemoryStore(embedder=HASHING_EMBEDDER)
    ingest_folder(tmp_path, store=store, embedder=HashingEmbedder())
    return build_server(embedder=HashingEmbedder(), store=store)


async def search_through(server: MCPServer, query: str, limit: int) -> list[SearchHit]:
    """Open a client on ``server``, search once, and close it."""
    async with McpSearchClient(server) as client:
        return await client.search(query, limit)


def test_search_returns_typed_hits_nearest_first(server: MCPServer) -> None:
    """Hits come back as ``SearchHit`` records with the chunk's location and distance."""
    hits = asyncio.run(search_through(server, "ccache compiled objects", 2))

    assert len(hits) == 2
    assert hits[0].document == "build.md"
    assert hits[0].section == "Build > Caching"
    assert "ccache stores compiled objects." in hits[0].content
    assert hits[0].distance <= hits[1].distance
    assert hits[0].relevance == pytest.approx(1.0 - hits[0].distance)
    assert len(hits[0].id) == 36


def test_one_client_serves_several_searches(server: MCPServer) -> None:
    """A connection stays open across searches, so the server process starts only once."""

    async def two_searches() -> tuple[list[SearchHit], list[SearchHit]]:
        """Run two searches on one connection."""
        async with McpSearchClient(server) as client:
            first = await client.search("ccache", 1)
            second = await client.search("libpthread", 1)
        return first, second

    first, second = asyncio.run(two_searches())

    assert first[0].document == "build.md"
    assert second[0].document == "ci.md"


def test_a_tool_error_raises_search_error(server: MCPServer) -> None:
    """An argument the tool refuses becomes ``SearchError`` with the server's message."""
    with pytest.raises(SearchError, match="limit"):
        asyncio.run(search_through(server, "ccache", 0))


def test_server_environment_passes_only_what_the_server_needs() -> None:
    """The server process gets the database and embedding settings, never the generation key."""
    parent = {
        "PATH": "/usr/bin",
        "DATABASE_URL": "postgresql://db",
        "EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5",
        "EMBEDDING_DIMENSION": "768",
        "FASTEMBED_CACHE_PATH": "/models",
        "TMPDIR": "/var/folders/xy/T/",
        "GENERATION_API_KEY": "sk-secret",
        "UNRELATED": "x",
    }

    environment = server_environment(parent)

    # fastembed's default model cache is under the temporary folder, so without TMPDIR the server
    # would look in /tmp and download its own copy of the model.
    assert environment["TMPDIR"] == "/var/folders/xy/T/"

    assert environment["DATABASE_URL"] == "postgresql://db"
    assert environment["EMBEDDING_MODEL"] == "BAAI/bge-base-en-v1.5"
    assert environment["EMBEDDING_DIMENSION"] == "768"
    assert environment["FASTEMBED_CACHE_PATH"] == "/models"
    assert "GENERATION_API_KEY" not in environment
    assert "UNRELATED" not in environment


def test_the_client_and_the_fake_satisfy_the_protocol(server: MCPServer) -> None:
    """Both search clients fit ``SearchClientProtocol``, so the graph accepts either."""
    real: SearchClientProtocol = McpSearchClient(server)
    fake: SearchClientProtocol = FakeSearchClient({})
    assert isinstance(real, SearchClientProtocol)
    assert isinstance(fake, SearchClientProtocol)


def test_a_server_that_cannot_start_raises_search_error(tmp_path: Path) -> None:
    """A missing server command is reported as ``SearchError``, not an operating-system error."""

    async def connect() -> None:
        """Try to open a client on a command that does not exist."""
        async with McpSearchClient(stdio_server("no-such-mcp-server-command", tmp_path)):
            pass

    with pytest.raises(SearchError, match="MCP server"):
        asyncio.run(connect())


@pytest.mark.parametrize("limit", [0, MAX_SEARCH_LIMIT + 1])
def test_the_fake_refuses_the_limits_the_server_refuses(limit: int) -> None:
    """The fake search client enforces the tool's 1 to 20 limit, like the real server."""
    with pytest.raises(SearchError):
        asyncio.run(FakeSearchClient({}).search("query", limit))
