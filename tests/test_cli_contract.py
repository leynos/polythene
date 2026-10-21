"""Contract tests for Polythene's in-process and process CLI boundaries."""

from __future__ import annotations

import os
import typing as typ

import polythene.isolation as isolation
from tests.support.backends import _DummyBackend
from tests.support.cli import (
    CliResult,
    assert_cli_diagnostic,
    assert_no_process_launch,
    normalise_cli_output,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    import pytest

PARSER_DIAGNOSTIC_STREAM: typ.Literal["stdout", "stderr"] = typ.cast(
    "typ.Literal['stdout', 'stderr']",
    os.environ.get("POLYTHENE_TEST_DIAGNOSTIC_STREAM", "stderr"),
)


def _invalid_isolation_arguments(store: Path) -> list[str]:
    """Return arguments that reject an invalid backend before launch."""
    return [
        "exec",
        "uuid-invalid-isolation",
        "--store",
        store.as_posix(),
        "--isolation",
        "unknown",
        "--",
        "true",
    ]


def _recording_backends() -> tuple[_DummyBackend, ...]:
    """Return one recording backend for each supported isolation choice."""
    return (
        _DummyBackend(0, name="bubblewrap"),
        _DummyBackend(0, name="proot"),
        _DummyBackend(0, name="chroot"),
    )


def test_invalid_isolation_is_rejected_before_any_backend_runs(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An invalid isolation choice fails before backend selection or launch."""
    rootfs = tmp_path / "uuid-invalid-isolation"
    rootfs.mkdir()
    backends = _recording_backends()
    monkeypatch.setattr(isolation, "BACKENDS", backends)
    monkeypatch.setattr(isolation, "IS_ROOT", True)

    result = run_cli(_invalid_isolation_arguments(tmp_path))

    assert_cli_diagnostic(
        result,
        "unknown",
        "--isolation",
        "bubblewrap",
        "proot",
        "chroot",
        stream=PARSER_DIAGNOSTIC_STREAM,
    )
    assert all(backend.calls == [] for backend in backends)
    assert_no_process_launch(result)
    assert "Unsupported isolation backend requested" not in result.stderr


def test_process_entry_points_reject_invalid_isolation(
    run_real_process_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    tmp_path: Path,
) -> None:
    """Both installed process entry points reject invalid isolation values."""
    (tmp_path / "uuid-invalid-isolation").mkdir()

    result = run_real_process_cli(_invalid_isolation_arguments(tmp_path))

    assert_cli_diagnostic(
        result,
        "unknown",
        "--isolation",
        "bubblewrap",
        "proot",
        "chroot",
        stream=PARSER_DIAGNOSTIC_STREAM,
    )
    assert_no_process_launch(result)


def test_unknown_command_is_reported_on_the_parser_stream(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
) -> None:
    """Unknown commands produce a parser diagnostic and no command result."""
    result = run_cli(["unregistered-command"])

    assert_cli_diagnostic(
        result,
        "unregistered-command",
        stream=PARSER_DIAGNOSTIC_STREAM,
    )


def test_missing_uuid_names_the_parameter_without_calling_a_backend(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A missing UUID is rejected before any isolation backend runs."""
    backends = _recording_backends()
    monkeypatch.setattr(isolation, "BACKENDS", backends)
    monkeypatch.setattr(isolation, "IS_ROOT", True)

    result = run_cli(["exec", "--store", tmp_path.as_posix()])

    assert_cli_diagnostic(
        result,
        "uuid",
        stream=PARSER_DIAGNOSTIC_STREAM,
    )
    assert all(backend.calls == [] for backend in backends)


def test_help_uses_stdout_and_has_no_diagnostic(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
) -> None:
    """Top-level and command help stay on stdout with a successful status."""
    main_help = run_cli(["--help"])
    exec_help = run_cli(["exec", "--help"])

    assert main_help.exit_code == 0
    assert exec_help.exit_code == 0
    assert "pull" in normalise_cli_output(main_help.stdout)
    assert "exec" in normalise_cli_output(main_help.stdout)
    assert "--isolation" in normalise_cli_output(exec_help.stdout)
    assert main_help.stderr == ""
    assert exec_help.stderr == ""


def test_stubbed_pull_prints_only_its_uuid(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A successful pull writes its generated UUID and no diagnostic."""
    monkeypatch.setattr(isolation, "generate_uuid", lambda: "uuid-contract-pull")

    def _fake_export(
        image: str,
        destination: Path,
        *,
        timeout: int | None = None,
    ) -> None:
        """Create the requested rootfs directory instead of exporting it."""
        destination.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(isolation, "export_rootfs", _fake_export)

    result = run_cli(["pull", "busybox", "--store", tmp_path.as_posix()])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["uuid-contract-pull"]
    assert result.stderr == ""


def test_stubbed_exec_returns_child_status_without_stdout(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A successful backend call preserves the child status and output."""
    rootfs = tmp_path / "uuid-contract-exec"
    rootfs.mkdir()
    backend = _DummyBackend(0)
    monkeypatch.setattr(isolation, "BACKENDS", (backend,))
    monkeypatch.setattr(isolation, "IS_ROOT", True)

    result = run_cli(
        [
            "exec",
            "uuid-contract-exec",
            "--store",
            tmp_path.as_posix(),
            "--",
            "true",
        ]
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert backend.calls == [(rootfs, "true", None)]


def test_real_process_preserves_missing_rootfs_exit_status(
    run_real_process_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    tmp_path: Path,
) -> None:
    """A missing rootfs exits one and reports the application error on stderr."""
    result = run_real_process_cli(
        [
            "exec",
            "uuid-missing-rootfs",
            "--store",
            tmp_path.as_posix(),
            "--",
            "true",
        ]
    )

    assert result.exit_code == 1
    assert "No such UUID rootfs" in result.stderr
    assert result.stdout == ""


def test_real_process_preserves_missing_command_exit_status(
    run_real_process_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    tmp_path: Path,
) -> None:
    """An exec without a child command exits two and reports the error."""
    (tmp_path / "uuid-no-command").mkdir()

    result = run_real_process_cli(
        ["exec", "uuid-no-command", "--store", tmp_path.as_posix()]
    )

    assert result.exit_code == 2
    assert "No command provided" in result.stderr
    assert result.stdout == ""
    assert_no_process_launch(result)
