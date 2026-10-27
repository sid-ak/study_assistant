"""Shared behavior contract for the embedder registry seam (ADR 0008).

Every test takes ``embedder_registry: EmbedderRegistryProtocol`` (parametrized in ``conftest.py``)
and runs against every implementation, labeled ``[memory]`` / ``[db]``. What only the DB registry
does, adding per-model columns and indexes, lives in ``test_db_embedder_registry.py``.
"""

import pytest
from support import EMBEDDER_A, EMBEDDER_B

from rag_core.store import EmbedderConflictError, EmbedderNotFoundError
from rag_core.store.embedders import (
    EmbedderRegistry,
    EmbedderRegistryProtocol,
    InMemoryEmbedderRegistry,
)


def test_current_is_none_until_set(embedder_registry: EmbedderRegistryProtocol) -> None:
    """A fresh registry has no current embedder, and registering one does not make it current."""
    assert embedder_registry.get_current() is None
    embedder_registry.register(EMBEDDER_A.model_id, EMBEDDER_A.dimension)
    assert embedder_registry.get_current() is None


def test_set_current_reports_model_and_dimension(
    embedder_registry: EmbedderRegistryProtocol,
) -> None:
    """The current embedder reads back with the dimension it was registered with."""
    embedder_registry.register(EMBEDDER_A.model_id, EMBEDDER_A.dimension)
    embedder_registry.set_current(EMBEDDER_A.model_id)
    assert embedder_registry.get_current() == EMBEDDER_A


def test_register_is_idempotent(embedder_registry: EmbedderRegistryProtocol) -> None:
    """Registering the same model with the same dimension twice is a no-op."""
    embedder_registry.register(EMBEDDER_A.model_id, EMBEDDER_A.dimension)
    embedder_registry.register(EMBEDDER_A.model_id, EMBEDDER_A.dimension)
    embedder_registry.set_current(EMBEDDER_A.model_id)
    assert embedder_registry.get_current() == EMBEDDER_A


def test_register_rejects_a_changed_dimension(embedder_registry: EmbedderRegistryProtocol) -> None:
    """A registered model's dimension is fixed; re-registering it with another one is refused."""
    embedder_registry.register(EMBEDDER_A.model_id, EMBEDDER_A.dimension)
    with pytest.raises(EmbedderConflictError):
        embedder_registry.register(EMBEDDER_A.model_id, EMBEDDER_A.dimension + 1)


def test_register_rejects_ids_that_collide(embedder_registry: EmbedderRegistryProtocol) -> None:
    """Two distinct ids that would share one embedding column cannot both be registered."""
    embedder_registry.register("bge-m3", 8)
    with pytest.raises(EmbedderConflictError):
        embedder_registry.register("BGE_M3", 8)


def test_set_current_rejects_unregistered_model(
    embedder_registry: EmbedderRegistryProtocol,
) -> None:
    """Only a registered model can become current."""
    with pytest.raises(EmbedderNotFoundError):
        embedder_registry.set_current("never-registered")


def test_only_one_embedder_is_current(embedder_registry: EmbedderRegistryProtocol) -> None:
    """Setting a new current embedder replaces the previous one."""
    for info in (EMBEDDER_A, EMBEDDER_B):
        embedder_registry.register(info.model_id, info.dimension)
    embedder_registry.set_current(EMBEDDER_A.model_id)
    embedder_registry.set_current(EMBEDDER_B.model_id)
    assert embedder_registry.get_current() == EMBEDDER_B


def test_both_implementations_conform_to_protocol() -> None:
    """Both registries satisfy EmbedderRegistryProtocol, structurally and at runtime."""
    # mypy --strict checks these assignments; the DB registry constructs without connecting.
    fake: EmbedderRegistryProtocol = InMemoryEmbedderRegistry()
    real: EmbedderRegistryProtocol = EmbedderRegistry("postgresql://placeholder")
    assert isinstance(fake, EmbedderRegistryProtocol)
    assert isinstance(real, EmbedderRegistryProtocol)
