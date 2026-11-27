"""The client the agent uses to reach retrieval through the MCP server."""

from api.mcp_client.client import (
    McpSearchClient,
    SearchClientProtocol,
    SearchError,
    SearchHit,
    server_environment,
    stdio_server,
)

__all__ = [
    "McpSearchClient",
    "SearchClientProtocol",
    "SearchError",
    "SearchHit",
    "server_environment",
    "stdio_server",
]
