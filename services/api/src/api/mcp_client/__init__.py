"""The client the agent uses to reach retrieval through the MCP server."""

from api.mcp_client.client import (
    MAX_SEARCH_LIMIT,
    McpSearchClient,
    SearchClientProtocol,
    SearchError,
    SearchHit,
    server_environment,
    stdio_server,
)

__all__ = [
    "MAX_SEARCH_LIMIT",
    "McpSearchClient",
    "SearchClientProtocol",
    "SearchError",
    "SearchHit",
    "server_environment",
    "stdio_server",
]
