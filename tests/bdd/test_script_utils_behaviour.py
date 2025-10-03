"""Behaviour-driven tests for script utility helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from polythene import script_utils

Context = dict[str, object]

scenarios("../features/script_utilities.feature")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Expose the temporary directory to step implementations."""
    return tmp_path


@pytest.fixture
def script_context() -> Context:
    """Return a shared dictionary for storing intermediate results."""
    return {}


@given("a temporary workspace")
def given_workspace(workspace: Path, script_context: Context) -> Path:
    """Store the temporary workspace for later steps."""
    script_context["workspace"] = workspace
    return workspace


@given(parsers.parse('the files "{first}", "{second}" exist'))
def create_files(first: str, second: str, workspace: Path) -> None:
    """Create the specified files inside the workspace."""
    for name in (first, second):
        (workspace / name).write_text("ok", encoding="utf-8")


@when(parsers.parse('I call ensure_directory for "{relative}"'))
def call_ensure_directory(relative: str, workspace: Path) -> None:
    """Invoke ``ensure_directory`` for a relative path."""
    script_utils.ensure_directory(workspace / relative)


@when(parsers.parse('I request a unique match for "{relative}"'))
def call_unique_match(relative: str, workspace: Path, script_context: Context) -> None:
    """Store the unique match found by ``unique_match``."""
    result = script_utils.unique_match([workspace / relative], description="file")
    script_context["unique"] = result


@then(parsers.parse('the path "{relative}" exists'))
def assert_path_exists(relative: str, workspace: Path) -> None:
    """Assert that the requested path now exists."""
    assert (workspace / relative).exists()


@then(parsers.parse('the unique match is "{expected}"'))
def assert_unique(expected: str, script_context: Context) -> None:
    """Confirm that ``unique_match`` returned the expected filename."""
    result = script_context.get("unique")
    assert isinstance(result, Path)
    assert result.name == expected
