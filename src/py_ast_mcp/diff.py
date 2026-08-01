"""Structural (signature-level) diff between two Python files."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .format import header, section, truncate, unparse
from .functions import collect_functions
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


def _functions_section(a: Snapshot, b: Snapshot) -> tuple[list[str], int]:
    added, removed, changed = _diff_maps(a.functions, b.functions)
    both = set(a.functions) & set(b.functions)
    body_only = [
        k for k in both
        if k not in changed and a.func_bodies.get(k) != b.func_bodies.get(k)
    ]
    dec_changed = [
        k for k in both if a.func_decorators.get(k) != b.func_decorators.get(k)
    ]
    out = [section("functions")]
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
    return out, len(added) + len(removed) + len(changed) + len(body_only)


def _classes_section(a: Snapshot, b: Snapshot) -> tuple[list[str], int]:
    added, removed, changed = _diff_maps(a.classes, b.classes)
    base_changed = [
        k for k in set(a.classes) & set(b.classes)
        if a.class_bases.get(k) != b.class_bases.get(k)
    ]
    out = [section("classes")]
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
    return out, len(added) + len(removed) + len(changed) + len(base_changed)


def _methods_section(a: Snapshot, b: Snapshot) -> list[str]:
    """Per-class method changes, for classes present in both versions."""
    notes: list[str] = []
    for cls in sorted(set(a.classes) & set(b.classes)):
        prefix = cls + "."
        old_m = {k[len(prefix):]: v for k, v in a.functions.items() if k.startswith(prefix)}
        new_m = {k[len(prefix):]: v for k, v in b.functions.items() if k.startswith(prefix)}
        ma, mr, mc = _diff_maps(old_m, new_m)
        for k in ma:
            notes.append(f"+ {cls}.{k}  {new_m[k]}")
        for k in mr:
            notes.append(f"- {cls}.{k}  {old_m[k]}")
        for k in mc:
            notes.append(f"~ {cls}.{k}  {old_m[k]}  ->  {new_m[k]}")
    if not notes:
        return []
    return [section("methods"), *(_line(m) for m in notes)]


def _variables_section(a: Snapshot, b: Snapshot) -> tuple[list[str], int]:
    added, removed, changed = _diff_maps(a.variables, b.variables)
    out = [section("module variables")]
    if not (added or removed or changed):
        out.append("(unchanged)")
    for k in added:
        out.append(_line(f"+ {k}: {b.variables[k]}  @L{b.var_lines[k]}"))
    for k in removed:
        out.append(_line(f"- {k}: {a.variables[k]}  @L{a.var_lines[k]}"))
    for k in changed:
        out.append(_line(f"~ {k}: {a.variables[k]} -> {b.variables[k]}"))
    return out, len(added) + len(removed) + len(changed)


def _imports_section(a: Snapshot, b: Snapshot) -> list[str]:
    """Import changes. Deliberately not counted as structural changes."""
    added, removed, changed = _diff_maps(a.imports, b.imports)
    out = [section("imports")]
    if not (added or removed or changed):
        out.append("(unchanged)")
    for k in added:
        out.append(_line(f"+ {k} <- {b.imports[k]}"))
    for k in removed:
        out.append(_line(f"- {k} <- {a.imports[k]}"))
    for k in changed:
        out.append(_line(f"~ {k}: {a.imports[k]} -> {b.imports[k]}"))
    return out


def _exports_section(a: Snapshot, b: Snapshot) -> list[str]:
    if a.exports == b.exports:
        return []
    out = [section("__all__")]
    for k in sorted(set(b.exports) - set(a.exports)):
        out.append(_line(f"+ {k}"))
    for k in sorted(set(a.exports) - set(b.exports)):
        out.append(_line(f"- {k}"))
    return out


def _breaking_section(a: Snapshot, b: Snapshot) -> list[str]:
    """Public functions and classes that disappeared."""
    breaking = [
        k for k in set(a.functions) - set(b.functions) if not k.startswith("_")
    ] + [k for k in set(a.classes) - set(b.classes) if not k.startswith("_")]
    if not breaking:
        return []
    return [
        section("potentially breaking (public symbols removed)"),
        ", ".join(sorted(breaking)),
    ]


def diff_ast(old_path: str, new_path: str) -> str:
    old_pm = parse_file(old_path)
    new_pm = parse_file(new_path)
    a, b = snapshot(old_pm), snapshot(new_pm)

    fn_lines, fn_n = _functions_section(a, b)
    cls_lines, cls_n = _classes_section(a, b)
    var_lines, var_n = _variables_section(a, b)

    out = [
        header("diff_ast", f"{old_pm.path} -> {new_pm.path}"),
        f"structural changes: {fn_n + cls_n + var_n}",
        *fn_lines,
        *cls_lines,
        *_methods_section(a, b),
        *var_lines,
        *_imports_section(a, b),
        *_exports_section(a, b),
        *_breaking_section(a, b),
    ]
    return "\n".join(out)
