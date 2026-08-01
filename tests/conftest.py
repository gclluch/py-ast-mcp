"""Shared pytest fixtures: paths to the sample sources under tests/fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_parse_cache():
    from py_ast_mcp.parse import clear_cache

    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def sample() -> str:
    return str(FIXTURES / "sample.py")


@pytest.fixture
def smelly() -> str:
    return str(FIXTURES / "smelly.py")


@pytest.fixture
def helpers() -> str:
    return str(FIXTURES / "helpers.py")


@pytest.fixture
def broken() -> str:
    return str(FIXTURES / "broken.py")


@pytest.fixture
def pkg() -> str:
    return str(FIXTURES / "samplepkg")


@pytest.fixture
def pkg_core() -> str:
    return str(FIXTURES / "samplepkg" / "core.py")


@pytest.fixture
def nested_top() -> str:
    """Module whose symbol is referenced from a *different* directory."""
    return str(FIXTURES / "nestedpkg" / "top.py")


@pytest.fixture
def nested_deep() -> str:
    """Module one directory below the one it imports from."""
    return str(FIXTURES / "nestedpkg" / "sub" / "deep.py")


@pytest.fixture
def old_version() -> str:
    return str(FIXTURES / "old_version.py")


@pytest.fixture
def new_version() -> str:
    return str(FIXTURES / "new_version.py")


@pytest.fixture
def dataclasses_bad() -> str:
    """Dataclass field defaults; the reported ones are import-time ValueErrors."""
    return str(FIXTURES / "dataclasses_bad.py")


@pytest.fixture
def matching() -> str:
    """`match` shapes, scored against radon itself."""
    return str(FIXTURES / "matching.py")


@pytest.fixture
def hazards() -> str:
    """Hazards the first pass of find_errors stayed silent about."""
    return str(FIXTURES / "hazards.py")
