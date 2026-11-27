"""Running the golden set through retrieval, and saving the run for later comparison."""

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.agent import AgentEvalRun
from evals.golden import GoldenQuestion
from evals.metrics import percentile, reciprocal_rank, section_recall
from rag_core.embed import EmbedderProtocol
from rag_core.ingest.chunking import BREADCRUMB_SEPARATOR
from rag_core.rerank import RerankerProtocol
from rag_core.retrieve import RetrievalResult, retrieve
from rag_core.store import StoreProtocol

# A run name is used as a file name, so it is limited to characters that cannot leave its folder.
RUN_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


@dataclass(frozen=True)
class RetrievedSection:
    """One retrieved chunk, by document and heading path, with its distance and relevance.

    ``distance`` is ``None`` for a chunk only lexical search found.
    """

    document: str
    section: str
    distance: float | None


@dataclass(frozen=True)
class QuestionResult:
    """How retrieval did on one golden question."""

    id: str
    text: str
    recall: float
    reciprocal_rank: float
    retrieved: list[RetrievedSection]
    latencies_ms: list[float]


@dataclass(frozen=True)
class EvalRun:
    """One evaluation run: its settings, every question's result, and the totals.

    ``recall_at_k`` and ``mrr`` are means over the questions. The latency percentiles are taken
    over every timed retrieval, ``repeats`` per question.
    """

    model_id: str
    dimension: int
    k: int
    ef_search: int | None
    repeats: int
    # The reranker's model and its candidate count, or None for both in a dense-only run.
    reranker: str | None
    candidates: int | None
    # Whether lexical search was fused with dense search.
    hybrid: bool
    recall_at_k: float
    mrr: float
    latency_p50_ms: float
    latency_p95_ms: float
    questions: list[QuestionResult]


@dataclass(frozen=True)
class RetrievalSettings:
    """How every question in a run is retrieved: the components and the search settings."""

    embedder: EmbedderProtocol
    store: StoreProtocol
    k: int
    ef_search: int | None
    reranker: RerankerProtocol | None
    candidates: int
    hybrid: bool


def retrieve_once(text: str, settings: RetrievalSettings) -> RetrievalResult:
    """Retrieve the top ``k`` chunks for ``text`` with the run's settings."""
    return retrieve(
        text,
        embedder=settings.embedder,
        store=settings.store,
        limit=settings.k,
        ef_search=settings.ef_search,
        reranker=settings.reranker,
        candidates=settings.candidates,
        hybrid=settings.hybrid,
    )


def run_eval(
    questions: list[GoldenQuestion],
    *,
    embedder: EmbedderProtocol,
    store: StoreProtocol,
    k: int = 5,
    ef_search: int | None = None,
    repeats: int = 1,
    reranker: RerankerProtocol | None = None,
    candidates: int = 20,
    hybrid: bool = False,
) -> EvalRun:
    """Retrieve the top ``k`` chunks for each question and score them against its labels.

    Each question is retrieved ``repeats`` times and every retrieval is timed. The ranking of the
    first retrieval is the one scored. One untimed retrieval runs first, so loading a model on
    first use is not counted as latency. Raises ``ValueError`` if ``questions`` is empty, ``k`` or
    ``repeats`` is below one, or retrieval rejects ``ef_search``.
    """
    if not questions:
        raise ValueError("The golden set has no questions.")
    if k < 1:
        raise ValueError(f"k must be at least 1, not {k}.")
    if repeats < 1:
        raise ValueError(f"repeats must be at least 1, not {repeats}.")

    if reranker is not None and candidates < k:
        raise ValueError(f"candidates ({candidates}) must be at least k ({k}).")
    settings = RetrievalSettings(
        embedder=embedder,
        store=store,
        k=k,
        ef_search=ef_search,
        reranker=reranker,
        candidates=candidates,
        hybrid=hybrid,
    )

    # Untimed warm-up: an embedder or reranker that loads its model on first use does it here.
    retrieve_once(questions[0].text, settings)

    results: list[QuestionResult] = []
    all_latencies: list[float] = []
    for question in questions:
        attempts: list[RetrievalResult] = []
        for _ in range(repeats):
            attempts.append(retrieve_once(question.text, settings))
        latencies = [attempt.latency_ms for attempt in attempts]
        all_latencies.extend(latencies)

        first = attempts[0]
        ranked = [chunk.metadata for chunk in first.chunks]
        retrieved: list[RetrievedSection] = []
        for chunk in first.chunks:
            retrieved.append(
                RetrievedSection(
                    document=chunk.metadata["source"],
                    section=BREADCRUMB_SEPARATOR.join(chunk.metadata["headings"]),
                    distance=chunk.distance,
                )
            )
        results.append(
            QuestionResult(
                id=question.id,
                text=question.text,
                recall=section_recall(ranked, question.expected),
                reciprocal_rank=reciprocal_rank(ranked, question.expected),
                retrieved=retrieved,
                latencies_ms=latencies,
            )
        )

    total_recall = 0.0
    total_reciprocal_rank = 0.0
    for result in results:
        total_recall += result.recall
        total_reciprocal_rank += result.reciprocal_rank
    return EvalRun(
        model_id=embedder.info.model_id,
        dimension=embedder.info.dimension,
        k=k,
        ef_search=ef_search,
        repeats=repeats,
        reranker=None if reranker is None else reranker.model_id,
        candidates=None if reranker is None else candidates,
        hybrid=hybrid,
        recall_at_k=total_recall / len(results),
        mrr=total_reciprocal_rank / len(results),
        latency_p50_ms=percentile(all_latencies, 50),
        latency_p95_ms=percentile(all_latencies, 95),
        questions=results,
    )


def write_run(run: EvalRun | AgentEvalRun, folder: Path, *, name: str) -> Path:
    """Save ``run`` as ``<folder>/<name>.json``, with its name and the time it was saved.

    Creates ``folder`` if needed. Raises ``FileExistsError`` if a run with that name is already
    saved, and ``ValueError`` if ``name`` is not a plain file name of letters, digits, dots,
    dashes, and underscores.
    """
    path = run_path(folder, name)
    if path.exists():
        raise FileExistsError(f"A run named {name!r} is already saved at {path}.")
    folder.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Any] = {
        "name": name,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    # asdict turns the run, and the dataclasses nested in it, into plain dicts and lists.
    saved.update(asdict(run))
    # Mode "x" creates the file and fails if it appeared since the check above.
    with path.open("x", encoding="utf-8") as file:
        json.dump(saved, file, indent=2)
        file.write("\n")
    return path


def run_path(folder: Path, name: str) -> Path:
    """Where a run named ``name`` is saved in ``folder``.

    Raises ``ValueError`` if ``name`` is not a plain file name of letters, digits, dots, dashes,
    and underscores, so a name can never point outside ``folder``.
    """
    if RUN_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(
            f"Run name {name!r} must be letters, digits, dots, dashes, and underscores."
        )
    return folder / f"{name}.json"
