"""Type-shaped declarations: classes, enums, protocols, TypedDicts, aliases."""

from __future__ import annotations

import ast

from .format import bullet, empty, header, loc, plural, section, truncate, unparse
from .parse import AstToolError, ParsedModule, parse_file

__all__ = [
    "classify_class",
    "class_kind_of",
    "get_type_definition",
    "list_declarations",
    "infer_literal_type",
    "is_type_alias",
]

_KIND_BY_BASE = {
    "Protocol": "protocol",
    "typing.Protocol": "protocol",
    "t.Protocol": "protocol",
    "TypedDict": "typeddict",
    "typing.TypedDict": "typeddict",
    "NamedTuple": "namedtuple",
    "typing.NamedTuple": "namedtuple",
    "Enum": "enum",
    "IntEnum": "enum",
    "StrEnum": "enum",
    "Flag": "enum",
    "IntFlag": "enum",
    "enum.Enum": "enum",
    "enum.IntEnum": "enum",
    "enum.StrEnum": "enum",
    "ABC": "abc",
    "abc.ABC": "abc",
    "Exception": "exception",
    "BaseException": "exception",
}


def class_kind_of(node: ast.ClassDef) -> str:
    """Best-effort classification of a ClassDef."""
    decs = {unparse(d.func if isinstance(d, ast.Call) else d) for d in node.decorator_list}
    if any(d.split(".")[-1] == "dataclass" for d in decs):
        return "dataclass"
    for base in node.bases:
        text = unparse(base)
        stripped = text.split("[")[0]
        kind = _KIND_BY_BASE.get(stripped) or _KIND_BY_BASE.get(stripped.split(".")[-1])
        if kind:
            return kind
        if stripped.endswith("Error") or stripped.endswith("Exception"):
            return "exception"
    for kw in node.keywords:
        if kw.arg == "metaclass" and "ABCMeta" in unparse(kw.value):
            return "abc"
    return "class"


def classify_class(node: ast.ClassDef) -> tuple[str, list[str]]:
    return class_kind_of(node), [unparse(b) for b in node.bases]


def is_type_alias(stmt: ast.stmt) -> bool:
    """``X: TypeAlias = ...``, ``type X = ...`` (3.12) or a bare typing alias."""
    if hasattr(ast, "TypeAlias") and isinstance(stmt, getattr(ast, "TypeAlias")):
        return True
    if isinstance(stmt, ast.AnnAssign) and stmt.annotation is not None:
        return unparse(stmt.annotation).split(".")[-1] == "TypeAlias"
    if isinstance(stmt, ast.Assign) and isinstance(stmt.value, (ast.Subscript, ast.Call)):
        text = unparse(stmt.value)
        head = text.split("[")[0].split("(")[0].split(".")[-1]
        return head in {
            "Union",
            "Optional",
            "Literal",
            "Callable",
            "TypeVar",
            "NewType",
            "NamedTuple",
            "TypedDict",
            "Annotated",
        }
    return False


_LITERAL_TYPES = {
    str: "str",
    bytes: "bytes",
    bool: "bool",
    int: "int",
    float: "float",
    complex: "complex",
    type(None): "None",
}


def infer_literal_type(value: ast.expr | None) -> str:
    """Very small literal-shaped type inference, mirroring what a reader sees."""
    if value is None:
        return "?"
    if isinstance(value, ast.Constant):
        return _LITERAL_TYPES.get(type(value.value), type(value.value).__name__)
    if isinstance(value, ast.JoinedStr):
        return "str"
    if isinstance(value, (ast.List, ast.ListComp)):
        return "list"
    if isinstance(value, (ast.Tuple,)):
        return "tuple"
    if isinstance(value, (ast.Set, ast.SetComp)):
        return "set"
    if isinstance(value, (ast.Dict, ast.DictComp)):
        return "dict"
    if isinstance(value, ast.GeneratorExp):
        return "Generator"
    if isinstance(value, ast.Lambda):
        return "Callable"
    if isinstance(value, ast.Call):
        func = value.func
        name = unparse(func)
        short = name.split(".")[-1]
        if short and (short[0].isupper() or short in {"dict", "list", "set", "tuple", "frozenset"}):
            return short
        return f"{short}(...)"
    if isinstance(value, ast.BinOp):
        return infer_literal_type(value.left)
    if isinstance(value, ast.Compare) or isinstance(value, ast.BoolOp):
        return "bool"
    if isinstance(value, ast.Name):
        return f"= {value.id}"
    return "?"


