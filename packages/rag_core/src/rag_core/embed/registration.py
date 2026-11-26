"""Registering the embedding model the application runs, and choosing the first current one."""

from rag_core.store.embedders.protocol import EmbedderInfo, EmbedderRegistryProtocol


def register_embedder(registry: EmbedderRegistryProtocol, info: EmbedderInfo) -> bool:
    """Register ``info`` and make it current if no model is current yet; return whether it did.

    Registering is idempotent, so this is safe on every run. A model that is already current
    stays current, so registering a second model for a comparison never changes the default.
    Raises ``EmbedderConflictError`` if the model is registered with another dimension.
    """
    registry.register(info.model_id, info.dimension)
    if registry.get_current() is not None:
        return False
    registry.set_current(info.model_id)
    return True
