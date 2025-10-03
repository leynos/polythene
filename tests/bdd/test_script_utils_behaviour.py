"""Behavioural coverage for script utility helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from polythene import script_utils

scenarios("../features/script_utilities.feature")


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def script_context() -> dict[str, object]:
    return {}


@given("a temporary workspace")
def given_workspace(workspace: Path, script_context: dict[str, object]) -> Path:
    script_context["workspace"] = workspace
    return workspace


@given(parsers.parse('the files "{first}", "{second}" exist'))
def create_files(first: str, second: str, workspace: Path) -> None:
    for name in (first, second):
        (workspace / name).write_text("ok", encoding="utf-8")


@when(parsers.parse('I call ensure_directory for "{relative}"'))
def call_ensure_directory(relative: str, workspace: Path) -> None:
    script_utils.ensure_directory(workspace / relative)


@when(parsers.parse('I request a unique match for "{relative}"'))
def call_unique_match(
    relative: str, workspace: Path, script_context: dict[str, object]
) -> None:
    result = script_utils.unique_match([workspace / relative], description="file")
    script_context["unique"] = result


@then(parsers.parse('the path "{relative}" exists'))
def assert_path_exists(relative: str, workspace: Path) -> None:
    assert (workspace / relative).exists()


@then(parsers.parse('the unique match is "{expected}"'))
def assert_unique(expected: str, script_context: dict[str, object]) -> None:
    result = script_context.get("unique")
    assert isinstance(result, Path)
    assert result.name == expected
