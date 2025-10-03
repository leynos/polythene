"""Tests for the standalone polythene CLI package."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
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


def test_cmd_pull_exports_rootfs(
    run_cli: Callable[[Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The ``pull`` command exports the rootfs and prints the generated UUID."""
    calls: list[tuple[str, Path, int | None]] = []

    monkeypatch.setattr(polythene, "generate_uuid", lambda: "uuid-1234")

    def _fake_export(image: str, dest: Path, *, timeout: int | None = None) -> None:
        calls.append((image, dest, timeout))
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(polythene, "export_rootfs", _fake_export)

    result = run_cli(
        [
            "pull",
            "docker.io/library/busybox:latest",
            "--store",
            tmp_path.as_posix(),
            "--timeout",
            "30",
        ]
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "uuid-1234"

    assert calls == [
        (
            "docker.io/library/busybox:latest",
            tmp_path / "uuid-1234",
            30,
        )
    ]
    assert (tmp_path / "uuid-1234" / "dev").is_dir()
    assert (tmp_path / "uuid-1234" / "tmp").is_dir()


def test_cmd_exec_uses_first_available_runner(
    run_cli: Callable[[Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The ``exec`` command runs using the first available backend."""
    root = tmp_path / "uuid-5678"
    root.mkdir(parents=True)

    calls: list[tuple[Path, str, int | None]] = []

    def _fake_bwrap(path: Path, inner_cmd: str, timeout: int | None = None) -> int:
        calls.append((path, inner_cmd, timeout))
        return 0

    def _fail_proot(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("proot should not be invoked when bubblewrap succeeds")

    monkeypatch.setattr(polythene, "run_with_bwrap", _fake_bwrap)
    monkeypatch.setattr(polythene, "run_with_proot", _fail_proot)
    monkeypatch.setattr(polythene, "IS_ROOT", False)

    result = run_cli(
        [
            "exec",
            "uuid-5678",
            "--store",
            tmp_path.as_posix(),
            "--timeout",
            "15",
            "--",
            "echo",
            "hello world",
        ]
    )

    assert result.exit_code == 0
    assert calls == [(root, "echo 'hello world'", 15)]


def test_cmd_exec_reports_missing_root(
    run_cli: Callable[[Sequence[str]], CliResult],
    tmp_path: Path,
) -> None:
    """``exec`` exits with an error when the requested rootfs is missing."""
    result = run_cli(
        [
            "exec",
            "missing",  # UUID that does not exist
            "--store",
            tmp_path.as_posix(),
            "--",
            "true",
        ]
    )

    assert result.exit_code == 1
    assert "No such UUID rootfs" in result.stderr
