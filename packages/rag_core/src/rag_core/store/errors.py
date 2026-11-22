"""Errors raised through ``StoreProtocol``.

Every implementation raises these instead of its backend's own exceptions, so callers handle one
set of failures whichever store is behind the protocol.
"""


class StoreError(Exception):
    """Base class for every error the store raises on purpose."""


class MissingDocumentError(StoreError):
    """A chunk references a ``document_id`` that has no document."""


class EmbedderNotFoundError(StoreError):
    """The named embedder is not registered."""


class EmbedderConflictError(StoreError):
    """An embedder was re-registered with a dimension different from its registered one."""


class EmbeddingDimensionError(StoreError):
    """An embedding's length differs from the dimension of the store's embedder."""


class DuplicateIdError(StoreError):
    """An id is already taken by another document or chunk, or repeats within one batch."""


class UnsupportedDimensionError(StoreError):
    """An embedder's dimension is outside the range the store can store and index."""
