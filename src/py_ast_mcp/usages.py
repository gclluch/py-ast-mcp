"""Identifier usage search with source context."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .format import bullet, header, plural, section, truncate
from .parse import ParsedModule, parse_file

__all__ = ["find_usages", "collect_usages", "Usage"]


@dataclass
class Usage:
    lineno: int
    col: int
    role: str
    scope: str
    text: str


def _scope_name(pm: ParsedModule, node: ast.AST) -> str:
    for s in pm.enclosing_scopes(node):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return pm.qualname(s)
        if isinstance(s, ast.Lambda):
            return "<lambda>"
    return "<module>"


def collect_usages(pm: ParsedModule, identifier: str) -> list[Usage]:
    out: list[Usage] = []
    seen: set[tuple[int, int, str]] = set()

    def add(node: ast.AST, role: str) -> None:
        ln = getattr(node, "lineno", 0)
        col = getattr(node, "col_offset", 0)
        key = (ln, col, role)
        if key in seen:
            return
        seen.add(key)
        out.append(Usage(ln, col, role, _scope_name(pm, node), pm.line(ln).rstrip()))

    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Name) and node.id == identifier:
            role = {
                ast.Store: "assignment",
                ast.Del: "deletion",
            }.get(type(node.ctx), "read")
            add(node, role)
        elif isinstance(node, ast.Attribute) and node.attr == identifier:
            add(node, "attribute access")
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == identifier
        ):
            add(node, "function definition")
        elif isinstance(node, ast.ClassDef) and node.name == identifier:
            add(node, "class definition")
        elif isinstance(node, ast.arg) and node.arg == identifier:
            add(node, "parameter")
        elif isinstance(node, ast.keyword) and node.arg == identifier:
            add(node, "keyword argument")
        elif (
            isinstance(node, ast.alias)
            and (node.asname or node.name.split(".")[0]) == identifier
        ):
            add(node, "import binding")
        elif isinstance(node, ast.Global) and identifier in node.names:
            add(node, "global declaration")
        elif isinstance(node, ast.Nonlocal) and identifier in node.names:
            add(node, "nonlocal declaration")
        elif isinstance(node, ast.ExceptHandler) and node.name == identifier:
            add(node, "exception binding")
    out.sort(key=lambda u: (u.lineno, u.col))
    return out


def find_usages(path: str, identifier: str, context: int = 1) -> str:
    pm = parse_file(path)
    usages = collect_usages(pm, identifier)
    out = [
        header(f"usages of '{identifier}'", pm.path, plural(len(usages), "occurrence"))
    ]
    if not usages:
        out.append(
            f"\n'{identifier}' does not appear as a name, attribute, parameter or "
            "import binding in this file. It may live in another module, or only "
            "appear inside strings/comments."
        )
        return "\n".join(out)

    roles: dict[str, int] = {}
    for u in usages:
        roles[u.role] = roles.get(u.role, 0) + 1
    out.append("by role: " + ", ".join(f"{k}×{v}" for k, v in sorted(roles.items())))
    scopes: dict[str, list[Usage]] = {}
    for u in usages:
        scopes.setdefault(u.scope, []).append(u)
    out.append("by scope: " + ", ".join(f"{k}×{len(v)}" for k, v in scopes.items()))

    out.append(section("occurrences"))
    for u in usages:
        out.append(bullet(f"L{u.lineno}:{u.col}  {u.role}  in {u.scope}"))
        lo = max(u.lineno - context, 1)
        hi = min(u.lineno + context, len(pm.lines))
        for i in range(lo, hi + 1):
            marker = ">" if i == u.lineno else " "
            out.append(f"    {marker} {i} | {truncate(pm.line(i), 130)}")

    from . import jedi_support

    if jedi_support.available() and usages:
        first = usages[0]
        cross = jedi_support.references(pm.path, pm.source, first.lineno, first.col)
        if cross:
            out.append(section(f"cross-file references via jedi ({len(cross)})"))
            out.extend(bullet(c) for c in cross[:40])
            if len(cross) > 40:
                out.append(bullet(f"... {len(cross) - 40} more"))
    return "\n".join(out)
