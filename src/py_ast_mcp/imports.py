"""Imports and exports."""

from __future__ import annotations

import ast
import sys

from .format import bullet, empty, header, loc, plural, section, truncate, unparse
from .parse import ParsedModule, parse_file
from .types import class_kind_of

__all__ = ["list_imports", "list_exports", "collect_imports", "dunder_all"]

_STDLIB = set(getattr(sys, "stdlib_module_names", ()))


class ImportRec:
    __slots__ = ("binding", "module", "name", "level", "alias", "lineno", "is_from")

    def __init__(
        self,
        binding: str,
        module: str,
        name: str | None,
        level: int,
        alias: str | None,
        lineno: int,
        is_from: bool,
    ) -> None:
        self.binding = binding
        self.module = module
        self.name = name
        self.level = level
        self.alias = alias
        self.lineno = lineno
        self.is_from = is_from

    @property
    def source(self) -> str:
        dots = "." * self.level
        if self.is_from:
            return f"{dots}{self.module}.{self.name}" if self.module else f"{dots}{self.name}"
        return self.module

    @property
    def origin(self) -> str:
        if self.level:
            return "relative"
        root = (self.module or "").split(".")[0]
        if root in _STDLIB:
            return "stdlib"
        return "third-party/local"


def collect_imports(pm: ParsedModule) -> list[ImportRec]:
    recs: list[ImportRec] = []
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                binding = a.asname or a.name.split(".")[0]
                recs.append(
                    ImportRec(binding, a.name, None, 0, a.asname, node.lineno, False)
                )
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                binding = a.asname or a.name
                recs.append(
                    ImportRec(
                        binding,
                        node.module or "",
                        a.name,
                        node.level or 0,
                        a.asname,
                        node.lineno,
                        True,
                    )
                )
    recs.sort(key=lambda r: (r.lineno, r.binding))
    return recs


def list_imports(path: str) -> str:
    pm = parse_file(path)
    recs = collect_imports(pm)
    out = [header("imports", pm.path, plural(len(recs), "binding"))]
    if not recs:
        out.append(empty("imports"))
        return "\n".join(out)
    groups: dict[str, list[ImportRec]] = {}
    for r in recs:
        groups.setdefault(r.origin, []).append(r)
    for origin in ("stdlib", "third-party/local", "relative"):
        if origin not in groups:
            continue
        out.append(section(f"{origin} ({len(groups[origin])})"))
        for r in groups[origin]:
            desc = f"[{loc(line=r.lineno)}] {r.binding}"
            if r.is_from:
                dots = "." * r.level
                desc += f" <- from {dots}{r.module or ''} import {r.name}"
            else:
                desc += f" <- import {r.module}"
            if r.alias:
                desc += f" as {r.alias}"
            if r.level:
                desc += f"  (relative level {r.level})"
            out.append(bullet(desc))
    return "\n".join(out)


def dunder_all(pm: ParsedModule) -> tuple[list[str], int] | None:
    """Return (names, lineno) for a module-level ``__all__`` literal."""
    for stmt in pm.tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        elif isinstance(stmt, ast.AugAssign):
            targets, value = [stmt.target], stmt.value
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "__all__" and value is not None:
                names: list[str] = []
                if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                    names = [
                        e.value
                        for e in value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                return names, stmt.lineno
    return None


def list_exports(path: str) -> str:
    pm = parse_file(path)
    all_decl = dunder_all(pm)
    imported = {r.binding: r for r in collect_imports(pm) if r.lineno}
    defined: dict[str, tuple[str, int, int]] = {}
    for stmt in pm.tree.body:
        if isinstance(stmt, ast.ClassDef):
            defined[stmt.name] = (class_kind_of(stmt), stmt.lineno, stmt.end_lineno or stmt.lineno)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async function" if isinstance(stmt, ast.AsyncFunctionDef) else "function"
            defined[stmt.name] = (kind, stmt.lineno, stmt.end_lineno or stmt.lineno)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            defined[stmt.target.id] = ("variable", stmt.lineno, stmt.lineno)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    defined[t.id] = ("variable", stmt.lineno, stmt.lineno)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    for e in t.elts:
                        if isinstance(e, ast.Name):
                            defined[e.id] = ("variable", stmt.lineno, stmt.lineno)
        elif hasattr(ast, "TypeAlias") and isinstance(stmt, getattr(ast, "TypeAlias")):
            defined[unparse(stmt.name)] = ("type alias", stmt.lineno, stmt.lineno)

    out: list[str] = []
    if all_decl is not None:
        names, lineno = all_decl
        out.append(header("exports", pm.path, f"__all__ at L{lineno}, {len(names)} names"))
        out.append(section("__all__"))
        for n in names:
            if n in defined:
                kind, ln, _ = defined[n]
                out.append(bullet(f"[L{ln}] {n}  ({kind})"))
            elif n in imported:
                r = imported[n]
                out.append(bullet(f"[L{r.lineno}] {n}  (re-export from {r.source})"))
            else:
                out.append(bullet(f"{n}  (!! listed in __all__ but not defined here)"))
        extra = [
            n
            for n in defined
            if not n.startswith("_") and n not in names
        ]
        if extra:
            out.append(section(f"public but not in __all__ ({len(extra)})"))
            for n in sorted(extra, key=lambda x: defined[x][1]):
                kind, ln, _ = defined[n]
                out.append(bullet(f"[L{ln}] {n}  ({kind})"))
        return "\n".join(out)

    public_defined = {n: v for n, v in defined.items() if not n.startswith("_")}
    reexports = {
        n: r for n, r in imported.items() if not n.startswith("_") and n not in defined
    }
    total = len(public_defined) + len(reexports)
    out.append(
        header("exports", pm.path, f"no __all__; {total} implicit public names")
    )
    if public_defined:
        out.append(section(f"defined here ({len(public_defined)})"))
        for n in sorted(public_defined, key=lambda x: public_defined[x][1]):
            kind, ln, end = public_defined[n]
            out.append(bullet(f"[{loc(line=ln, end=end)}] {n}  ({kind})"))
    if reexports:
        out.append(section(f"re-exported imports ({len(reexports)})"))
        for n in sorted(reexports, key=lambda x: reexports[x].lineno):
            r = reexports[n]
            out.append(bullet(f"[L{r.lineno}] {n}  (from {r.source})"))
    if not public_defined and not reexports:
        out.append(empty("public names"))
    return "\n".join(out)
