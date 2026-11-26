"""The check that an embedder and a store agree on the model whose vectors they handle."""

from rag_core.embed.protocol import EmbedderProtocol
from rag_core.store.protocol import StoreProtocol


def check_same_model(embedder: EmbedderProtocol, store: StoreProtocol) -> None:
    """Raise ``ValueError`` unless ``store`` is bound to the model ``embedder`` runs.

    Vectors from two models live in unrelated spaces, so writing or searching one model's vectors
    in another model's column would give meaningless distances.
    """
    if embedder.info != store.embedder:
        raise ValueError(
            f"The embedder is {embedder.info.model_id!r} but the store holds vectors for "
            f"{store.embedder.model_id!r}; bind the store with store.with_embedder(embedder.info)."
        )
