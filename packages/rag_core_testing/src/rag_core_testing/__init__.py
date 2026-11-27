"""Test doubles and test data for code that depends on ``rag_core``.

A dev-only workspace package: test suites in any workspace member import it, and no runtime code
does. It holds fakes of ``rag_core``'s protocols, so unit tests run without a database or a model,
and small builders for valid test data.
"""

from rag_core_testing.embedders import InMemoryEmbedderRegistry
from rag_core_testing.embedding import HashingEmbedder
from rag_core_testing.factories import EMBEDDER_A, EMBEDDER_B, HASHING_EMBEDDER, make_chunk
from rag_core_testing.reranking import OverlapReranker
from rag_core_testing.store import InMemoryStore

__all__ = [
    "EMBEDDER_A",
    "EMBEDDER_B",
    "HASHING_EMBEDDER",
    "HashingEmbedder",
    "InMemoryEmbedderRegistry",
    "InMemoryStore",
    "OverlapReranker",
    "make_chunk",
]
