"""Tests for the quality tools: complexity, smells, errors, dead code, protocols."""

from __future__ import annotations

import pytest

from py_ast_mcp.complexity import code_complexity, complexity_of, rank_of
from py_ast_mcp.deadcode import dead_code
from py_ast_mcp.errors import collect_errors, find_errors
from py_ast_mcp.parse import AstToolError, parse_file
from py_ast_mcp.protocols import find_implementations
from py_ast_mcp.smells import code_smells, collect_smells


# --- code_complexity ------------------------------------------------------


def test_code_complexity_table(smelly):
    out = code_complexity(smelly)
    assert "## per function (highest first)" in out
    assert "long_and_complex" in out
    assert "cc" in out
    assert "average" in out


def test_code_complexity_single_function(smelly):
    out = code_complexity(smelly, "long_and_complex")
    assert "cyclomatic complexity:" in out
    assert "## decision points" in out
    for kind in ("if/elif", "for", "while", "except", "bool op"):
        assert kind in out


def test_with_and_assert_are_not_decision_points(smelly):
    """radon/mccabe count neither; neither creates an independent path."""
    out = code_complexity(smelly, "long_and_complex")
    points = out.split("## decision points")[1]
    assert "with" not in points
    assert "assert" not in points


def test_nested_def_complexity_not_double_counted():
    """An enclosing function must not be charged for a closure's branches.

    The closure is reported as its own row, so counting it twice inflates both.
    """
    from py_ast_mcp.complexity import complexity_of
    from py_ast_mcp.functions import find_function
    from py_ast_mcp.parse import parse_source

    pm = parse_source(
        "def outer(n):\n"
        "    def inner(y):\n"
        "        if y:\n"
        "            return 1\n"
        "        return 0\n"
        "    return inner(n)\n"
    )
    inner = find_function(pm, "outer.inner")
    outer = find_function(pm, "outer")
    assert complexity_of(inner.node, skip_nested_defs=True).score == 2
    # outer has no branches of its own; inner's `if` belongs to inner
    assert complexity_of(outer.node, skip_nested_defs=True).score == 1
    # the old behaviour, kept reachable for whole-module totals
    assert complexity_of(outer.node, skip_nested_defs=False).score == 2


"""Expected scores verified against `radon cc -s --no-assert` construct by
construct, and across 259 functions in a real 46-file codebase. If one of these
changes, we have drifted away from the standard metric."""
RADON_PARITY = [
    ("if only", "def f(x):\n if x: return 1\n return 0\n", 2),
    ("if/else", "def f(x):\n if x: return 1\n else: return 0\n", 2),
    ("if/elif/else", "def f(x):\n if x: return 1\n elif x>2: return 2\n else: return 0\n", 3),
    ("for", "def f(x):\n for i in x: print(i)\n", 2),
    ("for/else", "def f(x):\n for i in x: print(i)\n else: print('d')\n", 3),
    ("while", "def f(x):\n while x: x-=1\n", 2),
    ("try/except", "def f(x):\n try: g()\n except E: pass\n", 2),
    ("try/except/else", "def f(x):\n try: g()\n except E: pass\n else: h()\n", 3),
    ("try/finally", "def f(x):\n try: g()\n finally: h()\n", 1),
    ("with", "def f(x):\n with open(x) as fh: return fh.read()\n", 1),
    ("assert", "def f(x):\n assert x\n return 1\n", 1),
    ("boolop and", "def f(a,b):\n return a and b\n", 2),
    ("boolop 3", "def f(a,b,c):\n return a and b and c\n", 3),
    ("ternary", "def f(x):\n return 1 if x else 0\n", 2),
    ("comp no if", "def f(x):\n return [i for i in x]\n", 2),
    ("comp with if", "def f(x):\n return [i for i in x if i]\n", 3),
    ("lambda", "def f(x):\n g = lambda y: y+1\n return g(x)\n", 1),
    ("nested def+if", "def f(x):\n def g(y):\n  if y: return 1\n  return 0\n return g(x)\n", 1),
]


@pytest.mark.parametrize(
    "code,expected", [(c, e) for _, c, e in RADON_PARITY], ids=[n for n, _, _ in RADON_PARITY]
)
def test_complexity_matches_radon(code, expected):
    from py_ast_mcp.complexity import complexity_of
    from py_ast_mcp.functions import find_function
    from py_ast_mcp.parse import parse_source

    pm = parse_source(code)
    score = complexity_of(find_function(pm, "f").node, skip_nested_defs=True).score
    assert score == expected


def test_code_complexity_counts_match_statement(sample):
    out = code_complexity(sample, "Widget.classify")
    assert "match case" in out


def test_code_complexity_counts_comprehension_ifs(smelly):
    pm = parse_file(smelly)
    from py_ast_mcp.functions import find_function

    fi = find_function(pm, "long_and_complex")
    res = complexity_of(fi.node)
    assert res.counts.get("comprehension if", 0) >= 2
    assert res.score > 10


