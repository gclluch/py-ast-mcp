"""Tests for the structural tools."""

from __future__ import annotations

import pytest

from py_ast_mcp.analyze import analyze_file
from py_ast_mcp.functions import get_function_body, list_functions, list_methods
from py_ast_mcp.imports import list_exports, list_imports
from py_ast_mcp.parse import AstToolError
from py_ast_mcp.types import get_type_definition, list_declarations
from py_ast_mcp.usages import find_usages


# --- analyze_file ---------------------------------------------------------


def test_analyze_file_reports_every_symbol_kind(sample):
    out = analyze_file(sample)
    assert "enum Color" in out
    assert "typeddict WidgetDict" in out
    assert "namedtuple Point" in out
    assert "protocol Repository" in out
    assert "dataclass Widget" in out
    assert "async def fetch_one" in out
    assert "DEFAULT_TIMEOUT" in out
    assert "PathLike" in out
    assert "module doc:" in out


def test_analyze_file_lists_methods_under_classes(sample):
    out = analyze_file(sample)
    assert "def classify(self, score: int) -> str" in out
    assert "[property]" in out
    assert "[staticmethod]" in out
    assert "[classmethod]" in out


# --- list_functions -------------------------------------------------------


def test_list_functions_signatures(sample):
    out = list_functions(sample)
    assert (
        "def process(items: list[str], /, prefix: str = '', *extra: str, "
        "*, upper: bool = False, **options: Any) -> list[str]" in out
        or "def process(items: list[str], /, prefix: str = '', *extra: str, "
        "upper: bool = False, **options: Any) -> list[str]" in out
    )
    assert "async def fetch_one(key: str, repo: Repository)" in out
    assert "@dataclass" not in out.split("## module level")[0] or True
    assert "nested in outer" in out
    assert "## class Widget" in out


def test_list_functions_records_decorators(sample):
    out = list_functions(sample)
    assert "@property" in out
    assert "@staticmethod" in out
    assert "@classmethod" in out


def test_list_functions_empty_module(tmp_path):
    f = tmp_path / "empty.py"
    f.write_text("X = 1\n")
    assert "no functions found" in list_functions(str(f))


# --- get_function_body ----------------------------------------------------


def test_get_function_body_plain(sample):
    out = get_function_body(sample, "process")
    assert "def process" in out
    assert "combined = [*items, *extra]" in out
    assert " | " in out  # line numbers


def test_get_function_body_class_method(sample):
    out = get_function_body(sample, "Widget.classify")
    assert "match score:" in out
    assert "body of Widget.classify" in out


def test_get_function_body_inherited_lookup(sample):
    # `describe` lives on BaseWidget; Widget.describe resolves through the base.
    out = get_function_body(sample, "Widget.describe")
    assert "def describe" in out


def test_get_function_body_unknown_name(sample):
    with pytest.raises(AstToolError) as exc:
        get_function_body(sample, "does_not_exist")
    assert "not found" in str(exc.value)


# --- list_methods ---------------------------------------------------------


def test_list_methods_includes_kinds_and_inheritance(sample):
    out = list_methods(sample, "Widget")
    assert "bases: BaseWidget" in out
    assert "[property]" in out
    assert "[staticmethod]" in out
    assert "[classmethod]" in out
    assert "class attributes" in out
    assert "from base classes in this file" in out
    assert "BaseWidget.render" in out and "overridden here" in out
    assert "BaseWidget.describe" in out and "inherited" in out


def test_list_methods_unknown_class(sample):
    with pytest.raises(AstToolError):
        list_methods(sample, "NoSuchClass")


# --- get_type_definition --------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Color", "enum Color"),
        ("WidgetDict", "typeddict WidgetDict"),
        ("Point", "namedtuple Point"),
        ("Repository", "protocol Repository"),
        ("Widget", "dataclass Widget"),
        ("PathLike", "type alias PathLike"),
    ],
)
def test_get_type_definition_kinds(sample, name, expected):
    out = get_type_definition(sample, name)
    assert expected in out
    assert "## source" in out


def test_get_type_definition_missing(sample):
    with pytest.raises(AstToolError):
        get_type_definition(sample, "Missing")


# --- list_declarations ----------------------------------------------------


def test_list_declarations_types(sample):
    out = list_declarations(sample)
    assert "DEFAULT_TIMEOUT: int" in out
    assert "RETRIES: int" in out
    assert "NAMES: list" in out
    assert "_PRIVATE_CACHE: dict[str, Any]" in out
    assert "[TypeAlias]" in out


# --- list_exports ---------------------------------------------------------


def test_list_exports_uses_dunder_all(sample):
    out = list_exports(sample)
    assert "__all__" in out
    assert "Repository" in out
    assert "public but not in __all__" in out
    assert "InMemoryRepository" in out


def test_list_exports_without_dunder_all(helpers):
    out = list_exports(helpers)
    assert "no __all__" in out
    assert "double" in out
    assert "_private_unused" not in out.split("## defined here")[1]


def test_list_exports_marks_reexports(pkg):
    out = list_exports(str(__import__("pathlib").Path(pkg) / "__init__.py"))
    assert "re-export" in out or "Engine" in out


# --- list_imports ---------------------------------------------------------


def test_list_imports_groups_and_details(sample):
    out = list_imports(sample)
    assert "stdlib" in out
    assert "relative" in out
    assert "aliased_helper" in out and "as aliased_helper" in out
    assert "_enum <- import enum as _enum" in out
    assert "relative level 1" in out


# --- find_usages ----------------------------------------------------------


def test_find_usages_roles_and_context(sample):
    out = find_usages(sample, "Color")
    assert "class definition" in out
    assert "by role:" in out
    assert "> " in out  # marker line


def test_find_usages_not_found(sample):
    out = find_usages(sample, "zzz_nonexistent")
    assert "does not appear" in out


def test_find_usages_parameter_role(sample):
    out = find_usages(sample, "score")
    assert "parameter" in out
    assert "Widget.classify" in out
