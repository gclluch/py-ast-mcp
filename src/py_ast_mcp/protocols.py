"""Find classes implementing a Protocol / ABC, explicitly or structurally."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .format import bullet, header, loc, plural, section, unparse
from .parse import (
    AstToolError,
    ParseError,
    ParsedModule,
    containing_dir,
    iter_py_files,
    parse_file,
    resolve_path,
)
from .types import class_kind_of

__all__ = ["find_implementations"]


@dataclass
class ClassRec:
    name: str
    node: ast.ClassDef
    file: str
    bases: list[str]
    methods: dict[str, ast.AST] = field(default_factory=dict)
    attributes: set[str] = field(default_factory=set)
    kind: str = "class"


def _class_records(pm: ParsedModule) -> list[ClassRec]:
    out: list[ClassRec] = []
    for node in ast.walk(pm.tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods: dict[str, ast.AST] = {}
        attrs: set[str] = set()
        for s in node.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[s.name] = s
            elif isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
                attrs.add(s.target.id)
            elif isinstance(s, ast.Assign):
                attrs.update(t.id for t in s.targets if isinstance(t, ast.Name))
        out.append(
            ClassRec(
                name=node.name,
                node=node,
                file=pm.path,
                bases=[unparse(b) for b in node.bases],
                methods=methods,
                attributes=attrs,
                kind=class_kind_of(node),
            )
        )
    return out


def _required_members(rec: ClassRec) -> tuple[set[str], set[str]]:
    """Members a structural implementer must provide (methods, attributes)."""
    methods = {
        n
        for n in rec.methods
        if not (n.startswith("__") and n.endswith("__") and n != "__call__")
    }
    return methods, set(rec.attributes)


def find_implementations(path: str, protocol: str) -> str:
    root = Path(resolve_path(path))
    files = list(iter_py_files(containing_dir(str(root)), include_tests=True))
    if root.is_file() and root not in files:
        files.append(root)
    records: list[ClassRec] = []
    errors: list[str] = []
    for f in files:
        try:
            pm = parse_file(str(f))
        except ParseError as exc:
            errors.append(f"{f}: {exc.message}")
            continue
        records.extend(_class_records(pm))

    target = next((r for r in records if r.name == protocol), None)
    if target is None:
        raise AstToolError(
            f"Protocol/ABC '{protocol}' not found under {containing_dir(str(root))}. "
            f"Known classes: {', '.join(sorted({r.name for r in records})[:30])}"
        )
    req_methods, req_attrs = _required_members(target)

    explicit: list[tuple[ClassRec, str]] = []
    structural: list[tuple[ClassRec, set[str]]] = []
    partial: list[tuple[ClassRec, set[str], set[str]]] = []

    # transitive explicit subclasses
    by_name = {r.name: r for r in records}
    def bases_of(rec: ClassRec) -> set[str]:
        return {b.split("[")[0].split(".")[-1] for b in rec.bases}

    changed = True
    explicit_names: set[str] = set()
    while changed:
        changed = False
        for r in records:
            if r.name == protocol or r.name in explicit_names:
                continue
            hits = bases_of(r)
            if protocol in hits or (hits & explicit_names):
                explicit_names.add(r.name)
                changed = True
    for r in records:
        if r.name in explicit_names:
            direct = protocol in bases_of(r)
            explicit.append((r, "direct base" if direct else "indirect subclass"))

    for r in records:
        if r.name == protocol or r.name in explicit_names:
            continue
        have = set(r.methods) | r.attributes
        for b in bases_of(r):
            parent = by_name.get(b)
            if parent:
                have |= set(parent.methods) | parent.attributes
        missing = (req_methods | req_attrs) - have
        if not missing and (req_methods or req_attrs):
            structural.append((r, req_methods | req_attrs))
        elif req_methods and len(missing) <= max(1, len(req_methods) // 3):
            partial.append((r, (req_methods | req_attrs) - missing, missing))

    base = containing_dir(str(root))
    out = [
        header(
            f"implementations of {protocol}",
            str(base),
            f"{target.kind} declared at {Path(target.file).name}:{target.node.lineno}",
        )
    ]
    out.append(
        "required members: "
        + (", ".join(sorted(req_methods | req_attrs)) or "(none — matches everything)")
    )
    if errors:
        out.append(section("unparseable"))
        out.extend(bullet(e) for e in errors)

    out.append(section(f"explicit ({len(explicit)})"))
    if explicit:
        for r, why in sorted(explicit, key=lambda x: (x[0].file, x[0].node.lineno)):
            missing = (req_methods | req_attrs) - (set(r.methods) | r.attributes)
            note = f"  missing: {', '.join(sorted(missing))}" if missing else ""
            out.append(
                bullet(
                    f"{Path(r.file).name}:{r.node.lineno} {r.name} "
                    f"({why}; bases: {', '.join(r.bases) or '-'}){note}"
                )
            )
    else:
        out.append("(none)")

    out.append(section(f"structural ({len(structural)})"))
    if structural:
        for r, members in sorted(structural, key=lambda x: (x[0].file, x[0].node.lineno)):
            out.append(
                bullet(
                    f"{Path(r.file).name}:{r.node.lineno} {r.name} "
                    f"— defines all of {', '.join(sorted(members))}"
                )
            )
    else:
        out.append("(none)")

    if partial:
        out.append(section(f"near misses ({len(partial)})"))
        for r, have, missing in sorted(partial, key=lambda x: x[0].name):
            out.append(
                bullet(
                    f"{Path(r.file).name}:{r.node.lineno} {r.name} "
                    f"— missing {', '.join(sorted(missing))}"
                )
            )
    return "\n".join(out)
