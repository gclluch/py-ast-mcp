"""MCP stdio server exposing the Python AST analysis toolset."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import TypeVar

from mcp.server.mcpserver import MCPServer

from . import __version__
from . import analyze as _analyze
from . import callgraph as _callgraph
from . import complexity as _complexity
from . import deadcode as _deadcode
from . import diff as _diff
from . import doc as _doc
from . import errors as _errors
from . import functions as _functions
from . import imports as _imports
from . import protocols as _protocols
from . import smells as _smells
from . import types as _types
from . import usages as _usages
from .parse import AstToolError, ParseError

__all__ = ["mcp", "main", "create_server", "ToolFailure"]

INSTRUCTIONS = """\
py-ast-mcp performs structural analysis of Python source using the stdlib `ast`
module. Unlike grep it understands real structure: signatures, call
relationships, complexity, dead code and protocol conformance.

Use `analyze_file` first to orient in an unfamiliar module, then drill in with
`list_functions` / `get_function_body` / `call_graph`. All output is compact
annotated text with line numbers; paths may be absolute or relative to the
server's working directory.
"""

mcp: MCPServer = MCPServer("py-ast-mcp", instructions=INSTRUCTIONS, version=__version__)

F = TypeVar("F", bound=Callable[..., str])


class ToolFailure(Exception):
    """A tool failure carrying an already-rendered, user-facing message.

    Raised rather than returned: the MCP server turns any exception escaping a
    tool into a `CallToolResult` with `is_error=True`, which is what lets a
    client tell "this file does not parse" apart from a successful analysis.
    Returning the message as a normal string reports failure as success.
    """


def _safe(fn: F) -> F:
    """Convert internal errors into readable `ToolFailure`s.

    Raw tracebacks are not sent to the client; `raise ... from exc` keeps the
    original for server-side logs.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return fn(*args, **kwargs)
        except ParseError as exc:
            raise ToolFailure(exc.render()) from exc
        except AstToolError as exc:
            raise ToolFailure(f"ERROR: {exc}") from exc
        except RecursionError as exc:
            raise ToolFailure(
                "ERROR: file is too deeply nested for the AST walker"
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise ToolFailure(f"ERROR: unexpected {type(exc).__name__}: {exc}") from exc

    return wrapper  # type: ignore[return-value]


# --------------------------------------------------------------------------
# structural
# --------------------------------------------------------------------------


@mcp.tool()
@_safe
def analyze_file(path: str) -> str:
    """High-level summary of every symbol in a Python file.

    Lists classes (with dataclass/enum/Protocol/TypedDict classification),
    functions, async functions, methods and module-level assignments with line
    numbers. Start here when exploring an unfamiliar module.

    Args:
        path: Path to a .py file.
    """
    return _analyze.analyze_file(path)


@mcp.tool()
@_safe
def list_functions(path: str) -> str:
    """List all functions and methods with full signatures and line ranges.

    Includes parameter annotations and defaults, return annotation, decorators,
    async flag, and nested function relationships.

    Args:
        path: Path to a .py file.
    """
    return _functions.list_functions(path)


@mcp.tool()
@_safe
def get_function_body(path: str, name: str) -> str:
    """Extract the full source of a function or method, with line numbers.

    Args:
        path: Path to a .py file.
        name: Function name, `Class.method`, or a dotted nested path.
    """
    return _functions.get_function_body(path, name)


@mcp.tool()
@_safe
def list_methods(path: str, type: str) -> str:  # noqa: A002 - mirrors TS tool
    """List every method of a class: declared, inherited, properties, class and
    static methods, plus class-level attributes.

    Inherited members are only resolved for base classes defined in the same
    file; bases from other modules are reported as unresolved.

    Args:
        path: Path to a .py file.
        type: Class name.
    """
    return _functions.list_methods(path, type)


@mcp.tool()
@_safe
def get_type_definition(path: str, name: str) -> str:
    """Extract a class, TypeAlias, Enum, Protocol, TypedDict or NamedTuple
    definition with its members and source.

    Args:
        path: Path to a .py file.
        name: Type name.
    """
    return _types.get_type_definition(path, name)


@mcp.tool()
@_safe
def list_declarations(path: str) -> str:
    """List module-level assignments with annotated or inferred types.

    Args:
        path: Path to a .py file.
    """
    return _types.list_declarations(path)


@mcp.tool()
@_safe
def list_exports(path: str) -> str:
    """List the public symbols of a module.

    Respects `__all__` when present, otherwise reports non-underscore
    module-level names, and flags re-exported imports.

    Args:
        path: Path to a .py file.
    """
    return _imports.list_exports(path)


@mcp.tool()
@_safe
def list_imports(path: str) -> str:
    """List all imports: bound name, module path, relative level and aliases,
    grouped into stdlib / third-party / relative.

    Args:
        path: Path to a .py file.
    """
    return _imports.list_imports(path)


@mcp.tool()
@_safe
def find_usages(path: str, identifier: str, context: int = 1) -> str:
    """Find every occurrence of an identifier with surrounding source lines.

    Covers reads, assignments, parameters, attribute access, imports and
    global/nonlocal declarations. Always reports a project-wide references
    section: either the cross-file hits, or that there are none, or that `jedi`
    is not installed and cross-file references were therefore not checked. An
    empty result and an unchecked one are not the same answer.

    Args:
        path: Path to a .py file.
        identifier: Name to search for.
        context: Lines of context to show around each hit (default 1).
    """
    return _usages.find_usages(path, identifier, context)


# --------------------------------------------------------------------------
# call analysis
# --------------------------------------------------------------------------


@mcp.tool()
@_safe
def call_graph(
    path: str,
    function: str | None = None,
    direction: str = "TD",
    include_external: bool = False,
    scope: str = "file",
) -> str:
    """Emit a Mermaid flowchart of the call relationships in a file or package.

    Args:
        path: Path to a .py file.
        function: Optional root; only calls reachable from it are drawn.
        direction: Mermaid layout direction: TD, TB, LR, RL or BT.
        include_external: Include calls to names not defined in scope.
        scope: "file" (default) or "package" to walk every .py file in the
            containing directory.
    """
    return _callgraph.call_graph(path, function, direction, include_external, scope)


@mcp.tool()
@_safe
def get_callers(path: str, function: str, scope: str = "file") -> str:
    """Reverse call graph: who calls this function, directly and transitively.

    Args:
        path: Path to a .py file.
        function: Function name or `Class.method`.
        scope: "file" (default) or "package".
    """
    return _callgraph.get_callers(path, function, scope)


# --------------------------------------------------------------------------
# quality
# --------------------------------------------------------------------------


@mcp.tool()
@_safe
def code_complexity(path: str, function: str | None = None) -> str:
    """Cyclomatic complexity per function, with rank and decision-point breakdown.

    Counts if/elif, for, while, except, with, assert, comprehension ifs, boolean
    operators, ternaries and match cases.

    Args:
        path: Path to a .py file.
        function: Optional single function to analyse in detail.
    """
    return _complexity.code_complexity(path, function)


@mcp.tool()
@_safe
def code_smells(path: str, function: str | None = None) -> str:
    """Detect long functions, deep nesting, god classes, too many parameters,
    mutable default arguments, bare excepts and shadowed builtins.

    Args:
        path: Path to a .py file.
        function: Optional single function to analyse.
    """
    return _smells.code_smells(path, function)


@mcp.tool()
@_safe
def find_errors(path: str, function: str | None = None) -> str:
    """Find Python-specific hazards: bare/broad except, `except: pass`, mutable
    default args, unawaited coroutines (best effort), `assert` used for runtime
    validation, late-binding loop closures, `==` against None/True/False and
    methods that never use `self`.

    Args:
        path: Path to a .py file.
        function: Optional single function to analyse.
    """
    return _errors.find_errors(path, function)


@mcp.tool()
@_safe
def dead_code(path: str, include_tests: bool = False) -> str:
    """Find unreferenced private and module-level symbols across a directory.

    If `path` is a file, its containing directory is scanned so that cross-file
    references are seen.

    Args:
        path: A .py file or a directory.
        include_tests: Also scan test files (default False).
    """
    return _deadcode.dead_code(path, include_tests)


@mcp.tool()
@_safe
def find_implementations(path: str, interface: str) -> str:
    """Find classes implementing a Protocol or ABC, both explicitly (as a base
    class, including indirect subclasses) and structurally (method-set match).

    Args:
        path: A .py file or directory; the containing directory is scanned.
        interface: Name of the Protocol/ABC/base class. Named `interface`
            rather than `protocol` to match the identical tool in the
            TypeScript server, so one vocabulary works across both.
    """
    return _protocols.find_implementations(path, interface)


# --------------------------------------------------------------------------
# docs & multi-file
# --------------------------------------------------------------------------


@mcp.tool()
@_safe
def get_doc(path: str, name: str) -> str:
    """Extract a docstring and parse it into summary/params/returns/raises when
    it follows Google or NumPy style.

    Args:
        path: Path to a .py file.
        name: Symbol name, `Class.method`, or "module" for the module docstring.
    """
    return _doc.get_doc(path, name)


@mcp.tool()
@_safe
def analyze_package(path: str, include_tests: bool = False) -> str:
    """Directory-level summary of every .py file: sizes, class/function counts,
    docstrings and per-file symbol lists.

    Args:
        path: Directory to analyse.
        include_tests: Include test files (default False).
    """
    return _analyze.analyze_package(path, include_tests)


@mcp.tool()
@_safe
def diff_ast(old_path: str, new_path: str) -> str:
    """Structural diff between two Python files: added, removed and modified
    functions, classes, methods, module variables, imports and `__all__`.
    Signature-level, not text-level.

    Args:
        old_path: Path to the original file.
        new_path: Path to the updated file.
    """
    return _diff.diff_ast(old_path, new_path)


@mcp.tool()
@_safe
def find_node_at_position(path: str, line: int, column: int) -> str:
    """Identify the AST node at a cursor position with its enclosing scope chain.

    Args:
        path: Path to a .py file.
        line: 1-based line number.
        column: 0-based column offset.
    """
    return _analyze.find_node_at_position(path, line, column)


def create_server() -> MCPServer:
    return mcp


def main() -> None:
    """Console-script entry point: run the stdio server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
