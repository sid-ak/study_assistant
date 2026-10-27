"""Store package: the ``StoreProtocol`` seam and its DB-backed implementation, ``Store``.

Each store is bound to one ``EmbedderInfo``. The registry of embedding models lives in
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