def test_trivial_function_is_rank_a(sample):
    out = code_complexity(sample, "_internal_helper")
    assert "cyclomatic complexity: 1" in out
    assert "A (simple)" in out


def test_rank_thresholds():
    assert rank_of(1).startswith("A")
    assert rank_of(11).startswith("C")
    assert rank_of(99).startswith("F")


def test_code_complexity_unknown_function(sample):
    with pytest.raises(AstToolError):
        code_complexity(sample, "nope")


# --- code_smells ----------------------------------------------------------


def _kinds(findings):
    return {f.kind for f in findings}


def test_code_smells_finds_all_categories(smelly):
    pm = parse_file(smelly)
    kinds = _kinds(collect_smells(pm))
    assert "long-function" in kinds
    assert "deep-nesting" in kinds
    assert "god-class" in kinds
    assert "too-many-params" in kinds
    assert "mutable-default" in kinds
    assert "bare-except" in kinds
    assert "shadowed-builtin" in kinds


def test_code_smells_output_grouped_by_severity(smelly):
    out = code_smells(smelly)
    assert "## error" in out
    assert "## warn" in out
    assert "summary:" in out
    assert "fix:" in out


def test_code_smells_scoped_to_one_function(smelly):
    out = code_smells(smelly, "mutable_default")
    assert "mutable-default" in out
    assert "god-class" not in out


def test_code_smells_clean_file(helpers):
    out = code_smells(helpers)
    assert "No smells detected" in out


def test_self_param_not_counted_towards_param_limit(sample):
    out = code_smells(sample)
    assert "too-many-params" not in out


# --- find_errors ----------------------------------------------------------


def test_find_errors_covers_every_hazard(smelly):
    pm = parse_file(smelly)
    kinds = _kinds(collect_errors(pm))
    expected = {
        "bare-except",
        "broad-except",
        "except-pass",
        "mutable-default",
        "unawaited-coroutine",
        "assert-for-validation",
        "late-binding-closure",
        "singleton-comparison",
        "unused-self",
    }
    assert expected <= kinds, expected - kinds


def test_find_errors_reports_source_line(smelly):
    out = find_errors(smelly)
    assert "summary:" in out
    assert "except:" in out
    assert " | " in out


def test_find_errors_scoped(smelly):
    out = find_errors(smelly, "compare_singletons")
    assert "singleton-comparison" in out
    assert "bare-except" not in out


def test_find_errors_awaited_call_not_flagged(smelly):
    pm = parse_file(smelly)
    findings = [f for f in collect_errors(pm) if f.kind == "unawaited-coroutine"]
    lines = {f.lineno for f in findings}
    # `return await coro(2)` at the end of runner() must not be flagged
    src = pm.lines
    for ln in lines:
        assert "await coro" not in src[ln - 1]


def test_find_errors_clean_file(helpers):
    assert "No hazards detected" in find_errors(helpers)


def test_find_errors_on_syntax_error(broken):
    from py_ast_mcp.parse import ParseError

    with pytest.raises(ParseError):
        find_errors(broken)


# --- dead_code ------------------------------------------------------------


def test_dead_code_finds_unreferenced_private(pkg):
    out = dead_code(pkg)
    assert "_unused_private" in out
    assert "unreferenced private symbols" in out


def test_dead_code_does_not_flag_used_symbols(pkg):
    out = dead_code(pkg)
    assert "normalize" not in out.split("## unreferenced")[1]
    assert "Engine" not in out.split("## unreferenced")[1]


def test_dead_code_from_a_file_scans_its_directory(fixtures_dir):
    out = dead_code(str(fixtures_dir / "sample.py"))
    assert "_never_called" in out
    assert "UNUSED_CONSTANT" in out
    assert "_internal_helper" not in out.split("## unreferenced")[1]


def test_dead_code_reports_unparseable(fixtures_dir):
    out = dead_code(str(fixtures_dir))
    assert "unparseable" in out
    assert "broken.py" in out


def test_dead_code_include_tests_flag(fixtures_dir):
    out = dead_code(str(fixtures_dir), include_tests=True)
    assert "include_tests=True" in out


def test_dead_code_missing_path(tmp_path):
    with pytest.raises(AstToolError):
        dead_code(str(tmp_path / "missing"))


# --- find_implementations -------------------------------------------------


def test_find_implementations_structural(sample):
    out = find_implementations(sample, "Repository")
    assert "required members: get, put" in out
    assert "InMemoryRepository" in out
    assert "## structural" in out


def test_find_implementations_explicit_abc(pkg_core):
    out = find_implementations(pkg_core, "Storage")
    assert "MemoryStorage" in out
    assert "direct base" in out


def test_find_implementations_protocol_structural(pkg_core):
    out = find_implementations(pkg_core, "Serializer")
    assert "JsonSerializer" in out
    assert "defines all of dumps, loads" in out


def test_find_implementations_unknown(sample):
    with pytest.raises(AstToolError):
        find_implementations(sample, "NotAProtocol")
