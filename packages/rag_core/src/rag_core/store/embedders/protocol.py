"""The embedder registry interface.

``EmbedderRegistryProtocol`` records each embedding model and its fixed vector dimension, and marks
at most one model as current. Stores read the current model to decide where embeddings are written
and read from; ingestion code registers models and switches between them. Implementations conform
by shape; the ones that exist are exported from ``rag_core.store.embedders``.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EmbedderInfo:
    """A registered embedding model: its identifier and the fixed dimension of its vectors."""

    model_id: str
    dimension: int


@runtime_checkable
class EmbedderRegistryProtocol(Protocol):
    """Structural interface for the embedding-model registry, independent of any backend."""

    def register(self, model_id: str, dimension: int) -> None:
        """Idempotently register an embedding model and give it its own vector storage.

        Raises ``EmbedderConflictError`` if ``model_id`` is already registered with another
        dimension, or if it cannot be told apart from an already registered id. Registering does
        not make the model current.
        """
        ...

    def set_current(self, model_id: str) -> None:
        """Make ``model_id`` the one embedder that writes and reads go to.

        Raises ``EmbedderNotFoundError`` if it is not registered.
        """
        ...

    def get_current(self) -> EmbedderInfo | None:
        """Return the current embedder, or ``None`` if none has been set."""
        ...
