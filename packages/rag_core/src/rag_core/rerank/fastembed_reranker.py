"""``FastembedReranker``: a ``RerankerProtocol`` running a cross-encoder on fastembed.

A cross-encoder reads the query and one passage together and outputs a single relevance logit.
fastembed runs it on ONNX Runtime, with no PyTorch, and downloads its files on first use into the
same cache as the embedding models.
"""

import math

from fastembed.rerank.cross_encoder import TextCrossEncoder

from rag_core.config import Settings


def is_supported(model_id: str) -> bool:
    """Whether fastembed lists ``model_id`` as a cross-encoder; needs no network or files."""
    for description in TextCrossEncoder.list_supported_models():
        if description["model"] == model_id:
            return True
    return False


def sigmoid(logit: float) -> float:
    """Map a logit, any real number, to a probability between 0 and 1."""
    return 1.0 / (1.0 + math.exp(-logit))


class FastembedReranker:
    """Reranker backed by a fastembed cross-encoder, loaded on first use."""

    def __init__(self, model_id: str) -> None:
        """Check ``model_id`` against fastembed's cross-encoder list; load nothing.

        Raises ``ValueError`` if fastembed does not provide ``model_id``.
        """
        if not is_supported(model_id):
            raise ValueError(f"fastembed has no cross-encoder named {model_id!r}.")
        self._model_id = model_id
        self._model: TextCrossEncoder | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "FastembedReranker":
        """A reranker for the configured ``RERANKER_MODEL``."""
        return cls(settings.reranker_model)

    @property
    def model_id(self) -> str:
        """The cross-encoder that produces the scores."""
        return self._model_id

    @property
    def is_loaded(self) -> bool:
        """Whether the model has been loaded into memory."""
        return self._model is not None

    def load(self) -> TextCrossEncoder:
        """Load the model, downloading it if needed, and return it; later calls reuse it."""
        if self._model is None:
            self._model = TextCrossEncoder(self._model_id)
        return self._model

    def score(self, query: str, documents: list[str]) -> list[float]:
        """The sigmoid of the cross-encoder's logit for each document, from 0 to 1.

        The model outputs a logit per pair, unbounded in either direction; the sigmoid turns it into
        a probability of relevance, so a threshold means the same thing for any cross-encoder.
        """
        if not documents:
            return []
        scores: list[float] = []
        for logit in self.load().rerank(query, documents):
            scores.append(sigmoid(float(logit)))
        return scores
