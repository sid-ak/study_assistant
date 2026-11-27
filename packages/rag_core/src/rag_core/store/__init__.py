"""Store package: the ``StoreProtocol`` seam and its DB-backed implementation, ``Store``.

Each store is bound to one ``EmbedderInfo``. The registry of embedding models lives in
``rag_core.store.embedders``.
"""

from rag_core.store.client import Store
from rag_core.store.errors import (
    DuplicateIdError,
    EmbedderConflictError,
    EmbedderNotFoundError,
    EmbeddingDimensionError,
    MissingChunkError,
    MissingDocumentError,
    StoreError,
    UnsupportedDimensionError,
    ZeroEmbeddingError,
)
from rag_core.store.protocol import StoreProtocol

__all__ = [
    "DuplicateIdError",
    "EmbedderConflictError",
    "EmbedderNotFoundError",
    "EmbeddingDimensionError",
    "MissingChunkError",
    "MissingDocumentError",
    "Store",
    "StoreError",
    "StoreProtocol",
    "UnsupportedDimensionError",
    "ZeroEmbeddingError",
]
