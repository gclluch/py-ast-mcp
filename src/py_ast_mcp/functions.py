"""Function/method discovery: signatures, bodies, methods of a class."""

from __future__ import annotations

import ast
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .format import bullet, empty, header, loc, plural, section, truncate, unparse
from .parse import AstToolError, ParsedModule, parse_file

FuncNode = ast.FunctionDef | ast.AsyncFunctionDef

__all__ = [
    "Param",
    "FuncInfo",
    "iter_functions",
    "collect_functions",
    "build_func_info",
    "render_signature",
    "find_function",
    "list_functions",
    "get_function_body",
    "list_methods",
    "decorator_names",
]


@dataclass
class Param:
    name: str
    annotation: str | None = None
    default: str | None = None
    kind: str = "arg"  # posonly | arg | vararg | kwonly | kwarg

    def render(self) -> str:
        prefix = {"vararg": "*", "kwarg": "**"}.get(self.kind, "")
        s = f"{prefix}{self.name}"
        if self.annotation:
            s += f": {self.annotation}"
        if self.default is not None:
            s += f" = {self.default}" if self.annotation else f"={self.default}"
        return s


@dataclass
class FuncInfo:
    node: FuncNode
    name: str
    qualname: str
    is_async: bool
    params: list[Param]
    returns: str | None
    decorators: list[str]
    lineno: int
    end_lineno: int
    docstring: str | None
    class_name: str | None = None
    nested_in: str | None = None
    body_start: int = 0

    @property
    def kind(self) -> str:
        decs = set(self.decorators)
        if "staticmethod" in decs:
            return "staticmethod"
        if "classmethod" in decs:
            return "classmethod"
        if "property" in decs or any(d.endswith(".setter") for d in decs):
            return "property"
        if any(d.endswith(".getter") or d.endswith(".deleter") for d in decs):
            return "property"
        if self.class_name:
            return "method"
        return "function"

    @property
    def is_abstract(self) -> bool:
        return any("abstractmethod" in d for d in self.decorators)

    @property
    def nlines(self) -> int:
        return self.end_lineno - self.lineno + 1

    def signature(self, qualified: bool = False) -> str:
        return render_signature(self, qualified=qualified)


def decorator_names(node: ast.AST) -> list[str]:
    out: list[str] = []
    for dec in getattr(node, "decorator_list", []) or []:
        target = dec.func if isinstance(dec, ast.Call) else dec
        out.append(unparse(target))
    return out


def _params_of(node: FuncNode) -> list[Param]:
    a = node.args
    params: list[Param] = []

    posonly = list(a.posonlyargs)
    normal = list(a.args)
    positional = posonly + normal
    defaults = list(a.defaults)
    pad = len(positional) - len(defaults)
    for i, arg in enumerate(positional):
        default = None
        if i >= pad:
            default = unparse(defaults[i - pad])
        params.append(
            Param(
                name=arg.arg,
                annotation=unparse(arg.annotation) or None,
                default=default,
                kind="posonly" if i < len(posonly) else "arg",
            )
        )
    if a.vararg:
        params.append(
            Param(
                name=a.vararg.arg,
                annotation=unparse(a.vararg.annotation) or None,
                kind="vararg",
            )
        )
    for arg, dflt in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        params.append(
            Param(
                name=arg.arg,
                annotation=unparse(arg.annotation) or None,
                default=unparse(dflt) if dflt is not None else None,
                kind="kwonly",
            )
        )
    if a.kwarg:
        params.append(
            Param(
                name=a.kwarg.arg,
                annotation=unparse(a.kwarg.annotation) or None,
                kind="kwarg",
            )
        )
    return params


def render_signature(fi: FuncInfo, qualified: bool = False) -> str:
    parts: list[str] = []
    seen_posonly = False
    star_emitted = False
    for p in fi.params:
        if p.kind != "posonly" and seen_posonly:
            parts.append("/")
            seen_posonly = False
        if p.kind == "posonly":
            seen_posonly = True
        if p.kind == "kwonly" and not star_emitted:
            if not any(x.kind == "vararg" for x in fi.params):
                parts.append("*")
            star_emitted = True
        if p.kind == "vararg":
            star_emitted = True
        parts.append(p.render())
    if seen_posonly:
        parts.append("/")
    name = fi.qualname if qualified else fi.name
    sig = f"{'async ' if fi.is_async else ''}def {name}({', '.join(parts)})"
    if fi.returns:
        sig += f" -> {fi.returns}"
    return sig


