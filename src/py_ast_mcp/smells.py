"""Code smell detection."""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass

from .complexity import complexity_of
from .format import bullet, header, plural, section, truncate, unparse
from .functions import FuncInfo, collect_functions, find_function
from .parse import ParsedModule, parse_file

__all__ = ["Finding", "code_smells", "collect_smells"]

LONG_FUNCTION_LINES = 50
DEEP_NESTING = 4
GOD_CLASS_METHODS = 20
GOD_CLASS_LINES = 400
MAX_PARAMS = 5

_BUILTINS = set(dir(builtins))
_ALLOWED_SHADOWS = {"_", "id_", "type_"}
_MUTABLE_NODES = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
_MUTABLE_CALLS = {"list", "dict", "set", "collections.OrderedDict", "bytearray", "defaultdict"}


@dataclass
class Finding:
    kind: str
    lineno: int
    where: str
    message: str
    severity: str = "warn"
    hint: str | None = None

    def render(self) -> str:
        base = f"[L{self.lineno}] {self.kind}: {self.message}"
        if self.where:
            base += f"  (in {self.where})"
        if self.hint:
            base += f"\n    fix: {self.hint}"
        return base


def _nesting_depth(node: ast.AST) -> tuple[int, int]:
    """Return (max depth, line of deepest block)."""
    best = (0, getattr(node, "lineno", 0))

    def walk(n: ast.AST, depth: int) -> None:
        nonlocal best
        for child in ast.iter_child_nodes(n):
            d = depth
            if isinstance(
                child,
                (
                    ast.If,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.With,
                    ast.AsyncWith,
                    ast.Try,
                    ast.ExceptHandler,
                ),
            ) or (hasattr(ast, "Match") and isinstance(child, getattr(ast, "Match"))):
                d = depth + 1
                if d > best[0]:
                    best = (d, getattr(child, "lineno", 0))
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            walk(child, d)

    walk(node, 0)
    return best


def mutable_defaults(fi: FuncInfo) -> list[tuple[str, ast.expr]]:
    args = fi.node.args
    pairs: list[tuple[str, ast.expr]] = []
    positional = list(args.posonlyargs) + list(args.args)
    pad = len(positional) - len(args.defaults)
    for i, d in enumerate(args.defaults):
        pairs.append((positional[pad + i].arg, d))
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        if d is not None:
            pairs.append((a.arg, d))
    bad: list[tuple[str, ast.expr]] = []
    for name, node in pairs:
        if isinstance(node, _MUTABLE_NODES):
            bad.append((name, node))
        elif isinstance(node, ast.Call):
            fn = unparse(node.func)
            if fn in _MUTABLE_CALLS or fn.split(".")[-1] in _MUTABLE_CALLS:
                bad.append((name, node))
    return bad


def _shadowed_builtins(pm: ParsedModule, node: ast.AST, where: str) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple[str, int]] = set()

    def report(name: str, lineno: int, what: str) -> None:
        if name in _BUILTINS and name not in _ALLOWED_SHADOWS and not name.startswith("__"):
            key = (name, lineno)
            if key in seen:
                return
            seen.add(key)
            out.append(
                Finding(
                    "shadowed-builtin",
                    lineno,
                    where,
                    f"{what} '{name}' shadows the builtin",
                    "info",
                    f"rename to '{name}_' or something domain specific",
                )
            )

    for n in ast.walk(node):
        if isinstance(n, ast.arg):
            report(n.arg, n.lineno, "parameter")
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            report(n.id, n.lineno, "variable")
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            report(n.name, n.lineno, "definition")
    return out


