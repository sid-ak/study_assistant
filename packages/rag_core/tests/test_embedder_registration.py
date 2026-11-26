"""Behavior of ``register_embedder``: registering a model and making the first one current.

Runs against both registry backends through the ``embedder_registry`` fixture.
"""

import pytest

from rag_core.embed import register_embedder
from rag_core.store import EmbedderConflictError
from rag_core.store.embedders import EmbedderInfo, EmbedderRegistryProtocol
from rag_core_testing import EMBEDDER_A, EMBEDDER_B


def test_the_first_model_registered_becomes_current(
    embedder_registry: EmbedderRegistryProtocol,
) -> None:
    """With no current model, the registered one becomes current and the call reports it."""
    became_current = register_embedder(embedder_registry, EMBEDDER_A)
    assert became_current is True
    assert embedder_registry.get_current() == EMBEDDER_A


def test_registering_again_changes_nothing(embedder_registry: EmbedderRegistryProtocol) -> None:
    """A second call for the current model is a no-op that reports no change."""
    register_embedder(embedder_registry, EMBEDDER_A)
    became_current = register_embedder(embedder_registry, EMBEDDER_A)
    assert became_current is False
    assert embedder_registry.get_current() == EMBEDDER_A


def test_another_current_model_stays_current(embedder_registry: EmbedderRegistryProtocol) -> None:
    """A later model is registered but does not replace the current one."""
    register_embedder(embedder_registry, EMBEDDER_A)
    became_current = register_embedder(embedder_registry, EMBEDDER_B)
    assert became_current is False
    assert embedder_registry.get_current() == EMBEDDER_A
    # Registered: making it current now succeeds instead of raising EmbedderNotFoundError.
    embedder_registry.set_current(EMBEDDER_B.model_id)
    assert embedder_registry.get_current() == EMBEDDER_B


def test_a_changed_dimension_is_refused(embedder_registry: EmbedderRegistryProtocol) -> None:
    """Re-registering a model with another dimension raises and leaves the registry unchanged."""
    register_embedder(embedder_registry, EMBEDDER_A)
    changed = EmbedderInfo(model_id=EMBEDDER_A.model_id, dimension=EMBEDDER_A.dimension + 1)
    with pytest.raises(EmbedderConflictError):
        register_embedder(embedder_registry, changed)
    assert embedder_registry.get_current() == EMBEDDER_A
