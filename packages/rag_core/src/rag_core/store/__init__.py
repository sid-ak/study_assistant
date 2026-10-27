"""Store package: the ``StoreProtocol`` seam and its DB-backed implementation, ``Store``.

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
from rag_core.store.protocol import StoreProtocol

__all__ = [
    "EmbedderConflictError",
    "EmbedderNotFoundError",
    "EmbeddingDimensionError",
    "MissingDocumentError",
    "Store",
    "StoreError",
    "StoreProtocol",
]
