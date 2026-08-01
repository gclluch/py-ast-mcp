"""Python-specific correctness hazards."""

from __future__ import annotations

import ast

from .format import bullet, header, plural, section, truncate, unparse
from .functions import FuncInfo, collect_functions, find_function
from .parse import ParsedModule, is_test_filename, parse_file
from .smells import Finding, mutable_defaults

__all__ = ["find_errors", "collect_errors"]

_BROAD = {"Exception", "BaseException"}
_ASYNC_WRAPPERS = {
    "gather",
    "create_task",
    "ensure_future",
    "run",
    "wait",
    "wait_for",
    "shield",
    "run_coroutine_threadsafe",
    "as_completed",
    "to_thread",
}


def _in_range(node: ast.AST, lo: int, hi: int) -> bool:
    ln = getattr(node, "lineno", None)
    return ln is not None and lo <= ln <= hi


def _async_defs(pm: ParsedModule) -> dict[str, FuncInfo]:
    out: dict[str, FuncInfo] = {}
    for fi in collect_functions(pm):
        if fi.is_async:
            out[fi.qualname] = fi
            out.setdefault(fi.name, fi)
    return out


def _loads(node: ast.AST) -> set[str]:
    return {
        n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }


def _attr_owners(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            out.add(n.value.id)
        elif isinstance(n, ast.Name):
            out.add(n.id)
    return out


def _f(kind, node, where, msg, sev="warn", hint=None) -> Finding:
    return Finding(kind, getattr(node, "lineno", 0), where, msg, sev, hint)


def _scope_of(pm: ParsedModule, node: ast.AST) -> str:
    for s in pm.enclosing_scopes(node):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return pm.qualname(s)
    return "<module>"


def _exception_handling(pm: ParsedModule, lo: int, hi: int) -> list[Finding]:
    """bare `except:`, over-broad catches, and silently swallowed exceptions."""
    out: list[Finding] = []
    for h in ast.walk(pm.tree):
        if not isinstance(h, ast.ExceptHandler) or not _in_range(h, lo, hi):
            continue
        where = _scope_of(pm, h)
        if h.type is None:
            out.append(
                _f(
                    "bare-except",
                    h,
                    where,
                    "bare 'except:' also swallows KeyboardInterrupt and SystemExit",
                    "error",
                    "use 'except Exception:' at minimum, ideally a specific type",
                )
            )
        else:
            names = (
                [unparse(e) for e in h.type.elts]
                if isinstance(h.type, ast.Tuple)
                else [unparse(h.type)]
            )
            if any(n.split(".")[-1] in _BROAD for n in names):
                out.append(
                    _f(
                        "broad-except",
                        h,
                        where,
                        f"catches {', '.join(names)} — hides unrelated bugs",
                        "warn",
                        "narrow to the exceptions you can actually handle",
                    )
                )
        body = [s for s in h.body if not isinstance(s, ast.Pass)]
        if not body:
            out.append(
                _f(
                    "except-pass",
                    h,
                    where,
                    "exception silently swallowed ('except ...: pass')",
                    "error",
                    "log it, re-raise, or add a comment explaining why it is safe",
                )
            )
        elif len(h.body) == 1 and isinstance(h.body[0], ast.Expr):
            val = h.body[0].value
            if isinstance(val, ast.Constant) and val.value is Ellipsis:
                out.append(
                    _f("except-pass", h, where, "exception body is '...'", "error")
                )
    return out


def _mutable_default_args(funcs: list[FuncInfo]) -> list[Finding]:
    """Mutable default arguments, which are shared across every call."""
    out: list[Finding] = []
    for fi in funcs:
        for name, node in mutable_defaults(fi):
            out.append(
                _f(
                    "mutable-default",
                    node,
                    fi.qualname,
                    f"parameter '{name}' defaults to mutable {truncate(unparse(node), 30)} "
                    "— shared across every call",
                    "error",
                    f"use '{name}=None' then assign inside the body",
                )
            )
    return out


def _unawaited_coroutines(pm: ParsedModule, lo: int, hi: int) -> list[Finding]:
    """Calls to `async def` functions in this file that are never awaited.

    Best effort: only same-file definitions are known, and calls handed to a
    recognised asyncio wrapper are treated as awaited.
    """
    async_map = _async_defs(pm)
    if not async_map:
        return []
    out: list[Finding] = []
    for call in ast.walk(pm.tree):
        if not isinstance(call, ast.Call) or not _in_range(call, lo, hi):
            continue
        fn = call.func
        target = None
        if isinstance(fn, ast.Name) and fn.id in async_map:
            target = async_map[fn.id]
        elif isinstance(fn, ast.Attribute) and fn.attr in async_map:
            if isinstance(fn.value, ast.Name) and fn.value.id in ("self", "cls"):
                target = async_map[fn.attr]
        if target is None:
            continue
        parent = pm.parent(call)
        if isinstance(parent, ast.Await):
            continue
        # asyncio.gather(coro()) / create_task(coro()) etc.
        grand = parent
        wrapped = False
        for _ in range(3):
            if isinstance(grand, ast.Call):
                name = (
                    grand.func.attr
                    if isinstance(grand.func, ast.Attribute)
                    else getattr(grand.func, "id", "")
                )
                if name in _ASYNC_WRAPPERS:
                    wrapped = True
                    break
            grand = pm.parent(grand) if grand is not None else None
        if wrapped:
            continue
        out.append(
            _f(
                "unawaited-coroutine",
                call,
                _scope_of(pm, call),
                f"call to async def '{target.qualname}' is not awaited "
                "(best effort — may be intentional)",
                "error",
                "add 'await', or wrap in asyncio.create_task(...)",
            )
        )
    return out


def _assert_for_validation(pm: ParsedModule, lo: int, hi: int) -> list[Finding]:
    """`assert` used for runtime validation - stripped under `python -O`."""
    if is_test_filename(pm.path):
        return []
    out: list[Finding] = []
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Assert) and _in_range(node, lo, hi):
            where = _scope_of(pm, node)
            if where.startswith("test_") or ".test_" in where:
                continue
            out.append(
                _f(
                    "assert-for-validation",
                    node,
                    where,
                    f"assert {truncate(unparse(node.test), 50)} — stripped under 'python -O'",
                    "warn",
                    "raise an explicit exception for runtime validation",
                )
            )
    return out


