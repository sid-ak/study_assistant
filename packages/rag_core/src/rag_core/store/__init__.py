"""Store package: the ``StoreProtocol`` seam plus its DB-backed and in-memory implementations.

The embedder registry the stores read the current embedder from lives in
``rag_core.store.embedders``.
"""

from rag_core.store.client import Store
from rag_core.store.errors import (
    EmbedderConflictError,
    EmbedderNotFoundError,
    EmbeddingDimensionError,
    MissingDocumentError,
    StoreError,
)
from rag_core.store.memory import InMemoryStore
from rag_core.store.protocol import StoreProtocol

__all__ = [
    "EmbedderConflictError",
    "EmbedderNotFoundError",
    "EmbeddingDimensionError",
    "InMemoryStore",
    "MissingDocumentError",
    "Store",
    "StoreError",
    "StoreProtocol",
]
