"""Shared pytest fixtures for the Polythene test suite."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from runpy import run_module
import sys
from typing import Callable, Sequence

import pytest

import polythene


@dataclass(slots=True)
class CliResult:
    """Container capturing CLI output and exit status."""

    exit_code: int
    stdout: str
    stderr: str


@pytest.fixture()
def run_cli() -> Callable[[Sequence[str]], CliResult]:
    """Return a helper that invokes the Cyclopts app and captures output."""

    def _invoke(args: Sequence[str]) -> CliResult:
        stdout_buffer = StringIO()
        stderr_buffer = StringIO()
        exit_code = 0

        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                polythene.app(list(args))
        except SystemExit as exc:  # pragma: no cover - exercised in assertions
            code = exc.code
            if code is None:
                exit_code = 0
            elif isinstance(code, int):
                exit_code = code
            else:
                exit_code = int(code)
        return CliResult(
            exit_code=exit_code,
            stdout=stdout_buffer.getvalue(),
            stderr=stderr_buffer.getvalue(),
        )

    return _invoke


@pytest.fixture()
def run_module_cli() -> Callable[[Sequence[str]], CliResult]:
    """Return a helper that invokes ``python -m polythene``."""

    def _invoke(args: Sequence[str]) -> CliResult:
        stdout_buffer = StringIO()
        stderr_buffer = StringIO()
        exit_code = 0
        argv = ["python -m polythene", *args]
        patcher = pytest.MonkeyPatch()
        patcher.setattr(sys, "argv", list(argv), raising=False)

        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                run_module("polythene", run_name="__main__")
        except SystemExit as exc:  # pragma: no cover - exercised in assertions
            code = exc.code
            if code is None:
                exit_code = 0
            elif isinstance(code, int):
                exit_code = code
            else:
                exit_code = int(code)
        finally:
            patcher.undo()

        return CliResult(
            exit_code=exit_code,
            stdout=stdout_buffer.getvalue(),
            stderr=stderr_buffer.getvalue(),
        )

    return _invoke
