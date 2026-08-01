"""Shared output formatting.

Everything these tools emit is read by a language model, so the house style is
dense, scannable plain text with line numbers everywhere -- not JSON dumps.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from pathlib import Path

__all__ = [
    "header",
    "section",
    "bullet",
    "loc",
    "rel",
    "table",
    "indent",
    "join_nonempty",
    "truncate",
    "unparse",
    "plural",
    "empty",
]


def header(title: str, path: str | None = None, extra: str | None = None) -> str:
    line = f"# {title}"
    if path:
        line += f"  {path}"
    if extra:
        line += f"  [{extra}]"
    return line


def section(title: str) -> str:
    return f"\n## {title}"


def bullet(text: str, level: int = 0) -> str:
    return "  " * level + f"- {text}"


def loc(
    node: ast.AST | None = None, line: int | None = None, end: int | None = None
) -> str:
    """Render a location marker like ``L12-30`` or ``L7``."""
    if node is not None:
        line = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
    if line is None:
        return "L?"
    if end is not None and end != line:
        return f"L{line}-{end}"
    return f"L{line}"


def rel(path: str | Path, base: str | Path | None = None) -> str:
    p = Path(path)
    if base is None:
        return p.name
    try:
        return str(p.relative_to(base))
    except ValueError:
        return str(p)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + ln if ln else ln for ln in text.splitlines())


def join_nonempty(parts: Iterable[str], sep: str = "\n") -> str:
    return sep.join(p for p in parts if p)


def truncate(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def plural(n: int, word: str, suffix: str = "s") -> str:
    return f"{n} {word}{'' if n == 1 else suffix}"


def empty(what: str) -> str:
    return f"(none) no {what} found"


def table(rows: Sequence[Sequence[str]], headers: Sequence[str] | None = None) -> str:
    """Fixed-width columns; cheaper for a model to scan than markdown pipes."""
    all_rows = ([list(headers)] if headers else []) + [list(r) for r in rows]
    if not all_rows:
        return ""
    ncols = max(len(r) for r in all_rows)
    for r in all_rows:
        while len(r) < ncols:
            r.append("")
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(ncols)]
    out = []
    for idx, r in enumerate(all_rows):
        cells = [str(c).ljust(widths[i]) for i, c in enumerate(r)]
        out.append("  ".join(cells).rstrip())
        if headers and idx == 0:
            out.append("  ".join("-" * w for w in widths).rstrip())
    return "\n".join(out)


def unparse(node: ast.AST | None) -> str:
    """``ast.unparse`` that never raises."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return "<expr>"
