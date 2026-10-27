"""Errors raised through ``StoreProtocol``.

Both implementations raise these instead of driver exceptions, so callers handle one set of
failures whichever store is behind the protocol (ADR 0006).
"""


class StoreError(Exception):
    """Base class for every error the store raises on purpose."""


class MissingDocumentError(StoreError):
    """A chunk references a ``document_id`` that has no document."""


class EmbedderNotFoundError(StoreError):
    """The named embedder is not registered, or no embedder is current."""


class EmbedderConflictError(StoreError):
    """An embedder was re-registered with a dimension different from its registered one."""


class EmbeddingDimensionError(StoreError):
    """An embedding's length differs from the current embedder's dimension."""