def build_func_info(
    pm: ParsedModule,
    node: FuncNode,
    class_name: str | None = None,
    nested_in: str | None = None,
) -> FuncInfo:
    body_start = node.body[0].lineno if node.body else node.lineno
    return FuncInfo(
        node=node,
        name=node.name,
        qualname=pm.qualname(node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        params=_params_of(node),
        returns=unparse(node.returns) or None,
        decorators=decorator_names(node),
        lineno=min([node.lineno] + [d.lineno for d in node.decorator_list]),
        end_lineno=node.end_lineno or node.lineno,
        docstring=ast.get_docstring(node),
        class_name=class_name,
        nested_in=nested_in,
        body_start=body_start,
    )


def iter_functions(pm: ParsedModule, include_nested: bool = True) -> Iterator[FuncInfo]:
    """Yield every function/method in the module in source order."""

    def walk(
        body: Sequence[ast.stmt], class_name: str | None, func_name: str | None
    ) -> Iterator[FuncInfo]:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fi = build_func_info(pm, stmt, class_name, func_name)
                yield fi
                if include_nested:
                    yield from walk(stmt.body, None, fi.qualname)
            elif isinstance(stmt, ast.ClassDef):
                yield from walk(stmt.body, stmt.name, func_name)
            elif isinstance(
                stmt, (ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.While)
            ):
                yield from walk(stmt.body, class_name, func_name)
                for attr in ("orelse", "finalbody"):
                    yield from walk(
                        getattr(stmt, attr, []) or [], class_name, func_name
                    )
                for handler in getattr(stmt, "handlers", []) or []:
                    yield from walk(handler.body, class_name, func_name)

    yield from walk(pm.tree.body, None, None)


def collect_functions(pm: ParsedModule, include_nested: bool = True) -> list[FuncInfo]:
    return list(iter_functions(pm, include_nested=include_nested))


def find_function(pm: ParsedModule, name: str) -> FuncInfo:
    """Resolve ``name``, ``Class.method`` or a dotted nested path."""
    funcs = collect_functions(pm)
    exact = [f for f in funcs if f.qualname == name]
    if exact:
        return exact[0]
    if "." in name:
        owner, _, leaf = name.rpartition(".")
        cand = [f for f in funcs if f.name == leaf and (f.class_name == owner)]
        if cand:
            return cand[0]
        cand = [f for f in funcs if f.qualname.endswith("." + name)]
        if cand:
            return cand[0]
        # Inherited method: search base classes defined in this file.
        cls = _find_class(pm, owner)
        if cls is not None:
            for base in _base_names(cls):
                try:
                    return find_function(pm, f"{base}.{leaf}")
                except AstToolError:
                    continue
        raise AstToolError(f"Function '{name}' not found in {pm.path}")
    by_name = [f for f in funcs if f.name == name]
    if not by_name:
        raise AstToolError(
            f"Function '{name}' not found in {pm.path}. "
            f"Available: {', '.join(sorted({f.qualname for f in funcs})[:25]) or '(none)'}"
        )
    top = [f for f in by_name if not f.class_name and not f.nested_in]
    return top[0] if top else by_name[0]


def _find_class(pm: ParsedModule, name: str) -> ast.ClassDef | None:
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ClassDef) and (
            node.name == name or pm.qualname(node) == name
        ):
            return node
    return None


def _base_names(cls: ast.ClassDef) -> list[str]:
    return [unparse(b) for b in cls.bases]


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------


