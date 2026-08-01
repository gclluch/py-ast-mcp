"""Shared parsing, caching and AST navigation helpers.

Every tool module goes through :func:`parse_file`, which caches parsed modules
by ``(path, mtime, size)`` so that repeated tool calls on the same file during a
single agent turn are cheap.
"""

from __future__ import annotations

import ast
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

__all__ = [
    "AstToolError",
    "ParseError",
    "ParsedModule",
    "parse_file",
    "parse_source",
    "clear_cache",
    "iter_py_files",
    "resolve_path",
    "is_test_file",
    "is_test_filename",
]


class AstToolError(Exception):
    """Base class for user-facing, non-crashing tool errors."""


class ParseError(AstToolError):
    """A Python file could not be parsed."""

    def __init__(
        self,
        path: str,
        message: str,
        line: int | None = None,
        col: int | None = None,
        text: str | None = None,
    ) -> None:
        self.path = path
        self.message = message
        self.line = line
        self.col = col
        self.text = text
        loc = ""
        if line is not None:
            loc = f":{line}" + (f":{col}" if col is not None else "")
        super().__init__(f"SyntaxError in {path}{loc}: {message}")

    def render(self) -> str:
        loc = ""
        if self.line is not None:
            loc = f" (line {self.line}" + (
                f", col {self.col})" if self.col is not None else ")"
            )
        out = [f"ERROR: cannot parse {self.path}{loc}", f"  {self.message}"]
        if self.text:
            out.append(f"  | {self.text.rstrip()}")
            if self.col is not None:
                out.append("  | " + " " * max(self.col - 1, 0) + "^")
        return "\n".join(out)


@dataclass
class ParsedModule:
    """A parsed Python module plus navigation helpers."""

    path: str
    source: str
    tree: ast.Module
    mtime: float
    size: int
    lines: list[str] = field(default_factory=list)
    _parents: dict[int, ast.AST] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.lines:
            self.lines = self.source.splitlines()
        self._build_parents()

    # -- navigation ---------------------------------------------------------
    def _build_parents(self) -> None:
        self._parents = {}
        for parent in ast.walk(self.tree):
            for child in ast.iter_child_nodes(parent):
                self._parents[id(child)] = parent

    def parent(self, node: ast.AST) -> ast.AST | None:
        return self._parents.get(id(node))

    def ancestors(self, node: ast.AST) -> list[ast.AST]:
        out: list[ast.AST] = []
        cur = self.parent(node)
        while cur is not None:
            out.append(cur)
            cur = self.parent(cur)
        return out

    def enclosing_scopes(self, node: ast.AST) -> list[ast.AST]:
        """Innermost-first list of enclosing def/class/module nodes."""
        scopes = [
            a
            for a in self.ancestors(node)
            if isinstance(
                a,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Lambda,
                    ast.Module,
                ),
            )
        ]
        return scopes

    def qualname(self, node: ast.AST) -> str:
        """Dotted name of a def/class node relative to the module."""
        name = getattr(node, "name", None)
        parts: list[str] = [name] if name else []
        for anc in self.ancestors(node):
            anc_name = getattr(anc, "name", None)
            if anc_name and isinstance(
                anc, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                parts.append(anc_name)
        return ".".join(reversed(parts))

    # -- source access ------------------------------------------------------
    def line(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1]
        return ""

    def segment(self, node: ast.AST) -> str:
        try:
            seg = ast.get_source_segment(self.source, node)
        except Exception:  # pragma: no cover - defensive
            seg = None
        if seg is not None:
            return seg
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start) or start
        return "\n".join(self.lines[start - 1 : end])

    def numbered(self, start: int, end: int, indent: str = "") -> str:
        """Render an inclusive line range with line numbers."""
        start = max(start, 1)
        end = min(end, len(self.lines))
        width = len(str(end))
        return "\n".join(
            f"{indent}{i:>{width}} | {self.lines[i - 1]}" for i in range(start, end + 1)
        )


_CACHE: dict[str, ParsedModule] = {}
_LOCK = threading.Lock()


def resolve_path(path: str) -> str:
    p = Path(path).expanduser()
    return str(p.resolve()) if p.exists() else str(p)


def parse_source(source: str, path: str = "<string>") -> ParsedModule:
    try:
        tree = ast.parse(source, filename=path, type_comments=False)
    except SyntaxError as exc:
        raise ParseError(path, exc.msg, exc.lineno, exc.offset, exc.text) from exc
    return ParsedModule(
        path=path, source=source, tree=tree, mtime=0.0, size=len(source)
    )


def parse_file(path: str) -> ParsedModule:
    """Parse ``path``, using the mtime/size keyed cache when possible."""
    real = resolve_path(path)
    p = Path(real)
    if not p.exists():
        raise AstToolError(f"File not found: {path}")
    if p.is_dir():
        raise AstToolError(f"Expected a file but got a directory: {path}")
    st = p.stat()
    with _LOCK:
        cached = _CACHE.get(real)
        if cached and cached.mtime == st.st_mtime and cached.size == st.st_size:
            return cached
    try:
        source = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = p.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=real)
    except SyntaxError as exc:
        raise ParseError(real, exc.msg, exc.lineno, exc.offset, exc.text) from exc
    mod = ParsedModule(
        path=real, source=source, tree=tree, mtime=st.st_mtime, size=st.st_size
    )
    with _LOCK:
        _CACHE[real] = mod
        if len(_CACHE) > 256:
            # cheap bounded cache: drop an arbitrary quarter
            for key in list(_CACHE)[:64]:
                _CACHE.pop(key, None)
    return mod


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
    ".eggs",
}


def is_test_filename(path: str | Path) -> bool:
    """True when the *file name* alone marks it as a test module."""
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def is_test_file(path: str | Path, root: str | Path | None = None) -> bool:
    """True for test modules.

    Directory-based detection is judged *relative to the scan root*, so pointing
    a tool at ``.../tests/fixtures`` does not classify everything inside it as
    tests.
    """
    p = Path(path)
    if is_test_filename(p):
        return True
    parts = p.parts
    if root is not None:
        try:
            parts = p.relative_to(root).parts
        except ValueError:
            pass
    return any(part in {"tests", "test", "testing"} for part in parts[:-1])


def iter_py_files(
    root: str | Path, include_tests: bool = False, recursive: bool = True
) -> Iterator[Path]:
    """Yield ``.py`` files under ``root`` (or ``root`` itself if it is a file)."""
    rp = Path(resolve_path(str(root)))
    if rp.is_file():
        yield rp
        return
    if not rp.exists():
        raise AstToolError(f"Path not found: {root}")
    if recursive:
        walker: Iterable[Path] = sorted(rp.rglob("*.py"))
    else:
        walker = sorted(rp.glob("*.py"))
    for f in walker:
        # relative to the scan root: a repo living under a directory that happens
        # to be named "build" or "env" must not exclude its own contents
        rel = f.relative_to(rp) if f != rp else f
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if not include_tests and is_test_file(f, root=rp):
            continue
        yield f


def containing_dir(path: str) -> Path:
    p = Path(resolve_path(path))
    return p if p.is_dir() else p.parent
