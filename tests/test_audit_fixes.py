"""Regressions for the 2026-08-01 audit.

Each test pins a claim the audit made, and where an external authority exists -
CPython itself, or radon - the test asks that authority rather than restating a
hand-computed number that can drift out of agreement with it.
"""

from __future__ import annotations

import ast
import warnings

import pytest

from py_ast_mcp.complexity import code_complexity, complexity_of
from py_ast_mcp.errors import collect_errors, find_errors
from py_ast_mcp.functions import collect_functions
from py_ast_mcp.parse import parse_file
from py_ast_mcp.smells import collect_smells


def kinds(findings, kind):
    return [f for f in findings if f.kind == kind]


# --- P1: mutable default on a dataclass field -----------------------------


def _classes_that_raise(path: str) -> set[str]:
    """Ground truth: execute each class body and see which ones blow up.

    `dont_inherit=True` matters. Without it the fixture inherits this module's
    `from __future__ import annotations`, which turns every annotation into a
    string; `dataclasses` then cannot resolve `InitVar` against the throwaway
    globals below and treats an InitVar as an ordinary field. That reports a
    ValueError for a class a real import accepts - an artifact of the harness,
    not of the fixture.
    """
    src = open(path).read()
    tree = ast.parse(src)
    imports = "\n".join(
        ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
    )
    raised = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        src_one = imports + "\n" + ast.unparse(node)
        try:
            exec(compile(src_one, "<t>", "exec", dont_inherit=True), {})
        except ValueError:
            raised.add(node.name)
    return raised


def test_dataclass_mutable_field_is_reported(dataclasses_bad):
    pm = parse_file(dataclasses_bad)
    found = kinds(collect_errors(pm), "mutable-dataclass-field")
    assert {f.where for f in found} == _classes_that_raise(dataclasses_bad)
    assert {f.where for f in found} == {"Crashes", "CrashesWithArgs"}
    assert all(f.severity == "error" for f in found)


def test_dataclass_mutable_field_names_default_factory(dataclasses_bad):
    out = find_errors(dataclasses_bad)
    assert "field(default_factory=list)" in out
    assert "field(default_factory=dict)" in out
    assert "field(default_factory=set)" in out


def test_dataclass_rule_spares_what_python_accepts(dataclasses_bad):
    """ClassVar, InitVar, default_factory, plain attrs and non-dataclasses."""
    pm = parse_file(dataclasses_bad)
    found = kinds(collect_errors(pm), "mutable-dataclass-field")
    reported = {f.where for f in found}
    assert "Fine" not in reported
    assert "NotADataclass" not in reported


def test_code_smells_reports_it_too(dataclasses_bad):
    """The parameter form is caught by both tools; so is this one."""
    pm = parse_file(dataclasses_bad)
    assert kinds(collect_smells(pm), "mutable-dataclass-field")


# --- P2: `case _:` is not a decision point --------------------------------

radon_visitors = pytest.importorskip("radon.visitors")


def _radon_scores(path: str) -> dict[str, int]:
    v = radon_visitors.ComplexityVisitor.from_code(open(path).read(), no_assert=True)
    out: dict[str, int] = {}
    for f in v.functions:
        out[f.name] = f.complexity
        for c in f.closures:
            out[f"{f.name}.{c.name}"] = c.complexity
    for cls in v.classes:
        for m in cls.methods:
            out[f"{cls.name}.{m.name}"] = m.complexity
    return out


@pytest.mark.parametrize("fixture", ["matching", "smelly", "sample"])
def test_complexity_matches_radon_exactly(fixture, request):
    """The README promises `radon cc --no-assert` exactly. Ask radon."""
    path = request.getfixturevalue(fixture)
    radon = _radon_scores(path)
    pm = parse_file(path)
    mine = {
        fi.qualname: complexity_of(fi.node, skip_nested_defs=True).score
        for fi in collect_functions(pm)
    }
    shared = set(radon) & set(mine)
    assert shared, f"no functions compared in {path}"
    assert {n: mine[n] for n in shared} == {n: radon[n] for n in shared}


def test_wildcard_case_is_not_counted(matching):
    """Three arms, one of them the fall-through: two decision points."""
    out = code_complexity(matching, "with_wildcard")
    assert "cyclomatic complexity: 3" in out