def list_functions(path: str) -> str:
    pm = parse_file(path)
    funcs = collect_functions(pm)
    if not funcs:
        return header("functions", pm.path) + "\n" + empty("functions")
    out = [
        header(
            "functions",
            pm.path,
            plural(len(funcs), "function") + " and methods",
        )
    ]
    current_class: str | None = "\0"
    for fi in funcs:
        if fi.class_name != current_class:
            current_class = fi.class_name
            if current_class:
                out.append(section(f"class {current_class}"))
            else:
                out.append(section("module level"))
        prefix = f"[{loc(line=fi.lineno, end=fi.end_lineno)}]"
        tags = []
        if fi.kind not in ("function", "method"):
            tags.append(fi.kind)
        if fi.is_abstract:
            tags.append("abstract")
        if fi.nested_in:
            tags.append(f"nested in {fi.nested_in}")
        tag = f"  ({', '.join(tags)})" if tags else ""
        out.append(bullet(f"{prefix} {fi.signature()}{tag}"))
        for dec in fi.decorators:
            out.append(bullet(f"@{dec}", 1))
        if fi.docstring:
            out.append(bullet(f'"{truncate(fi.docstring, 100)}"', 1))
    return "\n".join(out)


def get_function_body(path: str, name: str) -> str:
    pm = parse_file(path)
    fi = find_function(pm, name)
    out = [
        header(
            f"body of {fi.qualname}",
            pm.path,
            f"{loc(line=fi.lineno, end=fi.end_lineno)}, {plural(fi.nlines, 'line')}",
        ),
        fi.signature(qualified=True),
        "",
        pm.numbered(fi.lineno, fi.end_lineno),
    ]
    return "\n".join(out)


def list_methods(path: str, type: str) -> str:  # noqa: A002 - mirrors TS tool param
    pm = parse_file(path)
    cls = _find_class(pm, type)
    if cls is None:
        classes = [n.name for n in ast.walk(pm.tree) if isinstance(n, ast.ClassDef)]
        raise AstToolError(
            f"Class '{type}' not found in {pm.path}. "
            f"Available classes: {', '.join(classes) or '(none)'}"
        )
    bases = _base_names(cls)
    out = [
        header(
            f"methods of {cls.name}",
            pm.path,
            loc(cls),
        )
    ]
    if bases:
        out.append(f"bases: {', '.join(bases)}")

    own = [
        build_func_info(pm, s, cls.name)
        for s in cls.body
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    out.append(section(f"declared ({len(own)})"))
    if not own:
        out.append(empty("methods"))
    for fi in own:
        tags = [fi.kind] if fi.kind != "method" else []
        if fi.is_abstract:
            tags.append("abstract")
        if fi.is_async:
            tags.append("async")
        tag = f"  [{', '.join(tags)}]" if tags else ""
        out.append(
            bullet(f"[{loc(line=fi.lineno, end=fi.end_lineno)}] {fi.signature()}{tag}")
        )

    # class-level attributes
    attrs = []
    for s in cls.body:
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
            attrs.append(
                f"[{loc(s)}] {s.target.id}: {unparse(s.annotation)}"
                + (f" = {unparse(s.value)}" if s.value is not None else "")
            )
        elif isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name):
                    attrs.append(
                        f"[{loc(s)}] {t.id} = {truncate(unparse(s.value), 60)}"
                    )
    if attrs:
        out.append(section(f"class attributes ({len(attrs)})"))
        out.extend(bullet(a) for a in attrs)

    # inherited from bases visible in this file
    seen = {fi.name for fi in own}
    inherited: list[str] = []
    for base in bases:
        base_cls = _find_class(pm, base.split("[")[0])
        if base_cls is None:
            continue
        for s in base_cls.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if s.name in seen:
                    status = "overridden here"
                else:
                    status = "inherited"
                    seen.add(s.name)
                bfi = build_func_info(pm, s, base_cls.name)
                inherited.append(
                    f"[{loc(line=bfi.lineno, end=bfi.end_lineno)}] {base_cls.name}.{bfi.name} "
                    f"-> {bfi.signature()}  ({status})"
                )
    if inherited:
        out.append(section(f"from base classes in this file ({len(inherited)})"))
        out.extend(bullet(i) for i in inherited)
    unresolved = [b for b in bases if _find_class(pm, b.split("[")[0]) is None]
    if unresolved:
        out.append(
            section("unresolved bases")
            + "\n"
            + bullet(
                f"{', '.join(unresolved)} (defined outside {pm.path}; members not listed)"
            )
        )
    return "\n".join(out)
