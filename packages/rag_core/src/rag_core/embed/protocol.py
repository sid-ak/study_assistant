"""The embedder interface.

``EmbedderProtocol`` is the structural contract ingestion and retrieval depend on, so they never
bind to a particular model or runtime. Implementations conform by shape.
"""

from typing import Protocol, runtime_checkable

from rag_core.store.embedders.protocol import EmbedderInfo


@runtime_checkable
class EmbedderProtocol(Protocol):
    """Structural interface for turning text into unit-length vectors."""

    @property
    def info(self) -> EmbedderInfo:
        """The model id and vector dimension; a store bound to this ``info`` holds its vectors."""
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages for storage, returning one vector per text, in order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query, which may be encoded differently from a stored passage."""
        ...
