"""Tests for the MCP server wiring itself."""

from __future__ import annotations

import asyncio


from py_ast_mcp.server import mcp

EXPECTED_TOOLS = {
    "analyze_file",
    "list_functions",
    "get_function_body",
    "list_methods",
    "get_type_definition",
    "list_declarations",
    "list_exports",
    "list_imports",
    "find_usages",
    "call_graph",
    "get_callers",
    "code_complexity",
    "code_smells",
    "find_errors",
    "dead_code",
    "find_implementations",
    "get_doc",
    "analyze_package",
    "diff_ast",
    "find_node_at_position",
}


def _tools():
    return asyncio.run(mcp.list_tools())


def _call(tool_name, /, **kwargs) -> str:
    result = asyncio.run(mcp.call_tool(tool_name, kwargs))
    return "\n".join(getattr(b, "text", str(b)) for b in result.content)


def test_all_tools_registered():
    names = {t.name for t in _tools()}
    assert EXPECTED_TOOLS <= names, EXPECTED_TOOLS - names


def test_every_tool_has_description_and_schema():
    for tool in _tools():
        assert tool.description, tool.name
        assert tool.input_schema["type"] == "object"


def test_required_parameters_are_declared():
    by_name = {t.name: t for t in _tools()}
    assert by_name["analyze_file"].input_schema["required"] == ["path"]
    assert set(by_name["diff_ast"].input_schema["required"]) == {"old_path", "new_path"}
    cg = by_name["call_graph"].input_schema
    assert set(cg["properties"]) >= {
        "path",
        "function",
        "direction",
        "include_external",
        "scope",
    }


def test_call_tool_analyze_file(sample):
    out = _call("analyze_file", path=sample)
    assert "dataclass Widget" in out


def test_call_tool_call_graph(sample):
    out = _call("call_graph", path=sample, direction="LR")
    assert "flowchart LR" in out


def test_call_tool_dead_code(pkg):
    out = _call("dead_code", path=pkg)
    assert "_unused_private" in out


def test_syntax_error_returns_message_not_exception(broken):
    out = _call("analyze_file", path=broken)
    assert out.startswith("ERROR: cannot parse")
    assert "line 1" in out


def test_missing_file_returns_error_string(tmp_path):
    out = _call("analyze_file", path=str(tmp_path / "nope.py"))
    assert out.startswith("ERROR:")
    assert "File not found" in out


def test_unknown_symbol_returns_error_string(sample):
    out = _call("get_function_body", path=sample, name="not_a_function")
    assert out.startswith("ERROR:")


def test_server_has_instructions():
    assert mcp.instructions and "structural analysis" in mcp.instructions
