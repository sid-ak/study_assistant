"""The ``study`` console script: parse a command and run it against ``rag_core``.

Each command function takes its ``Components`` as an argument, so tests can run it against fakes.
``main`` builds the real ones from ``Settings`` through ``build_components``.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from rag_core.config import Settings
from rag_core.embed import EmbedderProtocol, FastembedEmbedder, register_embedder
from rag_core.ingest import ingest_folder
from rag_core.store import Store, StoreProtocol
from rag_core.store.embedders import EmbedderRegistry, EmbedderRegistryProtocol

# Exit status for a command that could not run because of its input, as argparse uses for usage.
USAGE_ERROR = 2


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


def main(argv: list[str] | None = None) -> int:
    """Run ``study`` with ``argv`` (default: ``sys.argv[1:]``) and return its exit status."""
    args = build_parser().parse_args(argv)
    components = build_components(Settings())
    if args.command == "ingest":
        return run_ingest(args.folder, components)
    # argparse only accepts the commands registered above, so this line is never reached.
    raise AssertionError(f"Unhandled command {args.command!r}")
