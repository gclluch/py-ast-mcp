"""Tests for parse.py and format.py."""

from __future__ import annotations

import ast

import pytest

from py_ast_mcp import format as fmt
from py_ast_mcp.parse import (
    AstToolError,
    ParseError,
    is_test_file,
    is_test_filename,
    iter_py_files,
    parse_file,
    parse_source,
)


def test_parse_file_caches_by_mtime(sample):
    a = parse_file(sample)
    b = parse_file(sample)
    assert a is b


def test_parse_file_rewrites_cache_when_file_changes(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("x = 1\n")
    first = parse_file(str(f))
    f.write_text("x = 1\ny = 2\n")
    second = parse_file(str(f))
    assert first is not second
    assert len(second.lines) == 2


def test_parse_error_has_line_and_column(broken):
    with pytest.raises(ParseError) as exc:
        parse_file(broken)
    assert exc.value.line == 1
    assert exc.value.col is not None
    rendered = exc.value.render()
    assert "cannot parse" in rendered
    assert "line 1" in rendered


def test_missing_file_raises_ast_tool_error(tmp_path):
    with pytest.raises(AstToolError):
        parse_file(str(tmp_path / "nope.py"))


def test_directory_raises_ast_tool_error(fixtures_dir):
    with pytest.raises(AstToolError):
        parse_file(str(fixtures_dir))


def test_qualname_and_scopes(sample):
    pm = parse_file(sample)
    methods = [
        n
        for n in ast.walk(pm.tree)
        if isinstance(n, ast.FunctionDef) and n.name == "classify"
    ]
    assert pm.qualname(methods[0]) == "Widget.classify"
    scopes = pm.enclosing_scopes(methods[0])
    assert any(isinstance(s, ast.ClassDef) for s in scopes)


def test_numbered_source(sample):
    pm = parse_file(sample)
    text = pm.numbered(1, 3)
    assert text.splitlines()[0].startswith("1 | ")


def test_iter_py_files_skips_tests_relative_to_root(fixtures_dir):
    files = {p.name for p in iter_py_files(fixtures_dir)}
    assert "sample.py" in files
    assert "core.py" in files


def test_skip_dirs_are_judged_relative_to_scan_root(tmp_path):
    """A repo living under a directory named ``build`` is still scannable.

    Skip names must be matched below the root, not anywhere in the absolute
    path, or such a project yields zero files.
    """
    root = tmp_path / "build" / "myproject"
    (root / "dist").mkdir(parents=True)
    (root / "mod.py").write_text("x = 1\n")
    (root / "dist" / "generated.py").write_text("y = 2\n")

    found = {p.name for p in iter_py_files(root)}
    assert "mod.py" in found
    assert "generated.py" not in found


def test_is_test_filename():
    assert is_test_filename("test_thing.py")
    assert is_test_filename("thing_test.py")
    assert not is_test_filename("thing.py")
    assert is_test_file("/a/tests/thing.py")
    assert not is_test_file("/a/tests/thing.py", root="/a/tests")


def test_parse_source_roundtrip():
    pm = parse_source("def f():\n    return 1\n", "mem.py")
    assert pm.module_name == "mem"
    assert len(pm.lines) == 2


def test_format_helpers():
    assert fmt.loc(line=3, end=3) == "L3"
    assert fmt.loc(line=3, end=9) == "L3-9"
    assert fmt.truncate("a" * 200, 20).endswith("…")
    assert fmt.plural(1, "file") == "1 file"
    assert fmt.plural(2, "file") == "2 files"
    rendered = fmt.table([["a", "1"], ["bb", "22"]], ["name", "n"])
    assert "name" in rendered and "---" in rendered
    assert fmt.unparse(None) == ""
