"""Root pytest configuration shared across every workspace package.

Auto-applies the ``unit`` marker to any test not marked ``integration``, so ``uv run pytest -m
unit`` selects the fast, DB-free suite without each test file opting in, and keeps doing so as tests
are added. Integration tests opt in explicitly with ``@pytest.mark.integration`` (or a module-level
``pytestmark``); everything else is unit by default.
"""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag every collected test lacking the ``integration`` mark with the ``unit`` mark."""
    for item in items:
        if item.get_closest_marker("integration") is None:
            item.add_marker(pytest.mark.unit)
