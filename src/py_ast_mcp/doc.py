"""Docstring extraction plus Google/NumPy style parsing."""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field

from .format import bullet, header, loc, section, truncate
from .functions import build_func_info, find_function
from .parse import AstToolError, ParsedModule, parse_file

__all__ = ["get_doc", "parse_docstring", "DocInfo"]

_GOOGLE_SECTION = re.compile(
    r"^\s*(Args|Arguments|Parameters|Returns|Return|Yields|Yield|Raises|"
    r"Attributes|Examples?|Note|Notes|Warning|Warnings|See Also|References|"
    r"Todo)\s*:\s*$",
    re.IGNORECASE,
)
_NUMPY_UNDERLINE = re.compile(r"^\s*-{3,}\s*$")
_GOOGLE_PARAM = re.compile(r"^\s*(\*{0,2}\w+)\s*(\(([^)]*)\))?\s*:\s*(.*)$")
_NUMPY_PARAM = re.compile(r"^\s*(\*{0,2}[\w, ]+?)\s*(?::\s*(.+))?$")

_ALIASES = {
    "arguments": "params",
    "args": "params",
    "parameters": "params",
    "return": "returns",
    "returns": "returns",
    "yield": "yields",
    "yields": "yields",
    "raises": "raises",
    "attributes": "attributes",
    "example": "examples",
    "examples": "examples",
    "note": "notes",
    "notes": "notes",
    "warning": "warnings",
    "warnings": "warnings",
    "see also": "see_also",
    "references": "references",
    "todo": "todo",
}


@dataclass
class DocInfo:
    raw: str
    style: str = "plain"
    summary: str = ""
    description: str = ""
    params: list[tuple[str, str, str]] = field(default_factory=list)
    returns: str = ""
    yields: str = ""
    raises: list[tuple[str, str]] = field(default_factory=list)
    attributes: list[tuple[str, str, str]] = field(default_factory=list)
    other: dict[str, str] = field(default_factory=dict)


def _detect_style(lines: list[str]) -> str:
    for i, line in enumerate(lines):
        if _GOOGLE_SECTION.match(line):
            return "google"
        if i + 1 < len(lines) and _NUMPY_UNDERLINE.match(lines[i + 1]):
            key = line.strip().lower()
            if key in _ALIASES or key in ("parameters", "returns", "raises"):
                return "numpy"
    return "plain"


def _split_sections(lines: list[str], style: str) -> tuple[list[str], dict[str, list[str]]]:
    head: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        matched = None
        if style == "google":
            m = _GOOGLE_SECTION.match(line)
            if m:
                matched = _ALIASES.get(m.group(1).lower(), m.group(1).lower())
                i += 1
        elif style == "numpy":
            if i + 1 < len(lines) and _NUMPY_UNDERLINE.match(lines[i + 1]):
                key = line.strip().lower()
                matched = _ALIASES.get(key, key)
                i += 2
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        (sections[current] if current else head).append(line)
        i += 1
    return head, sections


