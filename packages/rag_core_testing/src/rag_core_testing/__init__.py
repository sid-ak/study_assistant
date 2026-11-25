"""Test doubles and test data for code that depends on ``rag_core``.

A dev-only workspace package: test suites in any workspace member import it, and no runtime code
does. It holds in-memory fakes of ``rag_core``'s protocols, so unit tests run without a database,
and small builders for valid test data.
"""

from rag_core_testing.embedders import InMemoryEmbedderRegistry
from rag_core_testing.factories import EMBEDDER_A, EMBEDDER_B, make_chunk
from rag_core_testing.store import InMemoryStore

__all__ = [
    "EMBEDDER_A",
    "EMBEDDER_B",
    "InMemoryEmbedderRegistry",
    "InMemoryStore",
    "make_chunk",
]
