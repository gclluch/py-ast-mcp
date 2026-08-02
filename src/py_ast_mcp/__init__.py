"""py-ast-mcp — MCP server for deep structural analysis of Python source."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

# Read the installed metadata rather than restating the number here. A literal
# drifts silently: 0.2.0 went to PyPI reporting `__version__ == "0.1.0"` because
# the release bumped pyproject.toml and nothing bumped this file.
try:
    __version__ = _version("py-ast-mcp")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "main"]


def main() -> None:
    """Entry point shim so `python -m py_ast_mcp` and the console script agree."""
    from .server import main as _main

    _main()