# --------------------------------------------------------------------------


def _find_type_node(pm: ParsedModule, name: str) -> tuple[str, ast.AST] | None:
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ClassDef) and (
            node.name == name or pm.qualname(node) == name
        ):
            return class_kind_of(node), node
    for stmt in pm.tree.body:
        if hasattr(ast, "TypeAlias") and isinstance(stmt, getattr(ast, "TypeAlias")):
            if unparse(stmt.name) == name:
                return "type alias", stmt
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id == name:
                kind = "type alias" if is_type_alias(stmt) else "annotated assignment"
                return kind, stmt
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    kind = "type alias" if is_type_alias(stmt) else "assignment"
                    return kind, stmt
    return None


def get_type_definition(path: str, name: str) -> str:
    pm = parse_file(path)
    found = _find_type_node(pm, name)
    if found is None:
        available = sorted(
            {n.name for n in ast.walk(pm.tree) if isinstance(n, ast.ClassDef)}
        )
        raise AstToolError(
            f"Type '{name}' not found in {pm.path}. "
            f"Classes here: {', '.join(available) or '(none)'}"
        )
    kind, node = found
    start = getattr(node, "lineno", 1)
    if isinstance(node, ast.ClassDef) and node.decorator_list:
        start = min([start] + [d.lineno for d in node.decorator_list])
    end = getattr(node, "end_lineno", start) or start
    out = [header(f"{kind} {name}", pm.path, loc(line=start, end=end))]

    if isinstance(node, ast.ClassDef):
        bases = [unparse(b) for b in node.bases]
        kws = [f"{k.arg}={unparse(k.value)}" for k in node.keywords if k.arg]
        if bases or kws:
            out.append("bases: " + ", ".join(bases + kws))
        doc = ast.get_docstring(node)
        if doc:
            out.append(f'doc: "{truncate(doc, 140)}"')
        members: list[str] = []
        for s in node.body:
            if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
                members.append(
                    f"[{loc(s)}] {s.target.id}: {unparse(s.annotation)}"
                    + (f" = {truncate(unparse(s.value), 50)}" if s.value else "")
                )
            elif isinstance(s, ast.Assign):
                for t in s.targets:
                    if isinstance(t, ast.Name):
                        members.append(
                            f"[{loc(s)}] {t.id} = {truncate(unparse(s.value), 50)}"
                        )
            elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                members.append(
                    f"[{loc(s)}] {'async ' if isinstance(s, ast.AsyncFunctionDef) else ''}"
                    f"def {s.name}(...)"
                )
        if members:
            out.append(section(f"members ({len(members)})"))
            out.extend(bullet(m) for m in members)
    out.append(section("source"))
    out.append(pm.numbered(start, end))
    return "\n".join(out)


def list_declarations(path: str) -> str:
    pm = parse_file(path)
    rows: list[str] = []
    for stmt in pm.tree.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            ann = unparse(stmt.annotation)
            val = truncate(unparse(stmt.value), 60) if stmt.value is not None else None
            tag = " [TypeAlias]" if is_type_alias(stmt) else ""
            rows.append(
                f"[{loc(stmt)}] {stmt.target.id}: {ann}{tag}"
                + (f" = {val}" if val else "  (declaration only)")
            )
        elif isinstance(stmt, ast.Assign):
            inferred = infer_literal_type(stmt.value)
            tag = " [TypeAlias]" if is_type_alias(stmt) else ""
            for t in stmt.targets:
                names = []
                if isinstance(t, ast.Name):
                    names = [t.id]
                elif isinstance(t, (ast.Tuple, ast.List)):
                    names = [e.id for e in t.elts if isinstance(e, ast.Name)]
                for n in names:
                    rows.append(
                        f"[{loc(stmt)}] {n}: {inferred}{tag} = "
                        f"{truncate(unparse(stmt.value), 60)}"
                    )
        elif hasattr(ast, "TypeAlias") and isinstance(stmt, getattr(ast, "TypeAlias")):
            rows.append(
                f"[{loc(stmt)}] {unparse(stmt.name)} [TypeAlias] = "
                f"{truncate(unparse(stmt.value), 60)}"
            )
    out = [header("module-level declarations", pm.path, plural(len(rows), "declaration"))]
    out.append("\n".join(bullet(r) for r in rows) if rows else empty("declarations"))
    return "\n".join(out)