def _parse_params(body: list[str], style: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if style == "google":
        meaningful = [ln for ln in body if ln.strip()]
        if not meaningful:
            return out
        base = min(len(ln) - len(ln.lstrip()) for ln in meaningful)
        for line in body:
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            m = _GOOGLE_PARAM.match(line)
            if indent <= base and m:
                out.append(
                    (m.group(1), (m.group(3) or "").strip(), (m.group(4) or "").strip())
                )
            elif out:
                name, typ, desc = out[-1]
                out[-1] = (name, typ, (desc + " " + line.strip()).strip())
    else:  # numpy
        idx = 0
        while idx < len(body):
            line = body[idx]
            if not line.strip():
                idx += 1
                continue
            indent = len(line) - len(line.lstrip())
            m = _NUMPY_PARAM.match(line)
            name = (m.group(1) if m else line).strip()
            typ = (m.group(2) or "").strip() if m else ""
            desc_lines: list[str] = []
            idx += 1
            while idx < len(body):
                nxt = body[idx]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                    break
                desc_lines.append(nxt.strip())
                idx += 1
            out.append((name, typ, " ".join(x for x in desc_lines if x)))
    return out


def _parse_raises(body: list[str], style: str) -> list[tuple[str, str]]:
    params = _parse_params(body, style)
    return [(n, d or t) for n, t, d in params]


def parse_docstring(raw: str) -> DocInfo:
    """Parse a docstring into summary/params/returns when style allows."""
    clean = textwrap.dedent(raw).strip("\n")
    lines = clean.splitlines()
    style = _detect_style(lines)
    info = DocInfo(raw=clean, style=style)
    head, sections = _split_sections(lines, style)
    head_text = "\n".join(head).strip()
    if head_text:
        blocks = re.split(r"\n\s*\n", head_text, maxsplit=1)
        info.summary = " ".join(blocks[0].split())
        info.description = blocks[1].strip() if len(blocks) > 1 else ""
    for key, body in sections.items():
        if key == "params":
            info.params = _parse_params(body, style)
        elif key == "attributes":
            info.attributes = _parse_params(body, style)
        elif key == "raises":
            info.raises = _parse_raises(body, style)
        elif key == "returns":
            info.returns = " ".join(" ".join(body).split())
        elif key == "yields":
            info.yields = " ".join(" ".join(body).split())
        else:
            info.other[key] = textwrap.dedent("\n".join(body)).strip()
    return info


# --------------------------------------------------------------------------


def _find_documented(pm: ParsedModule, name: str) -> tuple[str, ast.AST, str | None]:
    if name in ("__module__", "module", "<module>", ""):
        return "module", pm.tree, ast.get_docstring(pm.tree)
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ClassDef) and (
            node.name == name or pm.qualname(node) == name
        ):
            return "class", node, ast.get_docstring(node)
    try:
        fi = find_function(pm, name)
    except AstToolError:
        fi = None
    if fi is not None:
        kind = "method" if fi.class_name else "function"
        return kind, fi.node, fi.docstring
    # module-level constant with a following string literal
    for i, stmt in enumerate(pm.tree.body):
        target = None
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target = stmt.target.id
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    target = t.id
        if target == name:
            doc = None
            if i + 1 < len(pm.tree.body):
                nxt = pm.tree.body[i + 1]
                if (
                    isinstance(nxt, ast.Expr)
                    and isinstance(nxt.value, ast.Constant)
                    and isinstance(nxt.value.value, str)
                ):
                    doc = nxt.value.value
            return "variable", stmt, doc
    raise AstToolError(f"Symbol '{name}' not found in {pm.path}")


def get_doc(path: str, name: str) -> str:
    pm = parse_file(path)
    kind, node, raw = _find_documented(pm, name)
    where = loc(node) if not isinstance(node, ast.Module) else "L1"
    out = [header(f"doc for {kind} {name}", pm.path, where)]

    if kind in ("function", "method"):
        fi = build_func_info(
            pm, node, node_class(pm, node)  # type: ignore[arg-type]
        )
        out.append(fi.signature(qualified=True))
    elif kind == "class" and isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        out.append(f"class {node.name}" + (f"({bases})" if bases else ""))

    if not raw:
        out.append("\n(no docstring)")
        return "\n".join(out)

    info = parse_docstring(raw)
    out.append(f"style: {info.style}")
    if info.summary:
        out.append(section("summary"))
        out.append(info.summary)
    if info.description:
        out.append(section("description"))
        out.append(info.description)
    if info.params:
        out.append(section("params"))
        for n, t, d in info.params:
            out.append(bullet(f"{n}{f' ({t})' if t else ''}: {d}".rstrip(": ")))
    if info.attributes:
        out.append(section("attributes"))
        for n, t, d in info.attributes:
            out.append(bullet(f"{n}{f' ({t})' if t else ''}: {d}".rstrip(": ")))
    if info.returns:
        out.append(section("returns"))
        out.append(info.returns)
    if info.yields:
        out.append(section("yields"))
        out.append(info.yields)
    if info.raises:
        out.append(section("raises"))
        for n, d in info.raises:
            out.append(bullet(f"{n}: {d}".rstrip(": ")))
    for key, val in info.other.items():
        out.append(section(key))
        out.append(val)
    if info.style == "plain":
        out.append(section("raw"))
        out.append(info.raw)
    return "\n".join(out)


def node_class(pm: ParsedModule, node: ast.AST) -> str | None:
    parent = pm.parent(node)
    return parent.name if isinstance(parent, ast.ClassDef) else None
