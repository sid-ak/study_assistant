"""``HashingEmbedder``: a deterministic, model-free fake of ``EmbedderProtocol``."""

import hashlib
import math
import re

from rag_core.store.embedders import EmbedderInfo
from rag_core_testing.factories import HASHING_EMBEDDER

# A word is a run of lowercase letters and digits.
WORD_PATTERN = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Fake embedder that hashes words into buckets, so texts sharing words score as similar.

    Each word adds one to the bucket its hash picks, and the counts are scaled to length 1. It
    loads no model and gives the same vector for the same text on every run, so tests that rank
    real text stay fast and repeatable. Queries and documents are embedded the same way.
    """

    def __init__(self, info: EmbedderInfo = HASHING_EMBEDDER) -> None:
        """Produce vectors for the model and dimension in ``info``."""
        self.info = info

    def embed_text(self, text: str) -> list[float]:
        """Embed one text as a normalized bag of hashed words."""
        vector = [0.0] * self.info.dimension
        for word in WORD_PATTERN.findall(text.lower()):
            # A hashlib digest is the same on every run, unlike the built-in hash().
            digest = hashlib.blake2b(word.encode("utf-8"), digest_size=4).digest()
            bucket = int.from_bytes(digest, "big") % self.info.dimension
            vector[bucket] += 1.0
        squares = 0.0
        for value in vector:
            squares += value * value
        length = math.sqrt(squares)
        if length == 0.0:
            # No words at all: return a fixed unit vector so the length is still 1.
            vector[0] = 1.0
            return vector
        return [value / length for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed each text as a normalized bag of hashed words."""
        return [self.embed_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embed a query exactly as a document."""
        return self.embed_text(text)
