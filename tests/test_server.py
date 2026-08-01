"""Tests for the MCP server wiring itself."""

from __future__ import annotations

import asyncio

from mcp.client import Client

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


async def _dispatch(tool_name, arguments):
    """Call a tool the way a real client does, so `is_error` is observable.

    `mcp.call_tool` lets exceptions escape; only the request handler maps them
    onto `CallToolResult.is_error`, which is the contract under test.
    """
    async with Client(mcp) as client:
        return await client.call_tool(tool_name, arguments)


def _call_expecting_error(tool_name, /, **kwargs) -> str:
    result = asyncio.run(_dispatch(tool_name, kwargs))
    assert result.is_error, f"{tool_name} reported failure as success"
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


def test_syntax_error_is_flagged_as_an_error(broken):
    text = _call_expecting_error("analyze_file", path=broken)
    assert "ERROR: cannot parse" in text
    assert "line 1" in text


def test_missing_file_is_flagged_as_an_error(tmp_path):
    text = _call_expecting_error("analyze_file", path=str(tmp_path / "nope.py"))
    assert "ERROR:" in text
    assert "File not found" in text


def test_unknown_symbol_is_flagged_as_an_error(sample):
    text = _call_expecting_error(
        "get_function_body", path=sample, name="not_a_function"
    )
    assert "ERROR:" in text


def test_failure_does_not_leak_a_traceback(broken):
    text = _call_expecting_error("analyze_file", path=broken)
    assert "Traceback" not in text
    assert 'File "' not in text


def test_success_is_not_flagged_as_an_error(sample):
    result = asyncio.run(_dispatch("analyze_file", {"path": sample}))
    assert result.is_error is False


def test_server_has_instructions():
    assert mcp.instructions and "structural analysis" in mcp.instructions
