"""Store package: the ``StoreProtocol`` seam plus its DB-backed and in-memory implementations."""

from rag_core.store.client import Store
from rag_core.store.errors import (
    EmbedderConflictError,
    EmbedderNotFoundError,
    EmbeddingDimensionError,
    MissingDocumentError,
    StoreError,
)
from rag_core.store.memory import InMemoryStore
from rag_core.store.protocol import EmbedderInfo, StoreProtocol

__all__ = [
    "EmbedderConflictError",
    "EmbedderInfo",
    "EmbedderNotFoundError",
    "EmbeddingDimensionError",
    "InMemoryStore",
    "MissingDocumentError",
    "Store",
    "StoreError",
    "StoreProtocol",
]