def test_bare_capture_counts_as_the_fall_through(matching):
    """`case other:` is irrefutable too, exactly as radon treats it."""
    out = code_complexity(matching, "with_capture")
    assert "cyclomatic complexity: 2" in out


def test_match_without_a_default_counts_every_arm(matching):
    out = code_complexity(matching, "no_default")
    assert "cyclomatic complexity: 3" in out


def test_match_of_only_a_wildcard_adds_nothing(matching):
    out = code_complexity(matching, "only_wildcard")
    assert "cyclomatic complexity: 1" in out
    assert "match case" not in out


# --- P2: the code_complexity description must match the implementation ----


def test_tool_description_does_not_claim_with_and_assert():
    from py_ast_mcp import server

    doc = server.code_complexity.__doc__ or server.code_complexity.fn.__doc__
    assert "not counted" in doc
    body = doc.split("Args:")[0]
    assert "with, assert" not in body
    assert "radon" in body


# --- P2: late-binding closures in comprehensions --------------------------


def test_comprehension_late_binding_is_reported(hazards):
    pm = parse_file(hazards)
    where = {f.where for f in kinds(collect_errors(pm), "late-binding-closure")}
    assert "comprehension_late_binding" in where
    assert "genexp_late_binding" in where
    assert "dict_comprehension_late_binding" in where


def test_loop_late_binding_still_reported(hazards):
    pm = parse_file(hazards)
    where = {f.where for f in kinds(collect_errors(pm), "late-binding-closure")}
    assert "loop_late_binding" in where


def test_default_arg_binding_is_not_reported(hazards):
    pm = parse_file(hazards)
    where = {f.where for f in kinds(collect_errors(pm), "late-binding-closure")}
    assert "bound_by_default_arg" not in where


def test_comprehension_late_binding_is_a_real_bug():
    """The premise: every closure really does see the final value.

    ruff's own B023 fires on this line, which is the point.
    """
    assert [f() for f in [lambda: i for i in range(3)]] == [2, 2, 2]  # noqa: B023


# --- P2: `is` with a literal ----------------------------------------------


def test_is_with_literal_matches_cpython_exactly(hazards):
    """CPython raises SyntaxWarning here; be no quieter than the interpreter."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(open(hazards).read(), hazards, "exec")
    expected = sorted(w.lineno for w in caught if issubclass(w.category, SyntaxWarning))
    pm = parse_file(hazards)
    actual = sorted(f.lineno for f in kinds(collect_errors(pm), "is-with-literal"))
    assert actual == expected
    assert expected, "fixture no longer contains any `is` literal"


def test_is_with_singletons_is_not_reported(hazards):
    pm = parse_file(hazards)
    where = {f.where for f in kinds(collect_errors(pm), "is-with-literal")}
    assert "is_with_singletons" not in where


# --- P2: unreachable except clauses ---------------------------------------


def test_unreachable_handler_by_superclass(hazards):
    pm = parse_file(hazards)
    where = {f.where for f in kinds(collect_errors(pm), "unreachable-except")}
    assert "unreachable_by_superclass" in where
    assert "unreachable_by_duplicate" in where
    assert "unreachable_in_tuple" in where


def test_correctly_ordered_handlers_are_not_reported(hazards):
    pm = parse_file(hazards)
    where = {f.where for f in kinds(collect_errors(pm), "unreachable-except")}
    assert "ordered_correctly" not in where
    assert "unrelated_siblings" not in where


def test_everything_after_a_bare_except_is_unreachable(tmp_path):
    """`ast.parse` accepts this even though the compiler rejects it."""
    f = tmp_path / "m.py"
    f.write_text(
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        pass\n"
    )
    found = kinds(collect_errors(parse_file(str(f))), "unreachable-except")
    assert len(found) == 1
    assert "bare except" in found[0].message


def test_unknown_exception_names_are_left_alone(tmp_path):
    """No import resolution, so no invented hierarchy - only exact repeats."""
    f = tmp_path / "m.py"
    f.write_text(
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except mod.Wrapped:\n"
        "        pass\n"
        "    except mod.Inner:\n"
        "        pass\n"
    )
    assert not kinds(collect_errors(parse_file(str(f))), "unreachable-except")
