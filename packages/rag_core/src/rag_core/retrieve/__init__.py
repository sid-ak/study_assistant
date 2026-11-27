"""Retrieval: the one entry point the CLI, the eval harness, and the MCP server search through.

``retrieve`` embeds a query and ranks stored chunks against it, returning them with their distances
and the time the whole search took.
"""

from rag_core.retrieve.dense import RetrievalResult, RetrievedChunk, rerank, retrieve, search

__all__ = ["RetrievalResult", "RetrievedChunk", "rerank", "retrieve", "search"]
