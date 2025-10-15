"""Tests for sandbox execution backends."""

from __future__ import annotations

import errno
import typing as typ

import pytest
from plumbum.commands.processes import ProcessExecutionError

from polythene import backends

if typ.TYPE_CHECKING:
    import pathlib

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


def test_prepare_proot_avoids_login_shell(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_prepare_proot`` should not request a login shell.

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
    result = backends._prepare_proot(
        typ.cast("BaseCommand", stub),
        tmp_path,
        inner_cmd,
        lambda _msg: None,
        timeout=None,
        _container_tmp=tmp_path,
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

    outcome = backend.run(
        tmp_path,
        "echo hi",
        timeout=None,
        logger=lambda _msg: None,
        container_tmp=tmp_path,
    )

    assert outcome == (backend.name, 0)
    assert len(stub.calls) == 2
    probe_call, exec_call = stub.calls
    assert probe_call[-2:] == ("-c", "true")
    assert exec_call[-2] == "-c"
    assert exec_call[-1] == "echo hi"
    assert executed == stub.calls


def test_probe_bwrap_userns_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permission denied during probing should disable bubblewrap early."""

    def fake_run_cmd(_cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        raise ProcessExecutionError(_cmd, 1, "", "Permission denied")

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("BaseCommand", _StubCommand()),
            timeout=None,
            logger=lambda _msg: None,
        )


def test_probe_bwrap_userns_oserror_eperm(monkeypatch: pytest.MonkeyPatch) -> None:
    """OS errors reporting ``EPERM`` disable bubblewrap immediately."""

    def fake_run_cmd(_cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("BaseCommand", _StubCommand()),
            timeout=None,
            logger=lambda _msg: None,
        )


def test_probe_bwrap_userns_respects_sysctl(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The userns sysctl check short-circuits bubblewrap probing."""
    flag = tmp_path / "unprivileged_userns_clone"
    flag.write_text("0", encoding="utf-8")
    monkeypatch.setattr(backends, "_UNPRIVILEGED_USERNS_PATH", flag)

    def fail_run_cmd(*_args: object, **_kwargs: object) -> int:
        pytest.fail("bubblewrap should not be probed when sysctl=0")
        raise AssertionError("unreachable")

    monkeypatch.setattr(backends, "run_cmd", fail_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="requires unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("BaseCommand", _StubCommand()),
            timeout=None,
            logger=lambda _msg: None,
        )


def test_backend_run_logs_bubblewrap_unavailability(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Backend.run`` logs and skips when bubblewrap becomes unavailable."""
    messages: list[str] = []

    def fake_prepare(
        *_args: object, **_kwargs: object
    ) -> list[str] | None:  # pragma: no cover - replaced in test
        message = "bubblewrap unavailable"
        raise backends.BubblewrapUnavailable(message)

    backend = backends.Backend(
        name="bubblewrap",
        binary="bwrap",
        prepare=fake_prepare,  # type: ignore[arg-type]
    )

    def fake_get_command(binary: str) -> _StubCommand:
        assert binary == "bwrap"
        return _StubCommand()

    monkeypatch.setattr(backends, "get_command", fake_get_command)

    outcome = backend.run(
        tmp_path,
        "echo hi",
        timeout=None,
        logger=messages.append,
        container_tmp=tmp_path,
    )

    assert outcome is None
    assert messages == ["bubblewrap unavailable"]
