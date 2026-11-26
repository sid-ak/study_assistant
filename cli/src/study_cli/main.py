"""The ``study`` console script: parse a command and run it against ``rag_core``.

Each command function takes its ``Components`` as an argument, so tests can run it against fakes.
``main`` builds the real ones from ``Settings`` through ``build_components``.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rag_core.config import Settings
from rag_core.embed import EmbedderProtocol, FastembedEmbedder, register_embedder
from rag_core.ingest import ingest_folder
from rag_core.retrieve import retrieve
from rag_core.store import EmbedderNotFoundError, Store, StoreProtocol
from rag_core.store.embedders import EmbedderRegistry, EmbedderRegistryProtocol

# Exit status for a command that could not run because of its input, as argparse uses for usage.
USAGE_ERROR = 2
# Characters of a chunk's text shown under each query result.
PREVIEW_LENGTH = 100


@dataclass(frozen=True)
class Components:
    """The embedder, store, and registry a command runs against."""

    embedder: EmbedderProtocol
    store: StoreProtocol
    registry: EmbedderRegistryProtocol


def build_components(settings: Settings) -> Components:
    """Build the configured embedder, and a store and registry on the configured database.

    Nothing connects or loads here: the store and registry connect per call, and the embedder
    loads its model on first use.
    """
    embedder = FastembedEmbedder.from_settings(settings)
    store = Store(settings.database_url, embedder=embedder.info)
    registry = EmbedderRegistry(settings.database_url)
    return Components(embedder=embedder, store=store, registry=registry)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for ``study`` and its subcommands."""
    parser = argparse.ArgumentParser(
        prog="study", description="Ingest markdown documents and search them."
    )
    # required=True makes argparse print usage and exit with status 2 when no command is given.
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Load every markdown file under a folder.")
    ingest.add_argument("folder", type=Path, help="Folder to ingest, searched recursively.")

    query = commands.add_parser("query", help="Show the chunks nearest to a question.")
    query.add_argument("text", help="The question or search text.")
    query.add_argument("--limit", type=int, default=5, help="How many chunks to show (default 5).")
    query.add_argument(
        "--ef-search",
        type=int,
        default=None,
        help="HNSW candidate-list size for this search, 1 to 1000 (default: the index's own).",
    )
    return parser


def run_ingest(folder: Path, components: Components) -> int:
    """Ingest ``folder``, print what changed, and return the exit status.

    Prepares the database schema, registers the configured model, and makes it current if no
    model is current yet, so the first ingest needs no separate setup step.
    """
    components.store.initialize()
    model_id = components.embedder.info.model_id
    if register_embedder(components.registry, components.embedder.info):
        print(f"{model_id} is now the current embedding model.")
    try:
        report = ingest_folder(folder, store=components.store, embedder=components.embedder)
    except NotADirectoryError as error:
        print(f"study ingest: {error}", file=sys.stderr)
        return USAGE_ERROR

    for source in report.added:
        print(f"added {source}")
    for source in report.replaced:
        print(f"replaced {source}")
    for source in report.empty:
        print(f"empty {source}")
    print(
        f"{len(report.added)} added, {len(report.replaced)} replaced, "
        f"{len(report.unchanged)} unchanged, {len(report.empty)} empty; "
        f"{report.chunks_written} chunks written"
    )
    return 0


def chunk_location(metadata: dict[str, Any]) -> str:
    """Where a chunk comes from: its source, then its heading path, each separated by ``>``."""
    parts = [str(metadata.get("source", "?"))]
    for heading in metadata.get("headings", []):
        parts.append(str(heading))
    return " > ".join(parts)


def body_preview(content: str, metadata: dict[str, Any]) -> str:
    """The start of a chunk's body on one line, without its heading breadcrumb."""
    body = content
    if metadata.get("headings"):
        # Chunks under a heading start with a breadcrumb line and a blank line; skip both.
        _, _, body = content.partition("\n\n")
    one_line = " ".join(body.split())
    if len(one_line) > PREVIEW_LENGTH:
        return one_line[:PREVIEW_LENGTH] + "..."
    return one_line


def run_query(text: str, limit: int, ef_search: int | None, components: Components) -> int:
    """Print the ``limit`` chunks nearest to ``text`` and the search latency; return the status.

    Each result line shows the rank, the cosine distance, the chunk id, and the chunk's source and
    headings, followed by the start of its text. The model is loaded before the timed search, so
    the reported latency is embedding the query plus searching, not loading the model.
    """
    components.store.initialize()
    embedder = components.embedder
    model_id = embedder.info.model_id
    # The first embedding in a process loads the model; do it here, outside the timed search.
    embedder.embed_query("warm up")
    try:
        result = retrieve(
            text, embedder=embedder, store=components.store, limit=limit, ef_search=ef_search
        )
    except EmbedderNotFoundError:
        print(
            f"study query: nothing has been ingested with {model_id}; "
            "run study ingest <folder> first.",
            file=sys.stderr,
        )
        return USAGE_ERROR
    except ValueError as error:
        print(f"study query: {error}", file=sys.stderr)
        return USAGE_ERROR

    for rank, chunk in enumerate(result.chunks, start=1):
        print(f"{rank}. {chunk.distance:.4f}  {chunk.id}  {chunk_location(chunk.metadata)}")
        print(f"   {body_preview(chunk.content, chunk.metadata)}")
    if ef_search is None:
        ef_text = "default"
    else:
        ef_text = str(ef_search)
    print(
        f"{len(result.chunks)} results in {result.latency_ms:.1f} ms "
        f"({model_id}, ef_search {ef_text})"
    )
    if not result.chunks:
        print("Nothing is ingested yet: run study ingest <folder> first.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run ``study`` with ``argv`` (default: ``sys.argv[1:]``) and return its exit status."""
    args = build_parser().parse_args(argv)
    components = build_components(Settings())
    if args.command == "ingest":
        return run_ingest(args.folder, components)
    if args.command == "query":
        return run_query(args.text, args.limit, args.ef_search, components)
    # argparse only accepts the commands registered above, so this line is never reached.
    raise AssertionError(f"Unhandled command {args.command!r}")
