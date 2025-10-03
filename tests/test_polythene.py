"""Tests for the standalone polythene CLI package."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import polythene


@pytest.fixture()
def cli_runner() -> CliRunner:
    """Return a Typer CLI runner configured for polythene."""
    return CliRunner()


def test_cmd_pull_exports_rootfs(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ``pull`` command exports the rootfs and prints the generated UUID."""
    calls: list[tuple[str, Path, int | None]] = []

    monkeypatch.setattr(polythene, "generate_uuid", lambda: "uuid-1234")

    def _fake_export(image: str, dest: Path, *, timeout: int | None = None) -> None:
        calls.append((image, dest, timeout))
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(polythene, "export_rootfs", _fake_export)

    result = cli_runner.invoke(
        polythene.app,
        [
            "pull",
            "docker.io/library/busybox:latest",
            "--store",
            tmp_path.as_posix(),
            "--timeout",
            "30",
        ],
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
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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

    result = cli_runner.invoke(
        polythene.app,
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
        ],
    )

    assert result.exit_code == 0
    assert calls == [(root, "echo 'hello world'", 15)]


def test_cmd_exec_reports_missing_root(cli_runner: CliRunner, tmp_path: Path) -> None:
    """``exec`` exits with an error when the requested rootfs is missing."""
    result = cli_runner.invoke(
        polythene.app,
        [
            "exec",
            "missing",  # UUID that does not exist
            "--store",
            tmp_path.as_posix(),
            "--",
            "true",
        ],
    )

    assert result.exit_code == 1
    assert "No such UUID rootfs" in result.stderr
