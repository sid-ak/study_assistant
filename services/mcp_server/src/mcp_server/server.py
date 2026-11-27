"""The MCP server: exposes ``rag_core``'s retrieval to agents as one ``search`` tool.

The server is a thin adapter. It validates the tool's arguments, calls ``rag_core``'s ``retrieve``,
and reshapes each ranked chunk into a plain record an agent can cite. It holds no retrieval logic of
its own, so every consumer of retrieval gets the same behavior.
"""

from typing import TypedDict

from mcp.server.mcpserver import MCPServer

from rag_core.config import Settings
from rag_core.embed import EmbedderProtocol, FastembedEmbedder
from rag_core.ingest.chunking import BREADCRUMB_SEPARATOR
from rag_core.retrieve import RetrievedChunk, retrieve
from rag_core.store import Store, StoreProtocol

# The name the server reports to clients when they connect.
SERVER_NAME = "study-assistant"

# Results one search may return. A small cap keeps a tool result well inside a model's context.
MAX_SEARCH_LIMIT = 20
# Results returned when the caller does not say how many.
DEFAULT_SEARCH_LIMIT = 5


class SearchHit(TypedDict):
    """One ranked chunk as the ``search`` tool returns it."""

    id: str
    document: str
    section: str
    content: str
    distance: float


class SearchTool:
    """The ``search`` tool, bound to the embedder and store it searches with."""

    def __init__(self, embedder: EmbedderProtocol, store: StoreProtocol) -> None:
        """Search ``store`` with queries embedded by ``embedder``."""
        self.embedder = embedder
        self.store = store

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[SearchHit]:
        """Return the stored chunks nearest to ``query``, nearest first.

        Each hit has the chunk's id, its source document, its heading path, its text, and its
        cosine distance to the query (0 is identical, 2 is opposite). ``limit`` is 1 to 20.
        """
        if not query.strip():
            raise ValueError("query must contain text.")
        if limit < 1 or limit > MAX_SEARCH_LIMIT:
            raise ValueError(f"limit must be 1 to {MAX_SEARCH_LIMIT}, not {limit}.")
        result = retrieve(query, embedder=self.embedder, store=self.store, limit=limit)
        return [hit_from_chunk(chunk) for chunk in result.chunks]


def hit_from_chunk(chunk: RetrievedChunk) -> SearchHit:
    """Reshape a retrieved chunk into a ``SearchHit``."""
    return SearchHit(
        id=str(chunk.id),
        document=chunk.metadata["source"],
        section=BREADCRUMB_SEPARATOR.join(chunk.metadata["headings"]),
        content=chunk.content,
        distance=chunk.distance,
    )


def build_server(*, embedder: EmbedderProtocol, store: StoreProtocol) -> MCPServer:
    """An MCP server offering the ``search`` tool over ``embedder`` and ``store``."""
    server = MCPServer(SERVER_NAME)
    tool = SearchTool(embedder, store)
    # The tool's name, description, and argument schema come from the method's signature and
    # docstring; a ValueError it raises reaches the client as an error result.
    server.add_tool(tool.search, name="search")
    return server


def main() -> None:
    """Run the server over stdio with the configured embedder and database.

    The model is loaded before the server starts, so the first search does not pay for it.
    """
    settings = Settings()
    embedder = FastembedEmbedder.from_settings(settings)
    embedder.load()
    store = Store(settings.database_url, embedder=embedder.info)
    # stdio: the client starts this process and speaks MCP over its standard input and output.
    build_server(embedder=embedder, store=store).run("stdio")
