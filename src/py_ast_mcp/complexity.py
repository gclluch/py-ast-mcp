"""Cyclomatic complexity."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .format import bullet, empty, header, loc, section, table
from .functions import collect_functions, find_function
from .parse import parse_file

__all__ = ["complexity_of", "code_complexity", "ComplexityResult", "rank_of"]


@dataclass
class ComplexityResult:
    score: int
    counts: dict[str, int] = field(default_factory=dict)
    max_depth: int = 0

    @property
    def rank(self) -> str:
        return rank_of(self.score)


def rank_of(score: int) -> str:
    if score <= 5:
        return "A (simple)"
    if score <= 10:
        return "B (moderate)"
    if score <= 20:
        return "C (complex)"
    if score <= 30:
        return "D (very complex)"
    if score <= 40:
        return "E (alarming)"
    return "F (unmaintainable)"


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
# ast.TryStar is 3.11+; ast.Try is the only one on 3.10
_TRY_NODES = tuple(
    t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t
)


def _counted_cases(node: ast.Match) -> int:
    """`match` arms that are decision points.

    An irrefutable arm - `case _:`, or any bare capture such as `case other:` -
    always matches, so it is the fall-through, exactly like `else` or a switch
    `default`. It is not an independent path and must not be counted, or every
    `match` scores one higher than `radon`, against which these scores are
    advertised as exact.

    Mirrors radon's own rule, including its blind spot: radon subtracts at most
    one such arm and does not check for a guard, so `case _ if cond:` - which
    can in fact fail - is still treated as the default.
    """
    has_default = any(
        getattr(case.pattern, "pattern", False) is None for case in node.cases
    )
    return max(0, len(node.cases) - has_default)


def complexity_of(node: ast.AST, skip_nested_defs: bool = False) -> ComplexityResult:
    """Cyclomatic complexity of a function/class/module subtree.

    Decision points counted: ``if``/``elif``, ``for``, ``while``, ``except``,
    comprehension ``if`` clauses, boolean operators, ternaries and ``match``
    cases. This matches what ``radon`` and ``mccabe`` count, so scores are
    directly comparable to those tools.

    ``with`` and ``assert`` are deliberately *not* counted: neither branches,
    so neither adds an independent path. ``with`` still contributes nesting
    depth.

    With ``skip_nested_defs``, decision points inside nested ``def``s are left
    out, so an enclosing function is not charged for closures that are reported
    as rows of their own.
    """
    counts: dict[str, int] = {}
    max_depth = 0

    def bump(key: str, n: int = 1) -> None:
        counts[key] = counts.get(key, 0) + n

    def walk(n: ast.AST, depth: int) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, depth)
        for child in ast.iter_child_nodes(n):
            nested = depth
            if skip_nested_defs and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            if isinstance(child, ast.If):
                bump("if/elif")
                nested = depth + 1
            elif isinstance(child, (ast.For, ast.AsyncFor)):
                bump("for")
                if child.orelse:
                    bump("loop else")
                nested = depth + 1
            elif isinstance(child, ast.While):
                bump("while")
                if child.orelse:
                    bump("loop else")
                nested = depth + 1
            elif isinstance(child, ast.ExceptHandler):
                bump("except")
                nested = depth + 1
            elif isinstance(child, _TRY_NODES):
                # `try/except/else`: the else clause is its own path
                if child.orelse:
                    bump("try else")
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                # not a branch, so no bump - but it is still an indent level
                nested = depth + 1
            elif isinstance(child, ast.BoolOp):
                bump("bool op", max(len(child.values) - 1, 1))
            elif isinstance(child, ast.IfExp):
                bump("ternary")
            elif isinstance(child, _COMPREHENSIONS):
                for gen in child.generators:
                    # each `for` clause is a loop, so it is a path in its own
                    # right - not just its filters
                    bump("comprehension")
                    bump("comprehension if", len(gen.ifs))
                nested = depth + 1
            elif hasattr(ast, "Match") and isinstance(child, ast.Match):
                arms = _counted_cases(child)
                if arms:
                    bump("match case", arms)
                nested = depth + 1
            walk(child, nested)

    walk(node, 0)
    score = 1 + sum(counts.values())
    return ComplexityResult(score=score, counts=counts, max_depth=max_depth)


def code_complexity(path: str, function: str | None = None) -> str:
    pm = parse_file(path)
    if function:
        fi = find_function(pm, function)
        res = complexity_of(fi.node, skip_nested_defs=True)
        out = [
            header(
                f"complexity of {fi.qualname}",
                pm.path,
                f"{loc(line=fi.lineno, end=fi.end_lineno)}",
            ),
            f"cyclomatic complexity: {res.score}   rank: {res.rank}",
            f"lines: {fi.nlines}   max nesting depth: {res.max_depth}   "
            f"params: {len(fi.params)}",
        ]
        if res.counts:
            out.append(section("decision points"))
            out.append(
                table(
                    sorted(
                        ([k, str(v)] for k, v in res.counts.items()),
                        key=lambda r: -int(r[1]),
                    ),
                    ["kind", "count"],
                )
            )
        return "\n".join(out)

    funcs = collect_functions(pm)
    if not funcs:
        return header("complexity", pm.path) + "\n" + empty("functions")
    rows: list[list[str]] = []
    scores: list[int] = []
    for fi in funcs:
        res = complexity_of(fi.node, skip_nested_defs=True)
        scores.append(res.score)
        rows.append(
            [
                fi.qualname,
                f"L{fi.lineno}-{fi.end_lineno}",
                str(res.score),
                res.rank.split(" ")[0],
                str(fi.nlines),
                str(res.max_depth),
            ]
        )
    rows.sort(key=lambda r: -int(r[2]))
    mod_res = complexity_of(pm.tree)
    out = [
        header(
            "complexity",
            pm.path,
            f"{len(funcs)} functions, module total {mod_res.score}",
        ),
        f"average {sum(scores) / len(scores):.1f}   max {max(scores)}   "
        f"functions over 10: {sum(1 for s in scores if s > 10)}",
        section("per function (highest first)"),
        table(rows, ["function", "lines", "cc", "rank", "len", "depth"]),
    ]
    hot = [r for r in rows if int(r[2]) > 10]
    if hot:
        out.append(section("attention"))
        for r in hot:
            out.append(bullet(f"{r[0]} ({r[1]}) cc={r[2]} — consider decomposing"))
    return "\n".join(out)
