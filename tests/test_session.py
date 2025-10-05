"""Unit tests for the :mod:`polythene.session` helpers."""

from __future__ import annotations

import typing as typ

import pytest

from polythene.session import PolytheneSession

if typ.TYPE_CHECKING:
    from pathlib import Path


class _RecordingSandbox:
    """Sandbox stub capturing invocations for assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int | None]] = []

    def run(
        self,
        argv: typ.Sequence[str],
        *,
        timeout: int | None = None,
    ) -> int:
        self.calls.append((list(argv), timeout))
        return 0


def test_session_exec_includes_store_and_command(tmp_path: Path) -> None:
    """Commands include the configured store and payload tokens."""
    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    session.exec("uuid-1", ["echo", "hello"], isolation="bubblewrap", timeout=5)

    assert sandbox.calls
    argv, timeout = sandbox.calls[-1]
    assert argv[:7] == [
        "uv",
        "run",
        "polythene",
        "exec",
        "uuid-1",
        "--store",
        tmp_path.as_posix(),
    ]
    assert "--isolation=bubblewrap" in argv
    assert argv[-2:] == ["echo", "hello"]
    assert timeout == 5


def test_session_defaults_to_proot_on_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub runners request ``proot`` to avoid noisy bwrap failures."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    session.exec("uuid-2", "echo hi")

    argv, _ = sandbox.calls[-1]
    assert "--isolation=proot" in argv


def test_session_respects_explicit_isolation_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``POLYTHENE_ISOLATION`` overrides automatic backend selection."""
    monkeypatch.setenv("POLYTHENE_ISOLATION", "chroot")

    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    session.exec("uuid-3", ["true"])

    argv, _ = sandbox.calls[-1]
    assert "--isolation=chroot" in argv


def test_session_exec_rejects_empty_command(tmp_path: Path) -> None:
    """An informative error is raised when no command tokens are provided."""
    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    with pytest.raises(ValueError, match="Command must contain at least one token"):
        session.exec("uuid-4", [])
