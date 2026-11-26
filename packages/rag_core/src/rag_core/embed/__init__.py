"""Embedding: the ``EmbedderProtocol`` interface and its ``fastembed`` implementation.

An embedder turns text into fixed-length vectors. Its ``info`` names the model and dimension, which
is what a store is bound to, so vectors always land in the column of the model that made them.
"""

from rag_core.embed.fastembed_embedder import FastembedEmbedder
from rag_core.embed.protocol import EmbedderProtocol

__all__ = ["EmbedderProtocol", "FastembedEmbedder"]
