"""Test data shared by the store test modules: the embedder fixtures' models and a chunk builder."""

import uuid
from typing import Any
from uuid import UUID

from rag_core.store.embedders import EmbedderInfo

# Small dimensions keep the test vectors cheap; nothing in the store depends on a production size.
EMBEDDER_A = EmbedderInfo(model_id="test/embedder-a", dimension=8)
EMBEDDER_B = EmbedderInfo(model_id="test/embedder-b", dimension=4)


def make_chunk(document_id: UUID, dimension: int, **overrides: Any) -> dict[str, Any]:
    """A valid ``add_chunks`` row for ``document_id``, with any field replaced by ``overrides``."""
    chunk: dict[str, Any] = {
        "id": uuid.uuid4(),
        "document_id": document_id,
        "content": "chunk",
        "metadata": {},
        "embedding": [0.5] * dimension,
    }
    chunk.update(overrides)
    return chunk