def collect_smells(pm: ParsedModule, function: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    if function:
        funcs = [find_function(pm, function)]
        scope_nodes: list[ast.AST] = [f.node for f in funcs]
        classes: list[ast.ClassDef] = []
    else:
        funcs = collect_functions(pm)
        scope_nodes = [pm.tree]
        classes = [n for n in ast.walk(pm.tree) if isinstance(n, ast.ClassDef)]

    for fi in funcs:
        where = fi.qualname
        if fi.nlines > LONG_FUNCTION_LINES:
            findings.append(
                Finding(
                    "long-function",
                    fi.lineno,
                    where,
                    f"{fi.nlines} lines (threshold {LONG_FUNCTION_LINES})",
                    "warn",
                    "extract cohesive blocks into helpers",
                )
            )
        depth, deep_line = _nesting_depth(fi.node)
        if depth > DEEP_NESTING:
            findings.append(
                Finding(
                    "deep-nesting",
                    deep_line,
                    where,
                    f"nesting depth {depth} (threshold {DEEP_NESTING})",
                    "warn",
                    "use guard clauses / early returns",
                )
            )
        effective = [
            p
            for p in fi.params
            if not (fi.class_name and p.name in ("self", "cls") and p is fi.params[0])
        ]
        if len(effective) > MAX_PARAMS:
            findings.append(
                Finding(
                    "too-many-params",
                    fi.lineno,
                    where,
                    f"{len(effective)} parameters (threshold {MAX_PARAMS})",
                    "warn",
                    "group related args into a dataclass or use keyword-only args",
                )
            )
        for name, node in mutable_defaults(fi):
            findings.append(
                Finding(
                    "mutable-default",
                    node.lineno,
                    where,
                    f"parameter '{name}' defaults to mutable {truncate(unparse(node), 30)}",
                    "error",
                    f"use '{name}=None' and build it inside the function",
                )
            )
        cc = complexity_of(fi.node, skip_nested_defs=True)
        if cc.score > 10:
            findings.append(
                Finding(
                    "high-complexity",
                    fi.lineno,
                    where,
                    f"cyclomatic complexity {cc.score} ({cc.rank})",
                    "warn" if cc.score <= 20 else "error",
                    "split the decision tree",
                )
            )

    for cls in classes:
        methods = [
            s
            for s in cls.body
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        nlines = (cls.end_lineno or cls.lineno) - cls.lineno + 1
        if len(methods) > GOD_CLASS_METHODS or nlines > GOD_CLASS_LINES:
            findings.append(
                Finding(
                    "god-class",
                    cls.lineno,
                    cls.name,
                    f"{len(methods)} methods over {nlines} lines "
                    f"(thresholds {GOD_CLASS_METHODS}/{GOD_CLASS_LINES})",
                    "warn",
                    "split responsibilities into collaborating classes",
                )
            )

    for node in scope_nodes:
        for h in ast.walk(node):
            if isinstance(h, ast.ExceptHandler) and h.type is None:
                findings.append(
                    Finding(
                        "bare-except",
                        h.lineno,
                        "",
                        "bare 'except:' catches SystemExit/KeyboardInterrupt too",
                        "error",
                        "catch a specific exception, or 'except Exception:'",
                    )
                )
        findings.extend(_shadowed_builtins(pm, node, function or ""))

    findings.sort(key=lambda f: (f.lineno, f.kind))
    return findings


def code_smells(path: str, function: str | None = None) -> str:
    pm = parse_file(path)
    findings = collect_smells(pm, function)
    scope = f"function {function}" if function else "whole file"
    out = [header("code_smells", pm.path, f"{scope}, {plural(len(findings), 'finding')}")]
    if not findings:
        out.append("\nNo smells detected against the configured thresholds.")
        out.append(
            f"thresholds: long>{LONG_FUNCTION_LINES} lines, nesting>{DEEP_NESTING}, "
            f"god class>{GOD_CLASS_METHODS} methods/{GOD_CLASS_LINES} lines, "
            f"params>{MAX_PARAMS}"
        )
        return "\n".join(out)
    by_kind: dict[str, list[Finding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    out.append(
        "summary: "
        + ", ".join(f"{k}×{len(v)}" for k, v in sorted(by_kind.items()))
    )
    for sev in ("error", "warn", "info"):
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        out.append(section(f"{sev} ({len(group)})"))
        out.extend(bullet(f.render()) for f in group)
    return "\n".join(out)