def _singleton_comparisons(pm: ParsedModule, lo: int, hi: int) -> list[Finding]:
    """`== None` / `== True` instead of identity comparison."""
    out: list[Finding] = []
    for cmp_node in ast.walk(pm.tree):
        if not isinstance(cmp_node, ast.Compare) or not _in_range(cmp_node, lo, hi):
            continue
        for op, comparator in zip(cmp_node.ops, cmp_node.comparators, strict=True):
            if not isinstance(op, (ast.Eq, ast.NotEq)):
                continue
            for side in (cmp_node.left, comparator):
                if isinstance(side, ast.Constant) and side.value in (None, True, False):
                    if side.value is None or isinstance(side.value, bool):
                        good = "is" if isinstance(op, ast.Eq) else "is not"
                        out.append(
                            _f(
                                "singleton-comparison",
                                cmp_node,
                                _scope_of(pm, cmp_node),
                                f"'{truncate(unparse(cmp_node), 60)}' compares to "
                                f"{side.value!r} with ==/!=",
                                "warn",
                                f"use '{good} {side.value!r}'"
                                if side.value is None
                                else "use the value directly or 'is True'",
                            )
                        )
                        break
    return out


def _late_binding_closures(pm: ParsedModule, lo: int, hi: int) -> list[Finding]:
    """Closures capturing a loop variable by reference."""
    out: list[Finding] = []
    for loop in ast.walk(pm.tree):
        if not isinstance(loop, (ast.For, ast.AsyncFor)) or not _in_range(loop, lo, hi):
            continue
        targets = {n.id for n in ast.walk(loop.target) if isinstance(n, ast.Name)}
        if not targets:
            continue
        for inner in ast.walk(loop):
            if inner is loop:
                continue
            if isinstance(inner, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                args = inner.args
                bound = {a.arg for a in list(args.posonlyargs) + list(args.args)}
                bound |= {a.arg for a in args.kwonlyargs}
                free = _loads(inner) - bound
                hit = targets & free
                if hit:
                    kind = (
                        "lambda"
                        if isinstance(inner, ast.Lambda)
                        else f"def {inner.name}"
                    )
                    out.append(
                        _f(
                            "late-binding-closure",
                            inner,
                            _scope_of(pm, loop),
                            f"{kind} captures loop variable(s) {', '.join(sorted(hit))} "
                            "by reference — all copies see the final value",
                            "error",
                            f"bind with a default arg, e.g. "
                            f"lambda {sorted(hit)[0]}={sorted(hit)[0]}: ...",
                        )
                    )
    return out


def _unused_self(pm: ParsedModule, funcs: list[FuncInfo]) -> list[Finding]:
    """Methods that never touch `self`.

    Method names defined on more than one class are polymorphic hooks: not
    using `self` in one override is by design, so those are skipped.
    """
    method_owners: dict[str, set[str]] = {}
    for other in collect_functions(pm):
        if other.class_name:
            method_owners.setdefault(other.name, set()).add(other.class_name)

    out: list[Finding] = []
    for fi in funcs:
        if not fi.class_name or fi.kind in ("staticmethod",):
            continue
        first = fi.params[0].name if fi.params else None
        if first != "self":
            continue
        if fi.is_abstract or len(method_owners.get(fi.name, set())) > 1:
            continue
        body = [s for s in fi.node.body if not isinstance(s, ast.Expr)]
        if not body or all(isinstance(s, (ast.Pass, ast.Raise)) for s in body):
            continue  # stub / NotImplementedError placeholder
        used = _attr_owners(ast.Module(body=fi.node.body, type_ignores=[]))
        if "self" not in used:
            out.append(
                _f(
                    "unused-self",
                    fi.node,
                    fi.qualname,
                    "method never uses 'self'",
                    "info",
                    "make it a @staticmethod or move it to module scope",
                )
            )
    return out


def collect_errors(pm: ParsedModule, function: str | None = None) -> list[Finding]:
    """Run every hazard rule over `pm`, optionally scoped to one function."""
    if function:
        fi = find_function(pm, function)
        lo, hi = fi.lineno, fi.end_lineno
        funcs = [fi]
    else:
        lo, hi = 1, len(pm.lines) + 1
        funcs = collect_functions(pm)

    findings = [
        *_exception_handling(pm, lo, hi),
        *_mutable_default_args(funcs),
        *_unawaited_coroutines(pm, lo, hi),
        *_assert_for_validation(pm, lo, hi),
        *_singleton_comparisons(pm, lo, hi),
        *_late_binding_closures(pm, lo, hi),
        *_unused_self(pm, funcs),
    ]
    findings.sort(key=lambda f: (f.lineno, f.kind))
    return findings


def find_errors(path: str, function: str | None = None) -> str:
    pm = parse_file(path)
    findings = collect_errors(pm, function)
    scope = f"function {function}" if function else "whole file"
    out = [header("find_errors", pm.path, f"{scope}, {plural(len(findings), 'issue')}")]
    if not findings:
        out.append("\nNo hazards detected.")
        return "\n".join(out)
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    out.append("summary: " + ", ".join(f"{k}×{v}" for k, v in sorted(by_kind.items())))
    for sev in ("error", "warn", "info"):
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        out.append(section(f"{sev} ({len(group)})"))
        for f in group:
            out.append(bullet(f.render()))
            src = pm.line(f.lineno).strip()
            if src:
                out.append(f"    {f.lineno} | {truncate(src, 110)}")
    return "\n".join(out)
