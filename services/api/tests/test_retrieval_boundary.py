"""The agent reaches retrieval only through the MCP server, never by importing ``rag_core``."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "api"


def imported_modules(path: Path) -> list[str]:
    """Every module name that ``import`` or ``from ... import`` statements in ``path`` name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return names


def test_no_api_module_imports_rag_core() -> None:
    """A direct import would bypass the MCP tool and break the retrieval boundary."""
    offenders: list[str] = []
    for path in sorted(SOURCE.rglob("*.py")):
        for name in imported_modules(path):
            if name == "rag_core" or name.startswith("rag_core."):
                offenders.append(f"{path.relative_to(SOURCE)} imports {name}")
    assert offenders == []


def test_the_boundary_check_sees_the_source_files() -> None:
    """The check above is only meaningful if it actually finds the package's modules."""
    assert (SOURCE / "__init__.py").is_file()
