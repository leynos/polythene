"""Tests for sandbox execution backends."""

from __future__ import annotations

import pathlib
import typing as typ

import pytest

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


def test_prepare_proot_avoids_login_shell(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_prepare_proot`` should not request a login shell.

    Login shells source profile scripts, which can mutate environment state in
    unexpected ways.  The probe command already uses ``-c`` so the execution
    command should mirror it to ensure a consistent environment.
    """
    assert isinstance(tmp_path, pathlib.Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    stub = _StubCommand()

    def fake_run_cmd(cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
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
    assert result == [
        "-R",
        str(tmp_path),
        "-0",
        "/bin/sh",
        "-c",
        inner_cmd,
    ]
