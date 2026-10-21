"""Shared pytest fixtures for the Polythene test suite."""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
import typing as typ
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from runpy import run_module

import pytest

import polythene
import polythene.isolation as isolation
from tests.support.cli import CliResult

__all__ = [
    "CliResult",
    "run_cli",
    "run_console_script_cli",
    "run_module_cli",
    "run_module_cli_process",
    "run_real_process_cli",
]

_TERMINAL_ENVIRONMENT = {
    "COLUMNS": "240",
    "NO_COLOR": "1",
    "TERM": "dumb",
}


def _set_deterministic_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove CLI configuration and make terminal output predictable."""
    for name in (
        "POLYTHENE_ISOLATION",
        "POLYTHENE_STORE",
        "POLYTHENE_VERBOSE",
        "FORCE_COLOR",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in _TERMINAL_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(isolation, "VERBOSE", False)


def _subprocess_environment(empty_bin: Path) -> dict[str, str]:
    """Return a scrubbed environment for real CLI process tests."""
    empty_bin.mkdir()
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("POLYTHENE_") and name != "FORCE_COLOR"
    }
    environment.update(_TERMINAL_ENVIRONMENT)
    interpreter_directory = Path(sys.executable).resolve().parent
    environment["PATH"] = os.pathsep.join(
        (empty_bin.as_posix(), interpreter_directory.as_posix())
    )
    return environment


def _run_process(command: list[str], environment: dict[str, str]) -> CliResult:
    """Run a CLI entry point and capture its process boundary."""
    # The fixed fixture commands must cross a real process boundary here.
    completed = subprocess.run(  # noqa: S603, TID251
        command,
        capture_output=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        text=True,
        timeout=30,
    )
    return CliResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _capture_cli_result(invoke: typ.Callable[[], object]) -> CliResult:
    """Capture CLI output and translate its process-style exit signal."""
    stdout_buffer = StringIO()
    stderr_buffer = StringIO()
    exit_code = 0

    try:
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            invoke()
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


@pytest.fixture
def run_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> typ.Callable[[typ.Sequence[str]], CliResult]:
    """Return a helper that invokes the Cyclopts app and captures output."""
    _set_deterministic_terminal(monkeypatch)

    def _invoke(args: typ.Sequence[str]) -> CliResult:
        """Invoke the in-process app with deterministic terminal settings."""
        return _capture_cli_result(lambda: polythene.app(list(args)))

    return _invoke


@pytest.fixture
def run_module_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> typ.Callable[[typ.Sequence[str]], CliResult]:
    """Return a helper that invokes ``python -m polythene``."""
    _set_deterministic_terminal(monkeypatch)

    def _invoke(args: typ.Sequence[str]) -> CliResult:
        """Invoke the module entry point with a scoped argv value."""
        argv = ["python -m polythene", *args]

        with monkeypatch.context() as invocation_patch:
            invocation_patch.setattr(sys, "argv", list(argv), raising=False)
            return _capture_cli_result(
                lambda: run_module("polythene", run_name="__main__")
            )

    return _invoke


@pytest.fixture
def run_module_cli_process(
    tmp_path: Path,
) -> typ.Callable[[typ.Sequence[str]], CliResult]:
    """Return a helper that runs ``python -m polythene`` in a child process."""
    environment = _subprocess_environment(tmp_path / "empty-bin")

    def _invoke(args: typ.Sequence[str]) -> CliResult:
        """Run the module entry point in a sanitised child process."""
        return _run_process([sys.executable, "-m", "polythene", *args], environment)

    return _invoke


@pytest.fixture
def run_console_script_cli(
    tmp_path: Path,
) -> typ.Callable[[typ.Sequence[str]], CliResult]:
    """Return a helper that runs the installed ``polythene`` script."""
    scripts_directory = Path(sysconfig.get_path("scripts"))
    script_name = "polythene.exe" if os.name == "nt" else "polythene"
    script_path = scripts_directory / script_name
    if not script_path.is_file():
        skip = typ.cast("typ.Callable[[str], typ.NoReturn]", pytest.skip)
        skip(f"polythene console script is not installed at {script_path}")

    environment = _subprocess_environment(tmp_path / "empty-bin")

    def _invoke(args: typ.Sequence[str]) -> CliResult:
        """Run the installed console script in a sanitised child process."""
        return _run_process([script_path.as_posix(), *args], environment)

    return _invoke


@pytest.fixture(params=("run_module_cli_process", "run_console_script_cli"))
def run_real_process_cli(
    request: pytest.FixtureRequest,
) -> typ.Callable[[typ.Sequence[str]], CliResult]:
    """Run a test against each installed process entry point."""
    fixture_name = typ.cast("str", request.param)
    runner = request.getfixturevalue(fixture_name)
    return typ.cast("typ.Callable[[typ.Sequence[str]], CliResult]", runner)
