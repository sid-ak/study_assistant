"""Embedder registry: which embedding models exist, their dimensions, and which one is current.

Kept apart from the document and chunk storage in ``rag_core.store``: a store is bound to one
``EmbedderInfo`` and never touches the registry (ADR 0006, ADR 0008).
"""

from rag_core.store.embedders.client import EmbedderRegistry
from rag_core.store.embedders.protocol import EmbedderInfo, EmbedderRegistryProtocol

__all__ = [
    "EmbedderInfo",
    "EmbedderRegistry",
    "EmbedderRegistryProtocol",
]
