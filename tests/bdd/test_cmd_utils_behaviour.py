"""Behavioural tests for the command execution helper functions."""

from __future__ import annotations

import shlex
import sys
import typing as typ

import pytest
from _pytest.capture import CaptureResult
from cuprum import Program, ProgramCatalogue, ProjectSettings, SafeCmd, sh
from pytest_bdd import parsers, scenarios, then, when

from polythene.cmd_utils import fail_on_error, run_cmd

if typ.TYPE_CHECKING:
    import polythene.cmd_utils as cmd_utils_module

Context = dict[str, object]

scenarios("../features/command_execution.feature")

#: The scenario steps name programs the way a shell user would. ``python`` is
#: registered under the running interpreter's absolute path so the feature runs
#: that interpreter rather than whichever one ``PATH`` happens to offer.
CATALOGUE = ProgramCatalogue(
    projects=(
        ProjectSettings(
            name="polythene-behaviour",
            programs=(
                Program("echo"),
                Program("false"),
                Program(sys.executable),
            ),
        ),
    )
)
_ALIASES = {"python": sys.executable}


def _build_command(command: str) -> SafeCmd:
    """Build a curated command from a shell-style ``command`` string."""
    parts = shlex.split(command)
    name = _ALIASES.get(parts[0], parts[0])
    return sh.make(Program(name), catalogue=CATALOGUE)(*parts[1:])


@pytest.fixture
def context() -> Context:
    """Provide shared state for step implementations."""
    return {}


@when(parsers.parse('I execute run_cmd with command "{command}" in foreground'))
def run_command(
    command: str,
    capsys: pytest.CaptureFixture[str],
    context: Context,
) -> None:
    """Execute a curated command in the foreground and record its outcome."""
    capsys.readouterr()
    outcome = run_cmd(_build_command(command), fg=True)
    context["result"] = fail_on_error(outcome)
    context["captured"] = capsys.readouterr()
    context.pop("error", None)


@when(parsers.parse('I execute run_cmd with adapter "{snippet}"'))
def run_adapter(
    snippet: str,
    capsys: pytest.CaptureFixture[str],
    context: Context,
) -> None:
    """Execute a Python snippet through the curated interpreter."""
    capsys.readouterr()
    python = sh.make(Program(sys.executable), catalogue=CATALOGUE)
    outcome = run_cmd(python("-c", snippet), fg=True)
    context["result"] = fail_on_error(outcome)
    context["captured"] = capsys.readouterr()
    context.pop("error", None)


@when("I execute run_cmd with an invalid command object")
def run_invalid_command(context: Context) -> None:
    """Attempt to execute run_cmd with a value that is not a cuprum command."""
    invalid = typ.cast("cmd_utils_module.Command", object())
    with pytest.raises(TypeError) as exc_info:
        run_cmd(invalid)
    context["error"] = exc_info.value


@then("run_cmd returns 0")
def assert_success(context: Context) -> None:
    """Ensure ``run_cmd`` reports success."""
    assert context.get("result") == 0


@then(parsers.parse("run_cmd returns {status:d}"))
def assert_status(context: Context, status: int) -> None:
    """Ensure ``run_cmd`` reports ``status``."""
    assert context.get("result") == status


@then("no exception is recorded")
def assert_no_error(context: Context) -> None:
    """Check the failing child was reported as data, not raised."""
    assert "error" not in context


@then(parsers.parse('the stderr log includes "{text}"'))
def assert_stderr_contains(context: Context, text: str) -> None:
    """Check that the captured stderr output includes ``text``."""
    captured = context.get("captured")
    assert isinstance(captured, CaptureResult)
    assert text in str(captured.err)


@then(parsers.parse('run_cmd raises a {exc_type} containing "{text}"'))
def assert_error_contains(context: Context, exc_type: str, text: str) -> None:
    """Check the stored error matches ``exc_type`` and message fragment."""
    error = context.get("error")
    assert error is not None, "Expected an error but none was recorded"
    mapping = {"TypeError": TypeError, "ValueError": ValueError}
    expected_type = mapping.get(exc_type)
    assert expected_type is not None, f"Unknown exception type {exc_type!r}"
    assert isinstance(error, expected_type)
    assert text in str(error)
