"""The MCP server: exposes ``rag_core``'s retrieval to agents as one ``search`` tool.

The server is a thin adapter. It validates the tool's arguments, calls ``rag_core``'s ``retrieve``,
and reshapes each ranked chunk into a plain record an agent can cite. It holds no retrieval logic of
its own, so every consumer of retrieval gets the same behavior.
"""

from typing import TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from rag_core.config import Settings
from rag_core.embed import EmbedderProtocol, FastembedEmbedder
from rag_core.ingest.chunking import BREADCRUMB_SEPARATOR
from rag_core.rerank import RerankerProtocol, build_reranker
from rag_core.retrieve import RetrievedChunk, retrieve
from rag_core.store import Store, StoreProtocol

# The name the server reports to clients when they connect.
SERVER_NAME = "study-assistant"

# Results one search may return. A small cap keeps a tool result well inside a model's context.
MAX_SEARCH_LIMIT = 20
# Results returned when the caller does not say how many.
DEFAULT_SEARCH_LIMIT = 5
# Dense-search candidates a reranking server rescores per search.
DEFAULT_CANDIDATES = 20


class SearchHit(TypedDict):
    """One ranked chunk as the ``search`` tool returns it."""

    id: str
    document: str
    section: str
    content: str
    distance: float
    relevance: float


class SearchTool:
    """The ``search`` tool, bound to the embedder and store it searches with."""

    def __init__(
        self,
        embedder: EmbedderProtocol,
        store: StoreProtocol,
        reranker: RerankerProtocol | None = None,
        candidates: int = DEFAULT_CANDIDATES,
    ) -> None:
        """Search ``store`` with ``embedder``; with a ``reranker``, rescore ``candidates`` hits."""
        self.embedder = embedder
        self.store = store
        self.reranker = reranker
        self.candidates = candidates

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[SearchHit]:
        """Return the stored chunks nearest to ``query``, nearest first.

        Each hit has the chunk's id, its source document, its heading path, its text, its cosine
        distance to the query (0 is identical, 2 is opposite), and its relevance: the reranker's
        score from 0 to 1 when the server reranks, otherwise the cosine similarity, 1 minus the
        distance. Hits are ordered by relevance. ``limit`` is 1 to 20.
        """
        # ToolError is the SDK's anticipated failure: its message reaches the client. Any other
        # exception is treated as a crash, and the client sees only a generic message.
        if not query.strip():
            raise ToolError("query must contain text.")
        if limit < 1 or limit > MAX_SEARCH_LIMIT:
            raise ToolError(f"limit must be 1 to {MAX_SEARCH_LIMIT}, not {limit}.")
        result = retrieve(
            query,
            embedder=self.embedder,
            store=self.store,
            limit=limit,
            reranker=self.reranker,
            candidates=self.candidates,
        )
        return [hit_from_chunk(chunk) for chunk in result.chunks]


def hit_from_chunk(chunk: RetrievedChunk) -> SearchHit:
    """Reshape a retrieved chunk into a ``SearchHit``."""
    return SearchHit(
        id=str(chunk.id),
        document=chunk.metadata["source"],
        section=BREADCRUMB_SEPARATOR.join(chunk.metadata["headings"]),
        content=chunk.content,
        distance=chunk.distance,
        relevance=chunk.relevance,
    )


def build_server(
    *,
    embedder: EmbedderProtocol,
    store: StoreProtocol,
    reranker: RerankerProtocol | None = None,
    candidates: int = DEFAULT_CANDIDATES,
) -> MCPServer:
    """An MCP server offering the ``search`` tool over ``embedder`` and ``store``.

    With a ``reranker``, every search reranks ``candidates`` dense results.
    """
    server = MCPServer(SERVER_NAME)
    tool = SearchTool(embedder, store, reranker, candidates)
    # The tool's name, description, and argument schema come from the method's signature and
    # docstring.
    server.add_tool(tool.search, name="search")
    return server


def main() -> None:
    """Run the server over stdio with the configured embedder and database.

    The models are loaded before the server starts, so the first search does not pay for them.
    ``RERANK_ENABLED`` decides whether searches are reranked.
    """
    settings = Settings()
    embedder = FastembedEmbedder.from_settings(settings)
    embedder.load()
    reranker = build_reranker(settings)
    if reranker is not None:
        reranker.score("warm up", ["warm up"])
    store = Store(settings.database_url, embedder=embedder.info)
    server = build_server(
        embedder=embedder,
        store=store,
        reranker=reranker,
        candidates=settings.rerank_candidates,
    )
    # stdio: the client starts this process and speaks MCP over its standard input and output.
    server.run("stdio")
