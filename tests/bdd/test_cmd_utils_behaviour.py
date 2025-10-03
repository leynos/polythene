"""Behavioural tests for the command execution helper functions."""

from __future__ import annotations

import shlex
import typing as typ

import pytest
from _pytest.capture import CaptureResult
from plumbum import local
from pytest_bdd import parsers, scenarios, then, when

from polythene.cmd_utils import run_cmd

if typ.TYPE_CHECKING:
    import polythene.cmd_utils as cmd_utils_module
else:  # pragma: no cover - runtime shim for annotations
    cmd_utils_module = typ.cast("object", None)

Context = dict[str, object]

scenarios("../features/command_execution.feature")


def _build_command(command: str) -> cmd_utils_module.Command:
    """Construct a plumbum command from ``command`` or raise ``ValueError``."""
    parts = shlex.split(command)
    if not parts:
        msg = "Command must contain at least one token"
        raise ValueError(msg)
    base = local[parts[0]]
    return base if len(parts) == 1 else base[tuple(parts[1:])]


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
    """Execute a shell command by constructing a plumbum invocation."""
    try:
        cmd = _build_command(command)
    except ValueError as exc:
        context["error"] = exc
        return
    capsys.readouterr()
    try:
        result = run_cmd(cmd, fg=True)
    except (TypeError, TimeoutError) as exc:
        context["error"] = exc
        return
    captured = capsys.readouterr()
    context["result"] = result
    context["captured"] = captured
    context.pop("error", None)


@when("I execute run_cmd with no command in foreground")
def run_empty_command(
    capsys: pytest.CaptureFixture[str],
    context: Context,
) -> None:
    """Execute the shared command step with an empty command string."""
    run_command("", capsys, context)


@when(parsers.parse('I execute run_cmd with adapter "{snippet}"'))
def run_adapter(
    snippet: str,
    capsys: pytest.CaptureFixture[str],
    context: Context,
) -> None:
    """Execute a Python snippet via a plumbum adapter."""
    cmd = local["python"]["-c", snippet]
    capsys.readouterr()
    result = run_cmd(cmd, fg=True)
    captured = capsys.readouterr()
    context["result"] = result
    context["captured"] = captured
    context["snippet"] = snippet
    context.pop("error", None)


@when("I execute run_cmd with an invalid command object")
def run_invalid_command(context: Context) -> None:
    """Attempt to execute run_cmd with an invalid command value."""
    invalid = typ.cast("cmd_utils_module.Command", object())
    with pytest.raises(TypeError) as exc_info:
        run_cmd(invalid)
    context["error"] = exc_info.value


@then("run_cmd returns 0")
def assert_success(context: Context) -> None:
    """Ensure ``run_cmd`` reports success."""
    assert context.get("result") == 0


@then(parsers.parse('the stderr log includes "{text}"'))
def assert_stderr_contains(context: Context, text: str) -> None:
    """Check that the captured stderr output includes ``text``."""
    captured = context.get("captured")
    assert isinstance(captured, CaptureResult)
    stderr = str(captured.err)
    assert text in stderr


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
