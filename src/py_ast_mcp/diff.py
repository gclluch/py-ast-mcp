"""Structural (signature-level) diff between two Python files."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .format import header, plural, section, truncate, unparse
from .functions import FuncInfo, collect_functions
from .imports import collect_imports, dunder_all
from .parse import ParsedModule, parse_file
from .types import class_kind_of, infer_literal_type

__all__ = ["diff_ast"]


def _line(text: str) -> str:
    """Diff lines carry their own +/-/~ marker; no bullet prefix."""
    return text


@dataclass
class Snapshot:
    functions: dict[str, str] = field(default_factory=dict)
    func_lines: dict[str, int] = field(default_factory=dict)
    func_bodies: dict[str, str] = field(default_factory=dict)
    func_decorators: dict[str, list[str]] = field(default_factory=dict)
    classes: dict[str, str] = field(default_factory=dict)
    class_lines: dict[str, int] = field(default_factory=dict)
    class_bases: dict[str, list[str]] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)
    var_lines: dict[str, int] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)
    exports: list[str] = field(default_factory=list)


def _body_fingerprint(node: ast.AST) -> str:
    try:
        return ast.dump(
            ast.parse(ast.unparse(node)), annotate_fields=False, include_attributes=False
        )
    except Exception:  # pragma: no cover - defensive
        return ""


def _var_repr(value) -> str:
    """Type plus literal value, so constant edits show up in the diff."""
    kind = infer_literal_type(value)
    if isinstance(value, ast.Constant):
        return f"{kind} = {truncate(unparse(value), 40)}"
    return kind


def snapshot(pm: ParsedModule) -> Snapshot:
    snap = Snapshot()
    for fi in collect_functions(pm):
        key = fi.qualname
        snap.functions[key] = fi.signature()
        snap.func_lines[key] = fi.lineno
        snap.func_bodies[key] = _body_fingerprint(fi.node)
        snap.func_decorators[key] = fi.decorators
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ClassDef):
            key = pm.qualname(node)
            snap.classes[key] = class_kind_of(node)
            snap.class_lines[key] = node.lineno
            snap.class_bases[key] = [unparse(b) for b in node.bases]
    for stmt in pm.tree.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            snap.variables[stmt.target.id] = (
                f"{unparse(stmt.annotation)} = {_var_repr(stmt.value)}"
                if stmt.value is not None
                else unparse(stmt.annotation)
            )
            snap.var_lines[stmt.target.id] = stmt.lineno
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    snap.variables[t.id] = _var_repr(stmt.value)
                    snap.var_lines[t.id] = stmt.lineno
    for r in collect_imports(pm):
        snap.imports[r.binding] = r.source
    all_decl = dunder_all(pm)
    snap.exports = all_decl[0] if all_decl else []
    return snap


def _diff_maps(
    old: dict[str, str], new: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    return added, removed, changed


def diff_ast(old_path: str, new_path: str) -> str:
    old_pm = parse_file(old_path)
    new_pm = parse_file(new_path)
    a, b = snapshot(old_pm), snapshot(new_pm)

    out = [header("diff_ast", f"{old_pm.path} -> {new_pm.path}")]
    total_changes = 0

    # functions
    added, removed, changed = _diff_maps(a.functions, b.functions)
    body_only = [
        k
        for k in set(a.functions) & set(b.functions)
        if k not in changed and a.func_bodies.get(k) != b.func_bodies.get(k)
    ]
    dec_changed = [
        k
        for k in set(a.functions) & set(b.functions)
        if a.func_decorators.get(k) != b.func_decorators.get(k)
    ]
    total_changes += len(added) + len(removed) + len(changed) + len(body_only)
    out.append(section("functions"))
    if not (added or removed or changed or body_only or dec_changed):
        out.append("(unchanged)")
    for k in added:
        out.append(_line(f"+ {k}  {b.functions[k]}  @L{b.func_lines[k]}"))
    for k in removed:
        out.append(_line(f"- {k}  {a.functions[k]}  @L{a.func_lines[k]}"))
    for k in changed:
        out.append(_line(f"~ {k}  signature changed  @L{b.func_lines[k]}"))
        out.append(_line(f"    old: {a.functions[k]}"))
        out.append(_line(f"    new: {b.functions[k]}"))
    for k in dec_changed:
        out.append(
            _line(f"~ {k}  decorators {a.func_decorators[k]} -> {b.func_decorators[k]}")
        )
    for k in sorted(body_only):
        out.append(_line(f"~ {k}  body changed (same signature)  @L{b.func_lines[k]}"))

    # classes
    added, removed, changed = _diff_maps(a.classes, b.classes)
    base_changed = [
        k
        for k in set(a.classes) & set(b.classes)
        if a.class_bases.get(k) != b.class_bases.get(k)
    ]
    total_changes += len(added) + len(removed) + len(changed) + len(base_changed)
    out.append(section("classes"))
    if not (added or removed or changed or base_changed):
        out.append("(unchanged)")
    for k in added:
        out.append(_line(f"+ {k}  ({b.classes[k]})  @L{b.class_lines[k]}"))
    for k in removed:
        out.append(_line(f"- {k}  ({a.classes[k]})  @L{a.class_lines[k]}"))
    for k in changed:
        out.append(_line(f"~ {k}  kind {a.classes[k]} -> {b.classes[k]}"))
    for k in base_changed:
        out.append(
            _line(f"~ {k}  bases {a.class_bases[k] or '-'} -> {b.class_bases[k] or '-'}")
        )

    # method-level detail per surviving class
    method_notes: list[str] = []
    for cls in sorted(set(a.classes) & set(b.classes)):
        prefix = cls + "."
        old_m = {k[len(prefix):]: v for k, v in a.functions.items() if k.startswith(prefix)}
        new_m = {k[len(prefix):]: v for k, v in b.functions.items() if k.startswith(prefix)}
        ma, mr, mc = _diff_maps(old_m, new_m)
        for k in ma:
            method_notes.append(f"+ {cls}.{k}  {new_m[k]}")
        for k in mr:
            method_notes.append(f"- {cls}.{k}  {old_m[k]}")
        for k in mc:
            method_notes.append(f"~ {cls}.{k}  {old_m[k]}  ->  {new_m[k]}")
    if method_notes:
        out.append(section("methods"))
        out.extend(_line(m) for m in method_notes)

    # variables
    added, removed, changed = _diff_maps(a.variables, b.variables)
    total_changes += len(added) + len(removed) + len(changed)
    out.append(section("module variables"))
    if not (added or removed or changed):
        out.append("(unchanged)")
    for k in added:
        out.append(_line(f"+ {k}: {b.variables[k]}  @L{b.var_lines[k]}"))
    for k in removed:
        out.append(_line(f"- {k}: {a.variables[k]}  @L{a.var_lines[k]}"))
    for k in changed:
        out.append(_line(f"~ {k}: {a.variables[k]} -> {b.variables[k]}"))

    # imports
    added, removed, changed = _diff_maps(a.imports, b.imports)
    out.append(section("imports"))
    if not (added or removed or changed):
        out.append("(unchanged)")
    for k in added:
        out.append(_line(f"+ {k} <- {b.imports[k]}"))
    for k in removed:
        out.append(_line(f"- {k} <- {a.imports[k]}"))
    for k in changed:
        out.append(_line(f"~ {k}: {a.imports[k]} -> {b.imports[k]}"))

    if a.exports != b.exports:
        out.append(section("__all__"))
        for k in sorted(set(b.exports) - set(a.exports)):
            out.append(_line(f"+ {k}"))
        for k in sorted(set(a.exports) - set(b.exports)):
            out.append(_line(f"- {k}"))

    out.insert(1, f"structural changes: {total_changes}")
    breaking = [
        k for k in set(a.functions) - set(b.functions) if not k.startswith("_")
    ] + [k for k in set(a.classes) - set(b.classes) if not k.startswith("_")]
    if breaking:
        out.append(section("potentially breaking (public symbols removed)"))
        out.append(", ".join(sorted(breaking)))
    return "\n".join(out)
