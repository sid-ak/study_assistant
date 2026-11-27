"""Every third-party module the generation lane imports is declared as its own dependency.

A module that arrives only through another package's requirements works until that package drops
it. The lane imports ``psycopg`` and ``langchain_core`` directly, so it has to ask for them itself.
"""

import ast
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
SOURCE = PACKAGE / "src" / "api"


def top_level_imports(path: Path) -> set[str]:
    """The first part of every module ``path`` imports: ``psycopg`` for ``psycopg.rows``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def imported_third_party_modules() -> set[str]:
    """Every module the lane imports that is neither its own nor from the standard library."""
    modules: set[str] = set()
    for path in sorted(SOURCE.rglob("*.py")):
        for name in top_level_imports(path):
            if name != "api" and name not in sys.stdlib_module_names:
                modules.add(name)
    return modules


def declared_distributions() -> set[str]:
    """The distribution names in the package's ``dependencies``, without extras or versions."""
    with (PACKAGE / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    declared: set[str] = set()
    for requirement in pyproject["project"]["dependencies"]:
        # "psycopg[binary]>=3.3.4" names the distribution "psycopg".
        name = requirement.split(";")[0]
        for separator in ["[", ">", "<", "=", "!", "~", " "]:
            name = name.split(separator)[0]
        declared.add(name.strip().lower().replace("_", "-"))
    return declared


def test_every_imported_third_party_module_is_declared() -> None:
    """An undeclared import breaks as soon as the package that happened to supply it changes."""
    declared = declared_distributions()
    module_to_distributions = packages_distributions()
    undeclared: list[str] = []
    for module in sorted(imported_third_party_modules()):
        distributions = module_to_distributions.get(module, [])
        names = set()
        for distribution in distributions:
            names.add(distribution.lower().replace("_", "-"))
        if not names & declared:
            undeclared.append(f"{module} (from {sorted(names) or 'an unknown distribution'})")
    assert undeclared == []


def test_the_check_sees_the_lane_s_own_imports() -> None:
    """The check above is only meaningful if it finds the modules the lane really imports."""
    modules = imported_third_party_modules()

    assert "langgraph" in modules
    assert "psycopg" in modules
