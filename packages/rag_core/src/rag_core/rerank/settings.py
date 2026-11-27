"""Building the configured reranker, or none, from the settings."""

from rag_core.config import Settings
from rag_core.rerank.fastembed_reranker import FastembedReranker
from rag_core.rerank.protocol import RerankerProtocol


def build_reranker(settings: Settings) -> RerankerProtocol | None:
    """The configured reranker when ``RERANK_ENABLED`` is on, otherwise ``None``.

    The reranker loads its model on first use, so building it here costs nothing.
    """
    if not settings.rerank_enabled:
        return None
    return FastembedReranker.from_settings(settings)
