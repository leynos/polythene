"""Tests for sandbox execution backends."""

from __future__ import annotations

import errno
import pathlib
import typing as typ

import pytest
from plumbum.commands.processes import ProcessExecutionError

from polythene import backends

if typ.TYPE_CHECKING:
    from plumbum.commands.base import BaseCommand
else:  # pragma: no cover - runtime sentinel for typing-only import
    BaseCommand = typ.Any  # type: ignore[assignment]


class _StubCommand:
    """Record invocations made by ``plumbum`` style command objects."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __getitem__(self, args: tuple[str, ...]) -> tuple[str, ...]:
        self.calls.append(args)
        return args


def _make_context(
    *,
    container_tmp: pathlib.Path,
    logger: typ.Callable[[str], None] = lambda _msg: None,
    timeout: int | None = None,
) -> backends.BackendContext:
    """Return a backend context tailored for the current test."""
    container_tmp = pathlib.Path(container_tmp)
    return backends.BackendContext(
        logger=logger,
        timeout=timeout,
        container_tmp=container_tmp,
    )


def test_prepare_proot_avoids_login_shell(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``make_prepare_proot`` should not request a login shell.

    Login shells source profile scripts, which can mutate environment state in
    unexpected ways.  The probe command already uses ``-c`` so the execution
    command should mirror it to ensure a consistent environment.
    """
    stub = _StubCommand()
    run_calls: list[tuple[str, ...]] = []

    def fake_run_cmd(cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        run_calls.append(cmd)
        return 0

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    inner_cmd = "test -x /usr/bin/rust-toy-app"
    context = _make_context(container_tmp=tmp_path, logger=lambda _msg: None)

    prepare = backends.make_prepare_proot(context)
    result = prepare(
        typ.cast("BaseCommand", stub),
        tmp_path,
        inner_cmd,
    )

    assert stub.calls[0] == (
        "-R",
        str(tmp_path),
        "-0",
        "/bin/sh",
        "-c",
        "true",
    )
    assert run_calls == [
        (
            "-R",
            str(tmp_path),
            "-0",
            "/bin/sh",
            "-c",
            "true",
        )
    ]
    assert result == [
        "-R",
        str(tmp_path),
        "-0",
        "/bin/sh",
        "-c",
        inner_cmd,
    ]


def test_make_prepare_bwrap_binds_context(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``make_prepare_bwrap`` captures timeout and tmp paths from context."""
    base_flags = ["--unshare-user"]
    proc_flags = ["--proc", "/proc"]
    context = _make_context(
        container_tmp=tmp_path / "container-tmp",
        timeout=37,
        logger=lambda _msg: None,
    )
    probe_calls: list[tuple[tuple[str, ...], int | None]] = []

    monkeypatch.setattr(
        backends, "_probe_bwrap_userns", lambda *_args: base_flags.copy()
    )
    monkeypatch.setattr(
        backends,
        "_probe_bwrap_proc",
        lambda *_args, **_kwargs: proc_flags.copy(),
    )

    def fake_run_cmd(
        cmd: tuple[str, ...], *, fg: bool, timeout: int | None
    ) -> int:  # pragma: no cover - instrumented below
        assert fg is True
        probe_calls.append((cmd, timeout))
        return 0

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    prepare = backends.make_prepare_bwrap(context)
    stub = _StubCommand()

    result = prepare(typ.cast("BaseCommand", stub), tmp_path, "echo hi")

    assert len(stub.calls) == 1
    probe_cmd, timeout = probe_calls[0]
    assert timeout == 37
    assert "--tmpfs" in probe_cmd
    idx = probe_cmd.index("--tmpfs")
    assert probe_cmd[idx + 1] == str(context.container_tmp)
    assert result[-2:] == ["-c", "echo hi"]


def test_proot_backend_run_uses_non_login_shell(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Backend.run`` should propagate the non-login shell into execution."""
    backend = next(b for b in backends.create_backends() if b.name == "proot")
    stub = _StubCommand()
    executed: list[tuple[str, ...]] = []

    def fake_get_command(binary: str) -> _StubCommand:
        assert binary == backend.binary
        return stub

    def fake_run_cmd(cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        executed.append(cmd)
        return 0

    monkeypatch.setattr(backends, "get_command", fake_get_command)
    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    context = _make_context(container_tmp=tmp_path, logger=lambda _msg: None)

    outcome = backend.run(
        tmp_path,
        "echo hi",
        context=context,
    )

    assert outcome == (backend.name, 0)
    assert len(stub.calls) == 2
    probe_call, exec_call = stub.calls
    assert probe_call[-2:] == ("-c", "true")
    assert exec_call[-2] == "-c"
    assert exec_call[-1] == "echo hi"
    assert executed == stub.calls


def test_probe_bwrap_userns_uses_context_timeout(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_probe_bwrap_userns`` passes the context timeout to ``run_cmd``."""
    stub = _StubCommand()
    timeouts: list[int | None] = []

    def fake_run_cmd(cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        assert cmd[-1] == "true"
        timeouts.append(timeout)
        return 0

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: True)

    context = _make_context(
        container_tmp=tmp_path, logger=lambda _msg: None, timeout=99
    )

    result = backends._probe_bwrap_userns(
        typ.cast("BaseCommand", stub),
        context,
    )

    assert result == ["--unshare-user", "--uid", "0", "--gid", "0"]
    assert timeouts == [99]


def test_probe_bwrap_userns_permission_denied(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Permission denied during probing should disable bubblewrap early."""

    def fake_run_cmd(_cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        raise ProcessExecutionError(_cmd, 1, "", "Permission denied")

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("BaseCommand", _StubCommand()),
            _make_context(container_tmp=tmp_path, logger=lambda _msg: None),
        )


def test_probe_bwrap_userns_oserror_eperm(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OS errors reporting ``EPERM`` disable bubblewrap immediately."""

    def fake_run_cmd(_cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("BaseCommand", _StubCommand()),
            _make_context(container_tmp=tmp_path, logger=lambda _msg: None),
        )


def test_probe_bwrap_userns_respects_sysctl(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The userns sysctl check short-circuits bubblewrap probing."""
    flag = tmp_path / "unprivileged_userns_clone"
    flag.write_text("0", encoding="utf-8")
    monkeypatch.setattr(backends, "_UNPRIVILEGED_USERNS_PATH", flag)
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: False)

    def fail_run_cmd(*_args: object, **_kwargs: object) -> typ.NoReturn:
        pytest.fail("bubblewrap should not be probed when sysctl=0")
        raise AssertionError("unreachable")  # appease Pyright's flow analysis

    monkeypatch.setattr(backends, "run_cmd", fail_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="requires unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("BaseCommand", _StubCommand()),
            _make_context(container_tmp=tmp_path, logger=lambda _msg: None),
        )


def test_probe_bwrap_userns_sysctl_missing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing sysctl files should not prevent probing."""
    missing_path = tmp_path / "nonexistent"
    monkeypatch.setattr(backends, "_UNPRIVILEGED_USERNS_PATH", missing_path)
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: False)

    stub = _StubCommand()
    executed: list[tuple[str, ...]] = []

    def fake_run_cmd(cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        executed.append(cmd)
        return 0

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    result = backends._probe_bwrap_userns(
        typ.cast("BaseCommand", stub),
        _make_context(container_tmp=tmp_path, logger=lambda _msg: None),
    )

    assert result == ["--unshare-user", "--uid", "0", "--gid", "0"]
    assert executed == stub.calls


def test_probe_bwrap_userns_sysctl_read_error(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected sysctl read errors should be logged but probing continues."""
    bad_path = tmp_path / "userns_dir"
    bad_path.mkdir()
    monkeypatch.setattr(backends, "_UNPRIVILEGED_USERNS_PATH", bad_path)
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: False)

    stub = _StubCommand()
    executed: list[tuple[str, ...]] = []
    logs: list[str] = []

    def fake_run_cmd(cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        executed.append(cmd)
        return 0

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    result = backends._probe_bwrap_userns(
        typ.cast("BaseCommand", stub),
        _make_context(container_tmp=tmp_path, logger=logs.append),
    )

    assert result == ["--unshare-user", "--uid", "0", "--gid", "0"]
    assert executed == stub.calls
    assert logs == [
        (
            "Unable to read /proc/sys/kernel/unprivileged_userns_clone: "
            f"[Errno 21] Is a directory: '{bad_path}'"
        )
    ]


def test_probe_bwrap_userns_skips_sysctl_for_privileged(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root users ignore the sysctl and still probe bubblewrap."""
    flag = tmp_path / "unprivileged_userns_clone"
    flag.write_text("0", encoding="utf-8")
    monkeypatch.setattr(backends, "_UNPRIVILEGED_USERNS_PATH", flag)
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: True)

    stub = _StubCommand()
    executed: list[tuple[str, ...]] = []

    def fake_run_cmd(cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        executed.append(cmd)
        return 0

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    result = backends._probe_bwrap_userns(
        typ.cast("BaseCommand", stub),
        _make_context(container_tmp=tmp_path, logger=lambda _msg: None),
    )

    assert result == ["--unshare-user", "--uid", "0", "--gid", "0"]
    assert stub.calls == executed  # probe executed despite sysctl=0


def test_backend_run_logs_bubblewrap_unavailability(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Backend.run`` logs and skips when bubblewrap becomes unavailable."""
    messages: list[str] = []

    def fake_prepare(
        _tool: object,
        _root: object,
        _inner_cmd: object,
    ) -> list[str] | None:  # pragma: no cover - replaced in test
        message = "bubblewrap unavailable"
        raise backends.BubblewrapUnavailable(message)

    backend = backends.Backend(
        name="bubblewrap",
        binary="bwrap",
        prepare_factory=lambda _context: fake_prepare,
    )

    def fake_get_command(binary: str) -> _StubCommand:
        assert binary == "bwrap"
        return _StubCommand()

    monkeypatch.setattr(backends, "get_command", fake_get_command)

    context = _make_context(container_tmp=tmp_path, logger=messages.append)

    outcome = backend.run(
        tmp_path,
        "echo hi",
        context=context,
    )

    assert outcome is None
    assert messages == ["bubblewrap unavailable"]
