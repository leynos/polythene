"""Behavioural coverage for :func:`polythene.cmd_utils.run_cmd`."""

from __future__ import annotations

import shlex
from typing import cast

import pytest
from _pytest.capture import CaptureResult
from plumbum import local
from pytest_bdd import parsers, scenarios, then, when

from polythene.cmd_utils import run_cmd

scenarios("../features/command_execution.feature")


@pytest.fixture()
def context() -> dict[str, object]:
    return {}


@when(parsers.parse('I execute run_cmd with sequence "{command}" in foreground'))
def run_sequence(command: str, capsys, context: dict[str, object]) -> None:
    args = shlex.split(command)
    capsys.readouterr()
    result = run_cmd(args, fg=True)
    captured = capsys.readouterr()
    context["result"] = result
    context["captured"] = captured


@when(parsers.parse('I execute run_cmd with adapter "{snippet}"'))
def run_adapter(snippet: str, capsys, context: dict[str, object]) -> None:
    cmd = local["python"]["-c", snippet]
    capsys.readouterr()
    result = run_cmd(cmd, fg=True)
    captured = capsys.readouterr()
    context["result"] = result
    context["captured"] = captured


@then("run_cmd returns 0")
def assert_success(context: dict[str, object]) -> None:
    assert context.get("result") == 0


@then(parsers.parse('the stderr log includes "{text}"'))
def assert_stderr_contains(context: dict[str, object], text: str) -> None:
    captured = context.get("captured")
    assert isinstance(captured, CaptureResult)
    stderr = cast(str, captured.err)
    assert text in stderr
