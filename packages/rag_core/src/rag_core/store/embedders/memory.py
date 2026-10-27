"""In-memory ``EmbedderRegistryProtocol`` implementation for unit tests."""

from rag_core.store.embedders.protocol import EmbedderInfo
from rag_core.store.errors import EmbedderConflictError, EmbedderNotFoundError
from rag_core.store.schema import embedding_column


class InMemoryEmbedderRegistry:
    """Dict-backed fake conforming to ``EmbedderRegistryProtocol``.

    It refuses the same id collisions as the DB registry, whose per-model columns are named by
    ``embedding_column``.
    """

    def __init__(self) -> None:
        """Start with no registered embedders and none current."""
        self.embedders: dict[str, EmbedderInfo] = {}
        self.current_model_id: str | None = None

    def register(self, model_id: str, dimension: int) -> None:
        """Register a model, refusing a changed dimension or an id that collides with another."""
        registered = self.embedders.get(model_id)
        if registered is not None:
            if registered.dimension != dimension:
                raise EmbedderConflictError(
                    f"{model_id!r} is registered with dimension {registered.dimension}, "
                    f"not {dimension}."
                )
            return
        column = embedding_column(model_id)
        if any(embedding_column(other) == column for other in self.embedders):
            raise EmbedderConflictError(
                f"Column {column!r} for {model_id!r} already belongs to another embedder."
            )
        self.embedders[model_id] = EmbedderInfo(model_id, dimension)

    def set_current(self, model_id: str) -> None:
        """Make ``model_id`` current; raises ``EmbedderNotFoundError`` if it is not registered."""
        if model_id not in self.embedders:
            raise EmbedderNotFoundError(f"Embedder {model_id!r} is not registered.")
        self.current_model_id = model_id

    def get_current(self) -> EmbedderInfo | None:
        """Return the current embedder, or ``None`` if none has been set."""
        if self.current_model_id is None:
            return None
        return self.embedders[self.current_model_id]
