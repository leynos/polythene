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


def test_session_run_includes_store_and_command(tmp_path: Path) -> None:
    """Commands include the configured store and payload tokens."""
    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    session.run("uuid-1", ["echo", "hello"], isolation="bubblewrap", timeout=5)

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
    isolation_idx = argv.index("--isolation")
    assert argv[isolation_idx + 1] == "bubblewrap"
    assert argv[-2:] == ["echo", "hello"]
    assert timeout == 5


def test_build_exec_argv_emits_split_isolation_flag(tmp_path: Path) -> None:
    """Isolation arguments are emitted as separate tokens."""
    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    argv = session._build_exec_argv("uuid-iso", ["true"], "proot")

    isolation_idx = argv.index("--isolation")
    assert argv[isolation_idx + 1] == "proot"
    assert all(not token.startswith("--isolation=") for token in argv)


def test_session_defaults_to_proot_on_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub runners request ``proot`` to avoid noisy bwrap failures."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    session.run("uuid-2", "echo hi")

    argv, _ = sandbox.calls[-1]
    isolation_idx = argv.index("--isolation")
    assert argv[isolation_idx + 1] == "proot"
    assert "--isolation=proot" not in argv


def test_session_respects_explicit_isolation_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``POLYTHENE_ISOLATION`` overrides automatic backend selection."""
    monkeypatch.setenv("POLYTHENE_ISOLATION", "chroot")

    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    session.run("uuid-3", ["true"])

    argv, _ = sandbox.calls[-1]
    isolation_idx = argv.index("--isolation")
    assert argv[isolation_idx + 1] == "chroot"


def test_session_run_rejects_empty_command(tmp_path: Path) -> None:
    """An informative error is raised when no command tokens are provided."""
    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    with pytest.raises(ValueError, match="Command must contain at least one token"):
        session.run("uuid-4", [])


def test_session_run_rejects_whitespace_command(tmp_path: Path) -> None:
    """Whitespace strings raise the same informative error as empty lists."""
    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    with pytest.raises(ValueError, match="Command must contain at least one token"):
        session.run("uuid-5", "   \t  ")


def test_session_invalid_isolation_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid ``POLYTHENE_ISOLATION`` values are rejected early."""
    monkeypatch.setenv("POLYTHENE_ISOLATION", "invalid_isolation")

    sandbox = _RecordingSandbox()
    session = PolytheneSession(sandbox, store=tmp_path)

    with pytest.raises(ValueError, match="Supported values"):
        session.run("uuid-6", ["true"])
