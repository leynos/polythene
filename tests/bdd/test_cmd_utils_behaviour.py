"""Behavioural tests for the command execution helper functions."""

from __future__ import annotations

import shlex

import pytest
from _pytest.capture import CaptureResult
from plumbum import local
from pytest_bdd import parsers, scenarios, then, when

from polythene.cmd_utils import run_cmd

Context = dict[str, object]

scenarios("../features/command_execution.feature")


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
    parts = shlex.split(command)
    if not parts:
        msg = "Command must contain at least one token"
        raise ValueError(msg)
    base = local[parts[0]]
    cmd = base if len(parts) == 1 else base[tuple(parts[1:])]
    capsys.readouterr()
    result = run_cmd(cmd, fg=True)
    captured = capsys.readouterr()
    context["result"] = result
    context["captured"] = captured


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
