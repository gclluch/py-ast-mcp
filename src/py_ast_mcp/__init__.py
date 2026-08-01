"""py-ast-mcp — MCP server for deep structural analysis of Python source."""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__", "main"]


def main() -> None:
    """Entry point shim so `python -m py_ast_mcp` and the console script agree."""
    from .server import main as _main

    _main()
