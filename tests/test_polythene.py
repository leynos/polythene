"""Tests for the standalone polythene CLI package."""

from __future__ import annotations

import importlib
import typing as typ

import pytest

import polythene
import polythene.isolation as isolation

if typ.TYPE_CHECKING:
    from pathlib import Path

    from conftest import CliResult


def test_cmd_pull_exports_rootfs(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The ``pull`` command exports the rootfs and prints the generated UUID."""
    calls: list[tuple[str, Path, int | None]] = []
    monkeypatch.setattr(isolation, "generate_uuid", lambda: "uuid-1234")

    def _fake_export(image: str, dest: Path, *, timeout: int | None = None) -> None:
        calls.append((image, dest, timeout))
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(isolation, "export_rootfs", _fake_export)

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
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The ``pull`` command regenerates a UUID after a collision."""
    uuids = iter(["uuid-1", "uuid-2"])
    monkeypatch.setattr(isolation, "generate_uuid", lambda: next(uuids))

    call_count = 0

    def _fake_export(image: str, dest: Path, *, timeout: int | None = None) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FileExistsError(dest)
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(isolation, "export_rootfs", _fake_export)

    result = run_cli(["pull", "busybox", "--store", tmp_path.as_posix()])

    assert result.exit_code == 0
    assert result.stdout.strip() == "uuid-2"
    assert call_count == 2


class _DummyBackend:
    def __init__(
        self,
        return_code: int | None,
        *,
        requires_root: bool = False,
        name: str = "dummy",
    ) -> None:
        self.return_code = return_code
        self.requires_root = requires_root
        self.name = name
        self.calls: list[tuple[Path, str, int | None]] = []

    def run(
        self,
        root: Path,
        inner_cmd: str,
        *,
        timeout: int | None,
        logger: typ.Callable[[str], None],
        container_tmp: Path,
    ) -> int | None:
        self.calls.append((root, inner_cmd, timeout))
        return self.return_code


def test_normalise_command_args_flattens_single_sequence() -> None:
    """Internal helpers flatten nested command sequences."""
    tokens = isolation._normalise_command_args((["echo", "hello"],))

    assert tokens == ["echo", "hello"]


def test_normalise_command_args_rejects_non_strings() -> None:
    """Non-string command tokens raise a descriptive ``TypeError``."""
    with pytest.raises(TypeError, match="Command tokens must be strings"):
        isolation._normalise_command_args(((42,),))


def test_cmd_exec_accepts_list_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Programmatic callers may keep passing list command tokens."""
    root = tmp_path / "uuid-list"
    root.mkdir(parents=True)

    backend = _DummyBackend(0)
    monkeypatch.setattr(isolation, "BACKENDS", (backend,))
    monkeypatch.setattr(isolation, "IS_ROOT", True)

    isolation.cmd_exec("uuid-list", ["echo", "hello world"], store=tmp_path)

    assert backend.calls == [(root, "echo 'hello world'", None)]


def test_cmd_exec_accepts_varargs_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Vararg command tokens remain supported alongside list calls."""
    root = tmp_path / "uuid-varargs"
    root.mkdir(parents=True)

    backend = _DummyBackend(0)
    monkeypatch.setattr(isolation, "BACKENDS", (backend,))
    monkeypatch.setattr(isolation, "IS_ROOT", True)

    isolation.cmd_exec("uuid-varargs", "echo", "hello", store=tmp_path)

    assert backend.calls == [(root, "echo hello", None)]


def test_cmd_exec_uses_first_available_backend(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The ``exec`` command runs using the first available backend."""
    root = tmp_path / "uuid-5678"
    root.mkdir(parents=True)

    primary = _DummyBackend(0)
    fallback = _DummyBackend(None)
    monkeypatch.setattr(isolation, "BACKENDS", (primary, fallback))
    monkeypatch.setattr(isolation, "IS_ROOT", False)

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


def test_cmd_exec_allows_leading_hyphen_arguments(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Command tokens beginning with ``-`` are passed through verbatim."""
    root = tmp_path / "uuid-hyphen"
    root.mkdir(parents=True)

    backend = _DummyBackend(0)
    monkeypatch.setattr(isolation, "BACKENDS", (backend,))
    monkeypatch.setattr(isolation, "IS_ROOT", True)

    result = run_cli(
        [
            "exec",
            "uuid-hyphen",
            "--store",
            tmp_path.as_posix(),
            "--",
            "-l",
            "--colour",
        ]
    )

    assert result.exit_code == 0
    assert backend.calls == [(root, "-l --colour", None)]


def test_cmd_exec_reports_missing_root(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
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
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-zero backend exit code terminates the CLI with that status."""
    root = tmp_path / "uuid-9999"
    root.mkdir()

    unavailable = _DummyBackend(None)
    failing = _DummyBackend(42)
    monkeypatch.setattr(isolation, "BACKENDS", (unavailable, failing))
    monkeypatch.setattr(isolation, "IS_ROOT", True)

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
    assert unavailable.calls
    assert failing.calls


def test_cmd_exec_requires_command(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
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

    assert result.exit_code == 2
    assert "No command provided" in result.stderr


def test_cmd_exec_prefers_requested_isolation(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--isolation`` reorders backend probing to honour the preference."""
    root = tmp_path / "uuid-preferred"
    root.mkdir()

    bubblewrap = _DummyBackend(0, name="bubblewrap")
    proot = _DummyBackend(0, name="proot")
    chroot = _DummyBackend(0, name="chroot")

    monkeypatch.setattr(isolation, "BACKENDS", (bubblewrap, proot, chroot))
    monkeypatch.setattr(isolation, "IS_ROOT", True)

    result = run_cli(
        [
            "exec",
            "uuid-preferred",
            "--store",
            tmp_path.as_posix(),
            "--isolation=proot",
            "--",
            "true",
        ]
    )

    assert result.exit_code == 0
    assert proot.calls == [(root, "true", None)]
    assert bubblewrap.calls == []


def test_cmd_exec_falls_back_when_preferred_unavailable(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``exec`` falls back to other backends if the preferred one declines."""
    root = tmp_path / "uuid-fallback"
    root.mkdir()

    bubblewrap = _DummyBackend(0, name="bubblewrap")
    proot = _DummyBackend(None, name="proot")
    chroot = _DummyBackend(0, name="chroot")

    monkeypatch.setattr(isolation, "BACKENDS", (bubblewrap, proot, chroot))
    monkeypatch.setattr(isolation, "IS_ROOT", True)

    result = run_cli(
        [
            "exec",
            "uuid-fallback",
            "--store",
            tmp_path.as_posix(),
            "--isolation",
            "proot",
            "--",
            "true",
        ]
    )

    assert result.exit_code == 0
    assert proot.calls == [(root, "true", None)]
    assert bubblewrap.calls == [(root, "true", None)]


def test_cmd_exec_reads_isolation_from_environment(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The CLI honours ``POLYTHENE_ISOLATION`` when no flag is provided."""
    root = tmp_path / "uuid-env"
    root.mkdir()

    bubblewrap = _DummyBackend(0, name="bubblewrap")
    proot = _DummyBackend(0, name="proot")
    monkeypatch.setattr(isolation, "BACKENDS", (bubblewrap, proot))
    monkeypatch.setattr(isolation, "IS_ROOT", True)
    monkeypatch.setenv("POLYTHENE_ISOLATION", "proot")

    result = run_cli(
        [
            "exec",
            "uuid-env",
            "--store",
            tmp_path.as_posix(),
            "--",
            "true",
        ]
    )

    assert result.exit_code == 0
    assert proot.calls == [(root, "true", None)]
    assert bubblewrap.calls == []


def test_cmd_exec_rejects_unknown_isolation(
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    tmp_path: Path,
) -> None:
    """An unknown isolation backend is reported as a CLI error."""
    rootfs = tmp_path / "uuid-unknown"
    rootfs.mkdir()

    result = run_cli(
        [
            "exec",
            "uuid-unknown",
            "--store",
            tmp_path.as_posix(),
            "--isolation",
            "unknown",  # not one of the registered backends
            "--",
            "true",
        ]
    )

    assert result.exit_code == 1
    assert 'Invalid value for "--isolation"' in result.stdout


def test_module_exec_accepts_isolation_option(
    run_module_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    tmp_path: Path,
) -> None:
    """``python -m polythene`` honours isolation options between arguments."""
    result = run_module_cli(
        [
            "exec",
            "missing",  # UUID that does not exist
            "--store",
            tmp_path.as_posix(),
            "--isolation",
            "proot",
            "--",
            "true",
        ]
    )

    assert result.exit_code == 1
    assert "No such UUID rootfs" in result.stderr


def test_module_exec_accepts_isolation_equals_option(
    run_module_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    tmp_path: Path,
) -> None:
    """``python -m polythene`` honours isolation options with equals form."""
    result = run_module_cli(
        [
            "exec",
            "missing",  # UUID that does not exist
            "--store",
            tmp_path.as_posix(),
            "--isolation=proot",
            "--",
            "true",
        ]
    )

    assert result.exit_code == 1
    assert "No such UUID rootfs" in result.stderr


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

    def _capture(tokens: typ.Sequence[str]) -> None:
        received[:] = list(tokens)

    monkeypatch.setattr(isolation, "app", _capture)
    monkeypatch.setattr(polythene, "app", _capture)

    polythene.main(["pull", "busybox"])

    assert received == ["pull", "busybox"]
