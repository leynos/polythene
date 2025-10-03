"""Tests for the standalone polythene CLI package."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import importlib

import pytest
from conftest import CliResult

import polythene


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


def test_cmd_pull_retries_existing_uuid(
    run_cli: Callable[[Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The ``pull`` command regenerates a UUID after a collision."""
    uuids = iter(["uuid-1", "uuid-2"])
    monkeypatch.setattr(polythene, "generate_uuid", lambda: next(uuids))

    call_count = 0

    def _fake_export(image: str, dest: Path, *, timeout: int | None = None) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FileExistsError(dest)
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(polythene, "export_rootfs", _fake_export)

    result = run_cli(["pull", "busybox", "--store", tmp_path.as_posix()])

    assert result.exit_code == 0
    assert result.stdout.strip() == "uuid-2"
    assert call_count == 2


class _DummyBackend:
    def __init__(self, return_code: int | None, *, requires_root: bool = False) -> None:
        self.return_code = return_code
        self.requires_root = requires_root
        self.calls: list[tuple[Path, str, int | None]] = []

    def run(
        self,
        root: Path,
        inner_cmd: str,
        *,
        timeout: int | None,
        logger: Callable[[str], None],
        container_tmp: Path,
    ) -> int | None:
        self.calls.append((root, inner_cmd, timeout))
        return self.return_code


def test_cmd_exec_uses_first_available_backend(
    run_cli: Callable[[Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The ``exec`` command runs using the first available backend."""
    root = tmp_path / "uuid-5678"
    root.mkdir(parents=True)

    primary = _DummyBackend(0)
    fallback = _DummyBackend(None)
    monkeypatch.setattr(polythene, "BACKENDS", (primary, fallback))
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
    assert primary.calls == [(root, "echo 'hello world'", 15)]
    assert fallback.calls == []


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


def test_cmd_exec_propagates_backend_error(
    run_cli: Callable[[Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-zero backend exit code terminates the CLI with that status."""
    root = tmp_path / "uuid-9999"
    root.mkdir()

    unavailable = _DummyBackend(None)
    failing = _DummyBackend(42)
    monkeypatch.setattr(polythene, "BACKENDS", (unavailable, failing))
    monkeypatch.setattr(polythene, "IS_ROOT", True)

    result = run_cli(
        [
            "exec",
            "uuid-9999",
            "--store",
            tmp_path.as_posix(),
            "--",
            "false",
        ]
    )

    assert result.exit_code == 42
    assert unavailable.calls and failing.calls


def test_cmd_exec_requires_command(
    run_cli: Callable[[Sequence[str]], CliResult],
    tmp_path: Path,
) -> None:
    """``exec`` exits with an error when invoked without a command."""
    rootfs = tmp_path / "uuid-empty"
    rootfs.mkdir()

    result = run_cli(
        [
            "exec",
            "uuid-empty",
            "--store",
            tmp_path.as_posix(),
            "--",
        ]
    )

    assert result.exit_code == 1
    assert "requires an argument" in result.stdout


def test_module_main_delegates_to_package_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``python -m polythene`` calls the package ``main`` function."""

    called = False

    def _stub() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(polythene, "main", _stub)
    module_main = importlib.import_module("polythene.__main__").main

    module_main()

    assert called


def test_main_accepts_custom_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """The package ``main`` helper forwards explicit argv tokens to Cyclopts."""

    received: list[str] = []

    def _capture(tokens: Sequence[str]) -> None:
        received[:] = list(tokens)

    monkeypatch.setattr(polythene, "app", _capture)

    polythene.main(["pull", "busybox"])

    assert received == ["pull", "busybox"]
