"""Call graph extraction and Mermaid rendering."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .format import bullet, empty, header, plural, section, unparse
from .functions import FuncInfo, collect_functions
from .imports import collect_imports
from .parse import (
    AstToolError,
    ParsedModule,
    ParseError,
    containing_dir,
    iter_py_files,
    parse_file,
    resolve_path,
)

__all__ = ["call_graph", "get_callers", "build_graph", "CallGraph"]

_DIRECTIONS = {"TD", "TB", "LR", "RL", "BT"}


@dataclass
class Edge:
    caller: str
    callee: str
    lineno: int
    external: bool


@dataclass
class CallGraph:
    nodes: dict[str, FuncInfo] = field(default_factory=dict)
    node_file: dict[str, str] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    externals: set[str] = field(default_factory=set)
    classes: dict[str, set[str]] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def out_edges(self, node: str) -> list[Edge]:
        return [e for e in self.edges if e.caller == node]

    def in_edges(self, node: str) -> list[Edge]:
        return [e for e in self.edges if e.callee == node]


def _module_key(path: str, base: Path | None) -> str:
    p = Path(path)
    if base is not None:
        try:
            return p.relative_to(base).with_suffix("").as_posix().replace("/", ".")
        except ValueError:
            pass
    return p.stem


def _index_module(pm: ParsedModule, prefix: str, graph: CallGraph) -> dict[str, str]:
    """Register every function of ``pm`` and return local-name -> node-id map."""
    local: dict[str, str] = {}
    for fi in collect_functions(pm):
        node_id = f"{prefix}:{fi.qualname}" if prefix else fi.qualname
        graph.nodes[node_id] = fi
        graph.node_file[node_id] = pm.path
        local[fi.qualname] = node_id
        local.setdefault(fi.name, node_id)
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ClassDef):
            methods = {
                s.name
                for s in node.body
                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            graph.classes.setdefault(node.name, set()).update(methods)
    return local


class _CallVisitor(ast.NodeVisitor):
    def __init__(
        self,
        pm: ParsedModule,
        prefix: str,
        graph: CallGraph,
        local: dict[str, str],
        cross: dict[str, str],
    ) -> None:
        self.pm = pm
        self.prefix = prefix
        self.graph = graph
        self.local = local
        self.cross = cross
        self.stack: list[str] = []
        self.class_stack: list[str] = []
        self.imported = {r.binding: r for r in collect_imports(pm)}

    # scope tracking ------------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qual = self.pm.qualname(node)
        node_id = self.local.get(qual)
        self.stack.append(node_id or qual)
        for dec in node.decorator_list:
            self.visit(dec)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _visit_func  # type: ignore[assignment]
    visit_AsyncFunctionDef = _visit_func  # type: ignore[assignment]

    # call handling -------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        caller = (
            self.stack[-1]
            if self.stack
            else f"{self.prefix}:<module>"
            if self.prefix
            else "<module>"
        )
        target, external = self._resolve(node.func)
        if target:
            self.graph.edges.append(Edge(caller, target, node.lineno, external))
            if external:
                self.graph.externals.add(target)
        self.generic_visit(node)

    def _lookup(self, name: str) -> str | None:
        if name in self.local:
            return self.local[name]
        rec = self.imported.get(name)
        if rec is not None:
            key = f"{rec.module}.{rec.name}" if rec.is_from else rec.module
            if key in self.cross:
                return self.cross[key]
            base = (rec.module or "").split(".")[-1]
            alt = f"{base}.{rec.name}" if rec.is_from else base
            if alt in self.cross:
                return self.cross[alt]
        return None

    def _resolve(self, func: ast.expr) -> tuple[str | None, bool]:
        if isinstance(func, ast.Name):
            hit = self._lookup(func.id)
            if hit:
                return hit, False
            if func.id in self.graph.classes:
                init = self._lookup(f"{func.id}.__init__")
                if init:
                    return init, False
            return func.id, True
        if isinstance(func, ast.Attribute):
            attr = func.attr
            if isinstance(func.value, ast.Name) and func.value.id in ("self", "cls"):
                if self.class_stack:
                    hit = self._lookup(f"{self.class_stack[-1]}.{attr}")
                    if hit:
                        return hit, False
                    # look through bases declared in the same module
                    for cls_name, methods in self.graph.classes.items():
                        if attr in methods:
                            hit = self._lookup(f"{cls_name}.{attr}")
                            if hit:
                                return hit, False
                return f"self.{attr}", True
            owner = unparse(func.value)
            if owner in self.graph.classes:
                hit = self._lookup(f"{owner}.{attr}")
                if hit:
                    return hit, False
            hit = self._lookup(attr) if attr in self.local else None
            if hit:
                return hit, False
            return f"{owner}.{attr}" if owner else attr, True
        if isinstance(func, ast.Lambda):
            return None, False
        text = unparse(func)
        return (text or None), True


def build_graph(
    path: str, scope: str = "file", include_tests: bool = False
) -> CallGraph:
    graph = CallGraph()
    if scope == "package":
        root = containing_dir(path)
        files = list(iter_py_files(root, include_tests=include_tests, recursive=True))
        base = root
    else:
        files = [Path(resolve_path(path))]
        base = None
    modules: list[tuple[ParsedModule, str, dict[str, str]]] = []
    cross: dict[str, str] = {}
    for f in files:
        try:
            pm = parse_file(str(f))
        except ParseError as exc:
            graph.errors.append(exc.render().splitlines()[0])
            continue
        prefix = _module_key(str(f), base) if scope == "package" else ""
        local = _index_module(pm, prefix, graph)
        modules.append((pm, prefix, local))
        graph.files.append(pm.path)
        if prefix:
            for qual, node_id in local.items():
                cross.setdefault(f"{prefix}.{qual}", node_id)
                cross.setdefault(f"{prefix.split('.')[-1]}.{qual}", node_id)
    for pm, prefix, local in modules:
        _CallVisitor(pm, prefix, graph, local, cross).visit(pm.tree)
    return graph


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_SAFE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _mermaid_id(name: str, cache: dict[str, str]) -> str:
    if name in cache:
        return cache[name]
    slug = "".join(c if c in _SAFE else "_" for c in name)
    ident = f"n{len(cache)}_{slug}"[:60]
    cache[name] = ident
    return ident


def _label(graph: CallGraph, node: str) -> str:
    fi = graph.nodes.get(node)
    if fi is None:
        return node.replace('"', "'")
    name = node.split(":", 1)[-1]
    mod = node.split(":", 1)[0] if ":" in node else ""
    text = f"{mod}.{name}" if mod else name
    if fi.is_async:
        text = "async " + text
    return f"{text} L{fi.lineno}".replace('"', "'")


def _reachable(graph: CallGraph, start: str, reverse: bool = False) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        cur = stack.pop()
        edges = graph.in_edges(cur) if reverse else graph.out_edges(cur)
        for e in edges:
            nxt = e.caller if reverse else e.callee
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _resolve_start(graph: CallGraph, function: str) -> str:
    if function in graph.nodes:
        return function
    matches = [
        nid
        for nid, fi in graph.nodes.items()
        if fi.qualname == function
        or fi.name == function
        or nid.endswith(":" + function)
    ]
    if not matches:
        raise AstToolError(
            f"Function '{function}' not found in graph. "
            f"Known: {', '.join(sorted(fi.qualname for fi in graph.nodes.values())[:25])}"
        )
    exact = [m for m in matches if graph.nodes[m].qualname == function]
    return (exact or matches)[0]


def call_graph(
    path: str,
    function: str | None = None,
    direction: str = "TD",
    include_external: bool = False,
    scope: str = "file",
) -> str:
    direction = (direction or "TD").upper()
    if direction not in _DIRECTIONS:
        raise AstToolError(
            f"direction must be one of {sorted(_DIRECTIONS)}, got {direction!r}"
        )
    if scope not in ("file", "package"):
        raise AstToolError("scope must be 'file' or 'package'")
    graph = build_graph(path, scope=scope)

    keep: set[str] | None = None
    start = None
    if function:
        start = _resolve_start(graph, function)
        keep = _reachable(graph, start)

    edges: list[Edge] = []
    seen_pairs: set[tuple[str, str]] = set()
    for e in graph.edges:
        if not include_external and e.external:
            continue
        if keep is not None and e.caller not in keep:
            continue
        if (e.caller, e.callee) in seen_pairs:
            continue
        seen_pairs.add((e.caller, e.callee))
        edges.append(e)

    title = f"call_graph ({scope})"
    extra = f"{plural(len(graph.nodes), 'function')}, {plural(len(edges), 'edge')}"
    if function:
        extra += f", rooted at {function}"
    out = [header(title, path, extra)]
    if graph.errors:
        out.append("skipped unparseable files:")
        out.extend(bullet(e) for e in graph.errors)

    ids: dict[str, str] = {}
    lines = [f"flowchart {direction}"]
    involved: set[str] = set()
    for e in edges:
        involved.add(e.caller)
        involved.add(e.callee)
    if keep is not None:
        involved |= {start} if start else set()

    for node in sorted(involved):
        nid = _mermaid_id(node, ids)
        if node in graph.nodes:
            lines.append(f'    {nid}["{_label(graph, node)}"]')
        else:
            lines.append(f'    {nid}(["{node}"])')
    for e in edges:
        a = _mermaid_id(e.caller, ids)
        b = _mermaid_id(e.callee, ids)
        arrow = "-.->" if e.external else "-->"
        lines.append(f"    {a} {arrow} {b}")
    if graph.externals and include_external:
        ext_ids = [
            _mermaid_id(x, ids) for x in sorted(graph.externals) if x in involved
        ]
        if ext_ids:
            lines.append(f"    class {','.join(ext_ids)} external;")
            lines.append(
                "    classDef external fill:#eee,stroke:#999,stroke-dasharray:3 3;"
            )

    out.append(section("mermaid"))
    out.append("```mermaid")
    out.append("\n".join(lines))
    out.append("```")

    if not edges:
        out.append(
            "\n(no calls found"
            + (" between functions defined here" if not include_external else "")
            + "; try include_external=true or scope='package')"
        )

    orphans = sorted(
        nid
        for nid in graph.nodes
        if nid not in involved and (keep is None or nid in keep)
    )
    if orphans:
        out.append(section(f"uncalled / non-calling functions ({len(orphans)})"))
        out.append(", ".join(n.split(":", 1)[-1] for n in orphans[:60]))

    out.append(section("edges"))
    if edges:
        for e in sorted(edges, key=lambda x: (x.caller, x.lineno)):
            mark = " (external)" if e.external else ""
            out.append(
                bullet(
                    f"{e.caller.split(':', 1)[-1]} -> {e.callee.split(':', 1)[-1]}"
                    f"  @L{e.lineno}{mark}"
                )
            )
    else:
        out.append(empty("edges"))
    return "\n".join(out)


def get_callers(path: str, function: str, scope: str = "file") -> str:
    if scope not in ("file", "package"):
        raise AstToolError("scope must be 'file' or 'package'")
    graph = build_graph(path, scope=scope)
    target = _resolve_start(graph, function)
    fi = graph.nodes[target]
    out = [
        header(
            f"callers of {fi.qualname}",
            path,
            f"scope={scope}, defined at L{fi.lineno}",
        )
    ]
    direct = graph.in_edges(target)
    if not direct:
        out.append(
            "\nNo callers found in this "
            + ("package" if scope == "package" else "file")
            + ". It may be an entry point, a callback, or called dynamically."
        )
    else:
        out.append(section(f"direct callers ({len(direct)})"))
        for e in sorted(direct, key=lambda x: (x.caller, x.lineno)):
            cfi = graph.nodes.get(e.caller)
            where = graph.node_file.get(e.caller, path)
            label = e.caller.split(":", 1)[-1]
            extra = f" [{Path(where).name}]" if scope == "package" else ""
            out.append(bullet(f"{label}{extra} calls it at L{e.lineno}"))
            if cfi:
                out.append(bullet(f"defined {cfi.signature()} @L{cfi.lineno}", 1))

    # transitive
    upstream = _reachable(graph, target, reverse=True) - {target}
    indirect = upstream - {e.caller for e in direct}
    if indirect:
        out.append(section(f"transitive callers ({len(indirect)})"))
        for n in sorted(indirect):
            out.append(bullet(n.split(":", 1)[-1]))
    roots = [n for n in upstream if not graph.in_edges(n) and n in graph.nodes]
    if roots:
        out.append(section("entry points reaching it"))
        out.append(", ".join(sorted(r.split(":", 1)[-1] for r in roots)))
    return "\n".join(out)
