"""Behavior of the MCP server's ``search`` tool, called through a real MCP client in-process.

``mcp.Client`` connects to a server object directly, so each call goes through the MCP protocol
(tool listing, argument validation, structured results) without a subprocess, a model, or a
database: the server is built over the hashing embedder and the in-memory store.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from mcp_server.server import MAX_SEARCH_LIMIT, build_server
from rag_core.ingest import ingest_folder
from rag_core_testing import HASHING_EMBEDDER, HashingEmbedder, InMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> InMemoryStore:
    """An in-memory store holding three small documents embedded by the hashing embedder."""
    (tmp_path / "ci").mkdir()
    (tmp_path / "build.md").write_text("# Build\n\n## Caching\n\nccache stores compiled objects.\n")
    (tmp_path / "ci" / "pthread.md").write_text(
        "# Failure\n\n## Cause\n\nlibpthread was not linked on the oldest image.\n"
    )
    (tmp_path / "release.md").write_text("# Release\n\nOrbit 5.0 removes the workers flag.\n")
    store = InMemoryStore(embedder=HASHING_EMBEDDER)
    ingest_folder(tmp_path, store=store, embedder=HashingEmbedder())
    return store


async def list_tool_names(store: InMemoryStore) -> list[str]:
    """The names of the tools the server lists."""
    async with Client(build_server(embedder=HashingEmbedder(), store=store)) as client:
        listing = await client.list_tools()
    names = []
    for tool in listing.tools:
        names.append(tool.name)
    return names


async def call_search(store: InMemoryStore, arguments: dict[str, Any]) -> Any:
    """Call the ``search`` tool with ``arguments`` and return the raw tool result."""
    async with Client(build_server(embedder=HashingEmbedder(), store=store)) as client:
        return await client.call_tool("search", arguments)


def test_the_server_offers_exactly_one_search_tool(store: InMemoryStore) -> None:
    """The agent sees one tool, so retrieval has exactly one entry point."""
    assert asyncio.run(list_tool_names(store)) == ["search"]


def test_search_returns_the_nearest_chunks_with_their_location(store: InMemoryStore) -> None:
    """Each hit carries the chunk id, document, heading path, text, and distance, nearest first."""
    result = asyncio.run(call_search(store, {"query": "ccache compiled objects", "limit": 3}))

    assert result.is_error is False
    hits = result.structured_content["result"]
    assert len(hits) == 3
    first = hits[0]
    assert first["document"] == "build.md"
    assert first["section"] == "Build > Caching"
    assert "ccache stores compiled objects." in first["content"]
    assert set(first) == {"id", "document", "section", "content", "distance"}
    distances = [hit["distance"] for hit in hits]
    assert distances == sorted(distances)


def test_search_ids_are_the_stored_chunk_ids(store: InMemoryStore) -> None:
    """A hit's id is the stored chunk's id, so a citation can be traced back to the chunk."""
    result = asyncio.run(call_search(store, {"query": "libpthread oldest image", "limit": 1}))

    [hit] = result.structured_content["result"]
    stored_ids = set()
    for chunk in store.chunks.values():
        stored_ids.add(str(chunk["id"]))
    assert hit["id"] in stored_ids


def test_search_defaults_to_five_results(store: InMemoryStore) -> None:
    """Without a limit, the tool asks for five chunks; this store holds only three."""
    result = asyncio.run(call_search(store, {"query": "orbit workers flag"}))

    assert len(result.structured_content["result"]) == 3


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "ccache", "limit": 0},
        {"query": "ccache", "limit": MAX_SEARCH_LIMIT + 1},
        {"query": "   "},
        {"limit": 3},
    ],
    ids=["limit below one", "limit above the maximum", "blank query", "missing query"],
)
def test_search_reports_invalid_arguments_as_a_tool_error(
    store: InMemoryStore, arguments: dict[str, Any]
) -> None:
    """Bad arguments come back as an error result the agent can read, not a crashed server."""
    result = asyncio.run(call_search(store, arguments))

    assert result.is_error is True
