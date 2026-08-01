"""Tests for the optional `jedi` integration and its graceful degradation."""

from __future__ import annotations

import pytest

from py_ast_mcp import jedi_support
from py_ast_mcp.analyze import find_node_at_position
from py_ast_mcp.usages import find_usages

jedi_missing = pytest.mark.skipif(
    not jedi_support.available(), reason="jedi is not installed"
)


def test_available_is_boolean():
    assert isinstance(jedi_support.available(), bool)


@jedi_missing
def test_infer_at_resolves_cross_file(pkg_core):
    from pathlib import Path

    src = Path(pkg_core).read_text()
    line = next(
        i + 1 for i, l in enumerate(src.splitlines()) if "engine.store(key" in l
    )
    col = src.splitlines()[line - 1].index("store")
    results = jedi_support.infer_at(pkg_core, src, line, col)
    assert any("store" in r for r in results)


@jedi_missing
def test_find_node_at_position_includes_jedi_section(pkg_core):
    from pathlib import Path

    src = Path(pkg_core).read_text().splitlines()
    line = next(i + 1 for i, l in enumerate(src) if "engine.store(key" in l)
    col = src[line - 1].index("store")
    out = find_node_at_position(pkg_core, line, col)
    assert "semantic resolution (jedi)" in out


def test_degrades_when_jedi_absent(monkeypatch, pkg_core):
    monkeypatch.setattr(jedi_support, "_jedi", None)
    assert jedi_support.available() is False
    assert jedi_support.infer_at(pkg_core, "x = 1\n", 1, 0) == []
    assert jedi_support.references(pkg_core, "x = 1\n", 1, 0) == []
    # tools still work without the semantic section
    out = find_node_at_position(pkg_core, 1, 0)
    assert "semantic resolution (jedi)" not in out
    out = find_usages(pkg_core, "normalize")
    assert "cross-file references via jedi" not in out
    assert "usages of 'normalize'" in out


def test_infer_at_survives_bad_input(pkg_core):
    assert jedi_support.infer_at(pkg_core, "def (", 1, 0) == []
    assert jedi_support.references(pkg_core, "def (", 99999, 0) == []


@jedi_missing
def test_project_root_is_not_the_files_own_directory(nested_deep):
    """Regression: the root must be the repo, not ``Path(path).parent``.

    A root pinned to the file's folder makes every cross-directory reference
    invisible while still looking healthy on a flat package.
    """
    from pathlib import Path

    project = jedi_support._project(nested_deep)
    assert project is not None
    root = Path(str(project._path)).resolve()
    assert root != Path(nested_deep).parent.resolve()
    assert Path(nested_deep).resolve().is_relative_to(root)


@jedi_missing
def test_references_reach_sibling_directory(nested_deep):
    """``deep_helper`` is defined in sub/deep.py and used in other/consumer.py.

    Sibling is the geometry that matters: neither directory contains the other,
    so a root pinned to ``sub/`` sees only the definition itself. A reference in
    a *sub*directory would be found either way, which is why this has to be a
    sibling to be a real regression test.
    """
    from pathlib import Path

    src = Path(nested_deep).read_text()
    line = next(
        i + 1 for i, l in enumerate(src.splitlines()) if l.startswith("def deep_helper")
    )
    col = src.splitlines()[line - 1].index("deep_helper")
    refs = jedi_support.references(nested_deep, src, line, col)
    assert any("consumer.py" in r for r in refs), refs


@jedi_missing
def test_project_is_cached_per_root(nested_deep, nested_top):
    assert jedi_support._project(nested_deep) is jedi_support._project(nested_top)
