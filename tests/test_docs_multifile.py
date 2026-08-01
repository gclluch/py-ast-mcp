"""Tests for get_doc, analyze_package, diff_ast and find_node_at_position."""

from __future__ import annotations

import pytest

from py_ast_mcp.analyze import analyze_package, find_node_at_position
from py_ast_mcp.diff import diff_ast
from py_ast_mcp.doc import get_doc, parse_docstring
from py_ast_mcp.parse import AstToolError


# --- get_doc --------------------------------------------------------------


def test_get_doc_google_style(sample):
    out = get_doc(sample, "process")
    assert "style: google" in out
    assert "## summary" in out
    assert "Process a list of items." in out
    assert "items: Items to process." in out
    assert "## returns" in out
    assert "The processed items." in out


def test_get_doc_numpy_style(sample):
    out = get_doc(sample, "Widget.classify")
    assert "style: numpy" in out
    assert "score (int)" in out
    assert "A textual band" in out


def test_get_doc_class_with_raises(sample):
    out = get_doc(sample, "Widget")
    assert "## raises" in out
    assert "ValueError" in out
    assert "## params" in out


def test_get_doc_module(sample):
    out = get_doc(sample, "module")
    assert "Sample module exercising" in out


def test_get_doc_plain_docstring(sample):
    out = get_doc(sample, "Color")
    assert "style: plain" in out
    assert "Colours a widget may take." in out


def test_get_doc_missing_docstring(sample):
    out = get_doc(sample, "make_callbacks")
    assert "(no docstring)" in out


def test_get_doc_unknown_symbol(sample):
    with pytest.raises(AstToolError):
        get_doc(sample, "nope")


def test_parse_docstring_plain():
    info = parse_docstring("Just a summary.\n\nAnd a description.")
    assert info.style == "plain"
    assert info.summary == "Just a summary."
    assert "description" in info.description


def test_parse_docstring_google_raises():
    info = parse_docstring(
        "Do a thing.\n\n"
        "Args:\n"
        "    a (int): first\n"
        "    b: second\n"
        "        continued\n"
        "Returns:\n"
        "    An int.\n"
        "Raises:\n"
        "    ValueError: when bad\n"
    )
    assert info.style == "google"
    assert [p[0] for p in info.params] == ["a", "b"]
    assert info.params[0][1] == "int"
    assert "continued" in info.params[1][2]
    assert info.returns == "An int."
    assert info.raises[0][0] == "ValueError"


# --- analyze_package ------------------------------------------------------


def test_analyze_package_summary(pkg):
    out = analyze_package(pkg)
    assert "analyze_package" in out
    assert "core.py" in out and "util.py" in out
    assert "## files" in out
    assert "## symbols by file" in out
    assert "class Engine@" in out


def test_analyze_package_totals(pkg):
    out = analyze_package(pkg)
    assert "totals:" in out
    assert "lines" in out


def test_analyze_package_reports_syntax_errors(fixtures_dir):
    out = analyze_package(str(fixtures_dir))
    assert "unparseable files" in out
    assert "broken.py" in out


def test_analyze_package_missing_dir(tmp_path):
    with pytest.raises(AstToolError):
        analyze_package(str(tmp_path / "nope"))


# --- diff_ast -------------------------------------------------------------


def test_diff_ast_functions(old_version, new_version):
    out = diff_ast(old_version, new_version)
    assert "+ added_function" in out
    assert "- removed_function" in out
    assert "~ changed_signature  signature changed" in out
    assert "old: def changed_signature(a: int) -> int" in out
    assert "new: def changed_signature(a: int, b: str = 'x') -> str" in out


def test_diff_ast_body_only_change(old_version, new_version):
    out = diff_ast(old_version, new_version)
    assert "~ same_function  body changed (same signature)" in out


def test_diff_ast_classes_and_methods(old_version, new_version):
    out = diff_ast(old_version, new_version)
    assert "+ NewService" in out
    assert "+ Service.restart" in out
    assert "- Service.legacy" in out
    assert "~ Service.start" in out


def test_diff_ast_variables_and_imports(old_version, new_version):
    out = diff_ast(old_version, new_version)
    assert "+ NEW_SETTING" in out
    assert "~ VERSION" in out or "VERSION" in out
    assert "- sys <- sys" in out
    assert "+ Path <- pathlib.Path" in out


def test_diff_ast_identical_files(sample):
    out = diff_ast(sample, sample)
    assert "structural changes: 0" in out
    assert out.count("(unchanged)") >= 4


def test_diff_ast_breaking_section(old_version, new_version):
    out = diff_ast(old_version, new_version)
    assert "potentially breaking" in out
    assert "removed_function" in out


# --- find_node_at_position ------------------------------------------------


def test_find_node_at_position_identifies_call(sample):
    import re
    from pathlib import Path

    src = Path(sample).read_text().splitlines()
    line = next(i + 1 for i, l in enumerate(src) if "return inner(n) + helpers.double" in l)
    col = src[line - 1].index("inner(")
    out = find_node_at_position(sample, line, col)
    assert "innermost node" in out
    assert "node chain" in out
    assert "enclosing scopes" in out
    assert "def outer" in out


def test_find_node_at_position_in_method_scope(sample):
    from pathlib import Path

    src = Path(sample).read_text().splitlines()
    line = next(i + 1 for i, l in enumerate(src) if "match score:" in l)
    col = src[line - 1].index("score")
    out = find_node_at_position(sample, line, col)
    assert "Widget.classify" in out
    assert "class Widget" in out


def test_find_node_at_position_out_of_range(sample):
    with pytest.raises(AstToolError):
        find_node_at_position(sample, 100000, 0)


def test_find_node_at_position_on_blank(sample):
    from pathlib import Path

    src = Path(sample).read_text().splitlines()
    line = next(i + 1 for i, l in enumerate(src) if not l.strip())
    out = find_node_at_position(sample, line, 0)
    assert "No AST node covers" in out or "innermost node" in out
