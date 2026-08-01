"""Unreferenced symbol detection across a file or directory."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .format import bullet, header, plural, section, table
from .imports import dunder_all
from .parse import (
    AstToolError,
    ParsedModule,
    ParseError,
    containing_dir,
    iter_py_files,
    parse_file,
    resolve_path,
)

__all__ = ["dead_code", "collect_defs", "collect_refs"]

_ALWAYS_LIVE = {
    "main",
    "__init__",
    "__all__",
    "setup",
    "teardown",
    "app",
}


@dataclass
class Definition:
    name: str
    kind: str
    file: str
    lineno: int
    end_lineno: int
    private: bool
    exported: bool
    decorators: list[str]


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def collect_defs(pm: ParsedModule) -> list[Definition]:
    exported: set[str] = set()
    all_decl = dunder_all(pm)
    has_all = all_decl is not None
    if all_decl:
        exported = set(all_decl[0])
    out: list[Definition] = []

    def add(
        name: str, kind: str, node: ast.AST, decorators: list[str] | None = None
    ) -> None:
        out.append(
            Definition(
                name=name,
                kind=kind,
                file=pm.path,
                lineno=getattr(node, "lineno", 0),
                end_lineno=getattr(node, "end_lineno", 0) or getattr(node, "lineno", 0),
                private=name.startswith("_") and not _is_dunder(name),
                exported=name in exported if has_all else not name.startswith("_"),
                decorators=decorators or [],
            )
        )

    for stmt in pm.tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(
                stmt.name,
                "async function"
                if isinstance(stmt, ast.AsyncFunctionDef)
                else "function",
                stmt,
                [ast.unparse(d) for d in stmt.decorator_list],
            )
        elif isinstance(stmt, ast.ClassDef):
            add(stmt.name, "class", stmt, [ast.unparse(d) for d in stmt.decorator_list])
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            add(stmt.target.id, "variable", stmt)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    add(t.id, "variable", stmt)

    # private methods on classes
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ClassDef):
            for s in node.body:
                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if s.name.startswith("_") and not _is_dunder(s.name):
                        out.append(
                            Definition(
                                name=s.name,
                                kind=f"private method of {node.name}",
                                file=pm.path,
                                lineno=s.lineno,
                                end_lineno=s.end_lineno or s.lineno,
                                private=True,
                                exported=False,
                                decorators=[ast.unparse(d) for d in s.decorator_list],
                            )
                        )
    return out


def collect_refs(pm: ParsedModule) -> dict[str, list[int]]:
    """Every name that is *read* (not merely defined) in this module."""
    refs: dict[str, list[int]] = {}

    def note(name: str, lineno: int) -> None:
        refs.setdefault(name, []).append(lineno)

    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
            note(node.id, node.lineno)
        elif isinstance(node, ast.Attribute):
            note(node.attr, node.lineno)
        elif isinstance(node, ast.alias):
            note(node.name.split(".")[0], getattr(node, "lineno", 0))
            note(node.name.split(".")[-1], getattr(node, "lineno", 0))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # __all__ entries, getattr("name"), and string annotations
            if node.value.isidentifier():
                note(node.value, node.lineno)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for n in node.names:
                note(n, node.lineno)
    return refs


def _def_self_lines(d: Definition) -> range:
    return range(d.lineno, d.end_lineno + 1)


def dead_code(path: str, include_tests: bool = False) -> str:
    root = Path(resolve_path(path))
    if root.is_file():
        scan_root = containing_dir(str(root))
        files = list(iter_py_files(scan_root, include_tests=include_tests))
        focus: str | None = str(root)
        if root not in files:
            files.append(root)
    else:
        scan_root = root
        files = list(iter_py_files(root, include_tests=include_tests))
        focus = None
    if not files:
        raise AstToolError(f"No .py files found for {path}")

    defs: list[Definition] = []
    refs_by_file: dict[str, dict[str, list[int]]] = {}
    errors: list[str] = []
    for f in files:
        try:
            pm = parse_file(str(f))
        except ParseError as exc:
            errors.append(f"{f}: {exc.message} (line {exc.line})")
            continue
        defs.extend(collect_defs(pm))
        refs_by_file[pm.path] = collect_refs(pm)

    dead: list[Definition] = []
    for d in defs:
        if _is_dunder(d.name) or d.name in _ALWAYS_LIVE or d.name == "_":
            continue
        if any(
            dec.split(".")[-1] in {"fixture", "task", "command", "route", "app"}
            or "register" in dec
            or "route" in dec
            for dec in d.decorators
        ):
            continue
        used_elsewhere = False
        for file, refs in refs_by_file.items():
            hits = refs.get(d.name, [])
            if not hits:
                continue
            if file != d.file:
                used_elsewhere = True
                break
            own = set(_def_self_lines(d))
            if any(h not in own for h in hits):
                used_elsewhere = True
                break
        if used_elsewhere:
            continue
        # private vs public is split at render time, below
        dead.append(d)

    private_dead = [d for d in dead if d.private]
    public_dead = [d for d in dead if not d.private]
    if focus:
        private_dead = [d for d in private_dead if d.file == focus] + [
            d for d in private_dead if d.file != focus
        ]

    out = [
        header(
            "dead_code",
            str(scan_root),
            f"{plural(len(files), 'file')} scanned, {len(defs)} definitions, "
            f"include_tests={include_tests}",
        )
    ]
    out.append(
        "method: a symbol is dead if no *other* line in any scanned file reads its "
        "name. Matching is by name only, not by scope or type. False positives: "
        "dynamic access (getattr, plugin registries, re-exports outside the scan). "
        "False negatives are the bigger risk - any attribute access or string "
        "literal anywhere with the same name marks a symbol live, so this "
        "under-reports. Treat hits as candidates to confirm, not as proof."
    )
    if errors:
        out.append(section("unparseable"))
        out.extend(bullet(e) for e in errors)

    def render(group: list[Definition], title: str, note: str) -> None:
        out.append(section(f"{title} ({len(group)})"))
        if not group:
            out.append("(none)")
            return
        out.append(note)
        rows = [
            [
                f"{Path(d.file).name}:{d.lineno}",
                d.name,
                d.kind,
                f"{d.end_lineno - d.lineno + 1} lines",
            ]
            for d in sorted(group, key=lambda x: (x.file, x.lineno))
        ]
        out.append(table(rows, ["location", "symbol", "kind", "size"]))

    render(
        private_dead,
        "unreferenced private symbols",
        "high confidence — private names cannot be used outside this package.",
    )
    render(
        public_dead,
        "unreferenced public symbols",
        "lower confidence — may be part of the public API used by callers outside "
        "the scanned directory.",
    )
    if not dead:
        out.append("\nNo unreferenced symbols found.")
    return "\n".join(out)
