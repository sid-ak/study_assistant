"""``OverlapReranker``: a deterministic, model-free fake of ``RerankerProtocol``."""

from rag_core_testing.embedding import WORD_PATTERN


def words(text: str) -> set[str]:
    """The distinct words of ``text``, lowercased."""
    return set(WORD_PATTERN.findall(text.lower()))


class OverlapReranker:
    """Scores a passage by the share of the query's distinct words it contains.

    A passage containing every query word scores 1, and one containing none scores 0, so tests can
    predict the order without a model.
    """

    @property
    def model_id(self) -> str:
        """The fake model's name."""
        return "test/overlap-reranker"

    def score(self, query: str, documents: list[str]) -> list[float]:
        """The share of the query's distinct words found in each document."""
        query_words = words(query)
        scores: list[float] = []
        for document in documents:
            if not query_words:
                scores.append(0.0)
                continue
            shared = query_words & words(document)
            scores.append(len(shared) / len(query_words))
        return scores
