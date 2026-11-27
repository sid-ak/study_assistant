"""The ``study-eval`` console script: run the golden set against the ingested corpus and save it.

``main`` builds the real embedder and store from ``Settings`` through ``build_components``, so
tests can replace that function with in-memory fakes.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.golden import check_labels, load_golden
from evals.runner import EvalRun, run_eval, run_path, write_run
from rag_core.config import Settings
from rag_core.embed import EmbedderProtocol, FastembedEmbedder
from rag_core.store import EmbedderNotFoundError, Store, StoreProtocol

# Exit status for a run that could not start because of its input, as argparse uses for usage.
USAGE_ERROR = 2


@dataclass(frozen=True)
class Components:
    """The embedder and store an evaluation runs against."""

    embedder: EmbedderProtocol
    store: StoreProtocol


def build_components(settings: Settings) -> Components:
    """Build the configured embedder and a store bound to it on the configured database.

    Nothing connects or loads here: the store connects per call, and the embedder loads its model
    on first use.
    """
    embedder = FastembedEmbedder.from_settings(settings)
    store = Store(settings.database_url, embedder=embedder.info)
    return Components(embedder=embedder, store=store)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for ``study-eval``. Default paths are relative to the repository root."""
    parser = argparse.ArgumentParser(
        prog="study-eval",
        description="Score retrieval on the golden set and save the run under a name.",
    )
    parser.add_argument("name", help="Name of the saved run, for example dense-bge-small.")
    parser.add_argument(
        "--golden",
        type=Path,
        default=Path("evals/golden/questions.toml"),
        help="Golden-set file (default: evals/golden/questions.toml).",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("corpus/release_engineering"),
        help="Folder the corpus was ingested from, to check labels against "
        "(default: corpus/release_engineering).",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("evals/results"),
        help="Folder runs are saved in (default: evals/results).",
    )
    parser.add_argument(
        "--k", type=int, default=5, help="Chunks retrieved per question (default 5)."
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Timed retrievals per question, for the latency percentiles (default 5).",
    )
    parser.add_argument(
        "--ef-search",
        type=int,
        default=None,
        help="HNSW candidate-list size for every search, 1 to 1000 (default: the index's own).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run ``study-eval`` with ``argv`` (default: the process arguments) and return its status.

    Every input is checked before any retrieval runs: the run name, the golden set, that each
    label names a heading in the corpus, and that the model has a vector for every stored chunk.
    """
    args = build_parser().parse_args(argv)
    try:
        if run_path(args.results, args.name).exists():
            raise ValueError(f"A run named {args.name!r} is already saved in {args.results}.")
        questions = load_golden(args.golden)
        check_labels(questions, args.corpus)
    except (ValueError, OSError) as error:
        # GoldenSetError is a ValueError; OSError covers a golden file that does not exist.
        print(error, file=sys.stderr)
        return USAGE_ERROR

    components = build_components(Settings())
    model_id = components.embedder.info.model_id
    try:
        # A chunk without this model's vector can never be retrieved, so the run would score it as
        # a miss. That means the model was registered but not embedded, not that retrieval failed.
        if components.store.get_unembedded_chunks(limit=1):
            raise ValueError(
                f"Some stored chunks have no vector from {model_id}. "
                "Run `study embed` with this model first."
            )
        run = run_eval(
            questions,
            embedder=components.embedder,
            store=components.store,
            k=args.k,
            ef_search=args.ef_search,
            repeats=args.repeats,
        )
    except (ValueError, EmbedderNotFoundError) as error:
        print(error, file=sys.stderr)
        return USAGE_ERROR

    print_run(run)
    path = write_run(run, args.results, name=args.name)
    print(f"Saved {path}")
    return 0


def print_run(run: EvalRun) -> None:
    """Print each question's recall and reciprocal rank, then the run's totals and settings."""
    for result in run.questions:
        print(f"{result.id:<28} recall {result.recall:.2f}  rr {result.reciprocal_rank:.2f}")
    ef_search = "default" if run.ef_search is None else str(run.ef_search)
    print(
        f"Recall@{run.k} {run.recall_at_k:.2f}  MRR {run.mrr:.2f}  "
        f"latency p50 {run.latency_p50_ms:.1f} ms, p95 {run.latency_p95_ms:.1f} ms"
    )
    print(
        f"({run.model_id}, {len(run.questions)} questions x {run.repeats} repeats, "
        f"ef_search {ef_search})"
    )
