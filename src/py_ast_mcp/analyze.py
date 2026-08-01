"""File- and package-level structural summaries, plus cursor-position lookup."""

from __future__ import annotations

import ast
from pathlib import Path

from .format import (
    bullet,
    header,
    loc,
    plural,
    section,
    table,
    truncate,
    unparse,
)
from .functions import build_func_info, decorator_names
from .imports import collect_imports, dunder_all
from .parse import (
    AstToolError,
    ParsedModule,
    ParseError,
    iter_py_files,
    parse_file,
    resolve_path,
)
from .types import class_kind_of, infer_literal_type, is_type_alias

__all__ = ["analyze_file", "analyze_package", "find_node_at_position", "file_summary"]


def _class_line(pm: ParsedModule, node: ast.ClassDef) -> str:
    kind, bases = class_kind_of(node), [unparse(b) for b in node.bases]
    methods = [
        s for s in node.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    props = [m for m in methods if "property" in decorator_names(m)]
    fields = [
        s
        for s in node.body
        if isinstance(s, ast.AnnAssign)
        or (
            isinstance(s, ast.Assign)
            and all(isinstance(t, ast.Name) for t in s.targets)
        )
    ]
    bits = [f"{len(methods)} methods"]
    if props:
        bits.append(f"{len(props)} properties")
    if fields:
        bits.append(f"{len(fields)} fields")
    base_txt = f"({', '.join(bases)})" if bases else ""
    line = f"[{loc(node)}] {kind} {node.name}{base_txt}  {{{', '.join(bits)}}}"
    doc = ast.get_docstring(node)
    if doc:
        line += f'  "{truncate(doc, 70)}"'
    return line


def _overview_lines(pm: ParsedModule, classes, funcs, imports) -> list[str]:
    """Module docstring, counts, and `__all__`."""
    out: list[str] = []
    doc = ast.get_docstring(pm.tree)
    if doc:
        out.append(f'module doc: "{truncate(doc, 160)}"')
    counts = {
        "lines": len(pm.lines),
        "imports": len(imports),
        "classes": len(classes),
        # "module-level", because `list_functions` counts methods too and the
        # two totals otherwise look like a contradiction on the same file.
        "module-level functions": len(
            [f for f in funcs if not isinstance(f, ast.AsyncFunctionDef)]
        ),
        "module-level async functions": len(
            [f for f in funcs if isinstance(f, ast.AsyncFunctionDef)]
        ),
    }
    out.append(
        "counts: "
        + ", ".join(f"{v} {k}" for k, v in counts.items() if v or k == "lines")
    )
    all_decl = dunder_all(pm)
    if all_decl:
        out.append(f"__all__ (L{all_decl[1]}): {', '.join(all_decl[0]) or '(empty)'}")
    return out


def _imports_lines(imports) -> list[str]:
    if not imports:
        return []
    out = [section(f"imports ({len(imports)})")]
    for r in imports[:60]:
        out.append(bullet(f"[L{r.lineno}] {r.binding} <- {r.source}"))
    if len(imports) > 60:
        out.append(bullet(f"... {len(imports) - 60} more"))
    return out


def _classes_lines(pm: ParsedModule, classes) -> list[str]:
    """Classes in source order, each followed by its methods.

    Source order, not grouped by kind: every other section of this report is
    line-ordered, and each class line already names its own kind, so grouping
    only scrambled the line numbers.
    """
    if not classes:
        return []
    out = [section(f"classes ({len(classes)})")]
    for c in classes:
        out.append(bullet(_class_line(pm, c)))
        for s in c.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fi = build_func_info(pm, s, c.name)
                tag = f" [{fi.kind}]" if fi.kind != "method" else ""
                out.append(
                    bullet(
                        f"[{loc(line=fi.lineno, end=fi.end_lineno)}] "
                        f"{fi.signature()}{tag}",
                        1,
                    )
                )
    return out


def _functions_lines(pm: ParsedModule, funcs) -> list[str]:
    if not funcs:
        return []
    out = [section(f"module-level functions ({len(funcs)})")]
    for f in funcs:
        fi = build_func_info(pm, f)
        line = f"[{loc(line=fi.lineno, end=fi.end_lineno)}] {fi.signature()}"
        if fi.decorators:
            line += f"  @{' @'.join(fi.decorators)}"
        out.append(bullet(line))
        if fi.docstring:
            out.append(bullet(f'"{truncate(fi.docstring, 90)}"', 1))
    return out


def _assignments_lines(pm: ParsedModule) -> list[str]:
    """Module-level assignments, annotated or inferred, flagging type aliases."""
    assigns: list[str] = []
    for stmt in pm.tree.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            tag = " [TypeAlias]" if is_type_alias(stmt) else ""
            assigns.append(
                f"[{loc(stmt)}] {stmt.target.id}: {unparse(stmt.annotation)}{tag}"
            )
        elif isinstance(stmt, ast.Assign):
            tag = " [TypeAlias]" if is_type_alias(stmt) else ""
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    assigns.append(
                        f"[{loc(stmt)}] {t.id}: {infer_literal_type(stmt.value)}{tag}"
                    )
        elif hasattr(ast, "TypeAlias") and isinstance(stmt, ast.TypeAlias):
            assigns.append(f"[{loc(stmt)}] {unparse(stmt.name)} [TypeAlias]")
    if not assigns:
        return []
    return [
        section(f"module-level assignments ({len(assigns)})"),
        *(bullet(a) for a in assigns),
    ]


def file_summary(pm: ParsedModule) -> list[str]:
    classes = [n for n in pm.tree.body if isinstance(n, ast.ClassDef)]
    funcs = [
        n
        for n in pm.tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    imports = collect_imports(pm)

    return [
        *_overview_lines(pm, classes, funcs, imports),
        *_imports_lines(imports),
        *_classes_lines(pm, classes),
        *_functions_lines(pm, funcs),
        *_assignments_lines(pm),
    ]


def analyze_file(path: str) -> str:
    pm = parse_file(path)
    out = [header("analyze_file", pm.path)]
    out.extend(file_summary(pm))
    return "\n".join(out)


def analyze_package(path: str, include_tests: bool = False) -> str:
    root = Path(resolve_path(path))
    files = list(iter_py_files(root, include_tests=include_tests))
    if not files:
        raise AstToolError(f"No .py files found under {path}")
    base = root if root.is_dir() else root.parent
    out = [
        header(
            "analyze_package",
            str(root),
            f"{plural(len(files), 'file')}, include_tests={include_tests}",
        )
    ]
    rows: list[list[str]] = []
    total = {"lines": 0, "classes": 0, "functions": 0, "async": 0, "errors": 0}
    details: list[str] = []
    for f in files:
        try:
            pm = parse_file(str(f))
        except ParseError as exc:
            total["errors"] += 1
            rows.append([str(f.relative_to(base)), "!", "-", "-", "-", "syntax error"])
            details.append(
                bullet(f"{f.relative_to(base)}: {exc.message} (line {exc.line})")
            )
            continue
        classes = [n for n in pm.tree.body if isinstance(n, ast.ClassDef)]
        funcs = [n for n in pm.tree.body if isinstance(n, ast.FunctionDef)]
        afuncs = [n for n in pm.tree.body if isinstance(n, ast.AsyncFunctionDef)]
        total["lines"] += len(pm.lines)
        total["classes"] += len(classes)
        total["functions"] += len(funcs)
        total["async"] += len(afuncs)
        doc = ast.get_docstring(pm.tree)
        rows.append(
            [
                str(f.relative_to(base)),
                str(len(pm.lines)),
                str(len(classes)),
                str(len(funcs)),
                str(len(afuncs)),
                truncate(doc or "", 60),
            ]
        )
    out.append(
        "totals: "
        + ", ".join(
            f"{v} {k}" for k, v in total.items() if v or k in ("lines", "classes")
        )
    )
    out.append(section("files"))
    out.append(table(rows, ["file", "lines", "cls", "fn", "async", "docstring"]))
    if details:
        out.append(section("unparseable files"))
        out.extend(details)

    out.append(section("symbols by file"))
    for f in files:
        try:
            pm = parse_file(str(f))
        except ParseError:
            continue
        names: list[str] = []
        for stmt in pm.tree.body:
            if isinstance(stmt, ast.ClassDef):
                names.append(f"{class_kind_of(stmt)} {stmt.name}@{stmt.lineno}")
            elif isinstance(stmt, ast.AsyncFunctionDef):
                names.append(f"async def {stmt.name}@{stmt.lineno}")
            elif isinstance(stmt, ast.FunctionDef):
                names.append(f"def {stmt.name}@{stmt.lineno}")
        if names:
            out.append(bullet(f"{f.relative_to(base)}: " + ", ".join(names)))
    return "\n".join(out)


# --------------------------------------------------------------------------


def _node_covers(node: ast.AST, line: int, col: int) -> bool:
    sl = getattr(node, "lineno", None)
    el = getattr(node, "end_lineno", None)
    sc = getattr(node, "col_offset", None)
    ec = getattr(node, "end_col_offset", None)
    if sl is None or el is None or sc is None or ec is None:
        return False
    if line < sl or line > el:
        return False
    if line == sl and col < sc:
        return False
    if line == el and col > ec:
        return False
    return True


def _describe(pm: ParsedModule, node: ast.AST) -> str:
    kind = type(node).__name__
    detail = ""
    if isinstance(node, ast.Name):
        ctx = type(node.ctx).__name__.lower()
        detail = f"name '{node.id}' ({ctx})"
    elif isinstance(node, ast.Attribute):
        detail = f"attribute '{unparse(node)}'"
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        detail = f"def {node.name}"
    elif isinstance(node, ast.ClassDef):
        detail = f"class {node.name}"
    elif isinstance(node, ast.Constant):
        detail = f"constant {truncate(repr(node.value), 40)}"
    elif isinstance(node, ast.Call):
        detail = f"call {truncate(unparse(node.func), 50)}(...)"
    elif isinstance(node, ast.arg):
        detail = f"parameter '{node.arg}'"
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        detail = truncate(unparse(node), 60)
    else:
        detail = truncate(unparse(node), 60) if hasattr(node, "lineno") else ""
    return f"{kind}: {detail}" if detail else kind


def find_node_at_position(path: str, line: int, column: int) -> str:
    pm = parse_file(path)
    if line < 1 or line > len(pm.lines):
        raise AstToolError(
            f"line {line} out of range for {pm.path} (1..{len(pm.lines)})"
        )
    candidates = [n for n in ast.walk(pm.tree) if _node_covers(n, line, column)]
    out = [header("node at position", pm.path, f"line {line}, col {column}")]
    out.append(f"source: {pm.line(line)}")
    out.append(" " * (len("source: ") + max(column, 0)) + "^")
    if not candidates:
        out.append("\nNo AST node covers that position (whitespace, comment or EOL).")
        return "\n".join(out)

    def span(n: ast.AST) -> tuple[int, int]:
        return (
            (n.end_lineno - n.lineno),  # type: ignore[attr-defined]
            (n.end_col_offset - n.col_offset)  # type: ignore[attr-defined]
            if n.end_lineno == n.lineno  # type: ignore[attr-defined]
            else 10**6,
        )

    candidates.sort(key=span)
    innermost = candidates[0]
    out.append(section("innermost node"))
    out.append(bullet(f"[{loc(innermost)}] {_describe(pm, innermost)}"))
    out.append(
        bullet(
            f"cols {innermost.col_offset}-{innermost.end_col_offset}",  # type: ignore[attr-defined]
            1,
        )
    )
    out.append(section("node chain (innermost -> outermost)"))
    for n in candidates[:12]:
        out.append(bullet(f"[{loc(n)}] {_describe(pm, n)}"))

    out.append(section("enclosing scopes"))
    scopes = pm.enclosing_scopes(innermost)
    if not scopes or all(isinstance(s, ast.Module) for s in scopes):
        out.append(bullet("<module>"))
    for s in scopes:
        if isinstance(s, ast.Module):
            out.append(bullet("<module>"))
        elif isinstance(s, ast.Lambda):
            out.append(bullet(f"[{loc(s)}] lambda"))
        else:
            word = "class" if isinstance(s, ast.ClassDef) else "def"
            out.append(bullet(f"[{loc(s)}] {word} {pm.qualname(s)}"))

    from . import jedi_support

    if jedi_support.available():
        inferred = jedi_support.infer_at(pm.path, pm.source, line, column)
        if inferred:
            out.append(section("semantic resolution (jedi)"))
            out.extend(bullet(i) for i in inferred[:8])
    return "\n".join(out)
