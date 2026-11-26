"""``FastembedEmbedder``: an ``EmbedderProtocol`` implementation running on ``fastembed``.

``fastembed`` runs quantized embedding models on ONNX Runtime, with no PyTorch. It downloads a
model's files on first use into its cache folder, which the ``FASTEMBED_CACHE_PATH`` environment
variable can move; by default it is ``fastembed_cache`` under the system temporary folder.
"""

from fastembed import TextEmbedding

from rag_core.config import Settings
from rag_core.store.embedders.protocol import EmbedderInfo

# Texts embedded per model call. Small batches keep peak memory low on an 8 GB machine.
BATCH_SIZE = 32


def supported_dimension(model_id: str) -> int | None:
    """Return the vector dimension fastembed lists for ``model_id``, or ``None`` if it has none.

    The list ships with the library, so this check needs no network and no model files.
    """
    for description in TextEmbedding.list_supported_models():
        if description["model"] == model_id:
            dimension: int = description["dim"]
            return dimension
    return None


class FastembedEmbedder:
    """Embedder backed by a ``fastembed`` ONNX model, loaded on first use.

    Building one checks the model id and dimension and loads nothing. The model's files are
    downloaded, if needed, and loaded into memory by the first call that embeds text.
    """

    def __init__(self, model_id: str, dimension: int, query_prefix: str = "") -> None:
        """Check ``model_id`` and ``dimension`` against fastembed's model list; load nothing.

        Raises ``ValueError`` if fastembed does not provide ``model_id`` or if ``dimension`` is
        not the model's own. ``query_prefix`` is put in front of every query before embedding.
        """
        model_dimension = supported_dimension(model_id)
        if model_dimension is None:
            raise ValueError(f"fastembed does not provide the embedding model {model_id!r}.")
        if model_dimension != dimension:
            raise ValueError(
                f"{model_id!r} produces {model_dimension}-dimension vectors, not {dimension}."
            )
        self._info = EmbedderInfo(model_id=model_id, dimension=dimension)
        self.query_prefix = query_prefix
        self._model: TextEmbedding | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "FastembedEmbedder":
        """Build the embedder that ``settings`` configures."""
        return cls(
            model_id=settings.embedding_model,
            dimension=settings.embedding_dimension,
            query_prefix=settings.embedding_query_prefix,
        )

    @property
    def info(self) -> EmbedderInfo:
        """The model id and vector dimension."""
        return self._info

    @property
    def is_loaded(self) -> bool:
        """Whether the model has been loaded into memory yet."""
        return self._model is not None

    def load(self) -> TextEmbedding:
        """Return the model, downloading and loading it the first time it is needed."""
        if self._model is None:
            self._model = TextEmbedding(model_name=self._info.model_id)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages, returning one unit-length vector per text, in order.

        Inputs longer than the model's limit (512 tokens for the bge models) are truncated.
        """
        if not texts:
            return []
        model = self.load()
        vectors: list[list[float]] = []
        for vector in model.embed(texts, batch_size=BATCH_SIZE):
            vectors.append(vector.tolist())
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed ``query_prefix`` followed by ``text``."""
        return self.embed_documents([self.query_prefix + text])[0]
