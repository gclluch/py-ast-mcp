"""Tests for call_graph and get_callers."""

from __future__ import annotations

import pytest

from py_ast_mcp.callgraph import build_graph, call_graph, get_callers
from py_ast_mcp.parse import AstToolError


def test_call_graph_emits_mermaid(sample):
    out = call_graph(sample)
    assert "```mermaid" in out
    assert "flowchart TD" in out
    assert "-->" in out
    assert "## edges" in out


def test_call_graph_resolves_local_calls(sample):
    out = call_graph(sample)
    assert "outer -> outer.inner" in out or "outer.inner" in out
    assert "outer.inner -> _internal_helper" in out
    assert "main -> process" in out
    assert "fetch_all -> fetch_one" in out


def test_call_graph_resolves_self_method_calls(sample):
    out = call_graph(sample)
    assert "BaseWidget.render -> BaseWidget.describe" in out


def test_call_graph_direction(sample):
    assert "flowchart LR" in call_graph(sample, direction="LR")
    assert "flowchart BT" in call_graph(sample, direction="BT")


def test_call_graph_rejects_bad_direction(sample):
    with pytest.raises(AstToolError):
        call_graph(sample, direction="SIDEWAYS")


def test_call_graph_rejects_bad_scope(sample):
    with pytest.raises(AstToolError):
        call_graph(sample, scope="universe")


def test_call_graph_include_external(sample):
    without = call_graph(sample, include_external=False)
    with_ext = call_graph(sample, include_external=True)
    assert "print" not in without
    assert "print" in with_ext
    assert "-.->" in with_ext


def test_call_graph_rooted_at_function(sample):
    out = call_graph(sample, function="main")
    assert "rooted at main" in out
    assert "main -> process" in out
    assert "fetch_all -> fetch_one" not in out


def test_call_graph_unknown_function(sample):
    with pytest.raises(AstToolError):
        call_graph(sample, function="nope")


def test_call_graph_package_scope_crosses_files(pkg_core):
    out = call_graph(pkg_core, scope="package")
    assert "util.normalize" in out
    assert "Engine.store -> validate" in out
    assert "call_graph (package)" in out


def test_call_graph_reports_uncalled_functions(pkg_core):
    out = call_graph(pkg_core, scope="package")
    assert "uncalled / non-calling functions" in out


def test_build_graph_skips_unparseable_files(fixtures_dir):
    graph = build_graph(str(fixtures_dir / "sample.py"), scope="package")
    assert graph.errors
    assert any("broken.py" in e for e in graph.errors)


def test_get_callers_direct(sample):
    out = get_callers(sample, "_internal_helper")
    assert "direct callers" in out
    assert "outer.inner" in out


def test_get_callers_transitive_and_entry_points(sample):
    out = get_callers(sample, "_internal_helper")
    assert "transitive callers" in out
    assert "entry points reaching it" in out
    assert "main" in out


def test_get_callers_none(sample):
    out = get_callers(sample, "main")
    assert "No callers found" in out


def test_get_callers_package_scope(pkg_core):
    out = get_callers(pkg_core, "normalize", scope="package")
    assert "Engine.store" in out
    assert "core.py" in out


def test_get_callers_unknown(sample):
    with pytest.raises(AstToolError):
        get_callers(sample, "nope")
