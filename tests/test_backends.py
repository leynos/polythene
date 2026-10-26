"""Tests for sandbox execution backends."""

from __future__ import annotations

import errno
import pathlib
import typing as typ

import pytest
from cuprum import (
    ArgValue,
    CommandResult,
    Program,
    ProgramCatalogue,
    ProjectSettings,
    SafeCmd,
    SafeCmdBuilder,
    sh,
)

from polythene import backends
from tests.support.podman import result

BACKEND_CATALOGUE = ProgramCatalogue(
    projects=(
        ProjectSettings(
            name="polythene-tests",
            programs=(Program("bwrap"), Program("proot"), Program("chroot")),
        ),
    )
)


def _outcome(
    cmd: SafeCmd,
    status: int,
    stdout: str = "",
    stderr: str = "",
) -> CommandResult:
    """Build the result cuprum would report for ``cmd`` at ``status``."""
    return typ.cast("CommandResult", result(cmd, status, stdout, stderr))


class _StubTool:
    """A stand-in for the builder ``get_command`` returns.

    Cuprum's builder is a callable returning a :class:`cuprum.SafeCmd`, so the
    stub records the arguments it was called with and hands back a real
    command built from a throwaway catalogue. Recording the arguments rather
    than the assembled command keeps the assertion about what the backend
    asked for, which is the part under test.

    ``__call__`` takes cuprum's full ``ArgValue`` range so the stub satisfies
    the ``SafeCmdBuilder`` protocol it stands in for; the values are recorded
    unrendered, because a backend that passed a path object where the tests
    expect text should fail the comparison rather than be silently coerced.
    Keyword values are refused rather than recorded: no backend builds a flag
    that way, so one appearing is a change the assertions should surface
    instead of a call this stub pretends to represent.
    """

    def __init__(self, binary: str) -> None:
        self.binary = binary
        self.calls: list[tuple[ArgValue, ...]] = []

    def __call__(self, *args: ArgValue, **kwargs: ArgValue) -> SafeCmd:
        if kwargs:
            msg = f"backend passed flags as keywords: {sorted(kwargs)}"
            raise AssertionError(msg)
        self.calls.append(args)
        return _builder(self.binary)(*args)


def _builder(binary: str) -> SafeCmdBuilder:
    """Return a cuprum builder for ``binary`` from :data:`BACKEND_CATALOGUE`."""
    return sh.make(Program(binary), catalogue=BACKEND_CATALOGUE)


def _make_context(
    *,
    container_tmp: pathlib.Path,
    logger: typ.Callable[[str], None] = lambda _msg: None,
    timeout: int | None = None,
) -> backends.BackendContext:
    """Return a backend context tailored for the current test."""
    return backends.BackendContext(
        logger=logger,
        timeout=timeout,
        container_tmp=pathlib.Path(container_tmp),
    )


def test_prepare_proot_avoids_login_shell(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``make_prepare_proot`` should not request a login shell.

    Login shells source profile scripts, which can mutate environment state in
    unexpected ways. The probe command already uses ``-c``, so the execution
    command should mirror it to ensure a consistent environment.
    """
    stub = _StubTool("proot")
    run_calls: list[tuple[str, ...]] = []

    def fake_run_cmd(
        cmd: SafeCmd,
        *,
        fg: bool,
        timeout: int | None,
        **_: object,
    ) -> object:
        run_calls.append(cmd.argv)
        return _outcome(cmd, 0)

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    inner_cmd = "test -x /usr/bin/rust-toy-app"
    context = _make_context(container_tmp=tmp_path)
    prepare = backends.make_prepare_proot(context)

    result = prepare(typ.cast("SafeCmdBuilder", stub), tmp_path, inner_cmd)

    assert stub.calls[0] == ("-R", str(tmp_path), "-0", "/bin/sh", "-c", "true")
    assert run_calls == [("-R", str(tmp_path), "-0", "/bin/sh", "-c", "true")]
    assert result == ["-R", str(tmp_path), "-0", "/bin/sh", "-c", inner_cmd]


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
        backends, "_probe_bwrap_proc", lambda *_args, **_kwargs: proc_flags.copy()
    )

    def fake_run_cmd(
        cmd: SafeCmd,
        *,
        fg: bool,
        timeout: int | None,
        **_: object,
    ) -> object:
        assert fg is True
        probe_calls.append((cmd.argv, timeout))
        return _outcome(cmd, 0)

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    prepare = backends.make_prepare_bwrap(context)
    stub = _StubTool("bwrap")

    result = prepare(typ.cast("SafeCmdBuilder", stub), tmp_path, "echo hi")

    assert len(stub.calls) == 1
    probe_cmd, timeout = probe_calls[0]
    assert timeout == 37
    assert "--tmpfs" in probe_cmd
    index = probe_cmd.index("--tmpfs")
    assert probe_cmd[index + 1] == str(context.container_tmp)
    assert result is not None
    assert result[-2:] == ["-c", "echo hi"]


def test_make_prepare_bwrap_gives_up_when_the_probe_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed probe means bubblewrap cannot run, not that it might work."""
    context = _make_context(container_tmp=tmp_path)
    monkeypatch.setattr(backends, "_probe_bwrap_userns", lambda *_args: [])
    monkeypatch.setattr(backends, "_probe_bwrap_proc", lambda *_a, **_k: [])

    def fake_run_cmd(cmd: SafeCmd, **_: object) -> object:
        return _outcome(cmd, 1, "", "bwrap: setting up uid map: Permission denied")

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    prepare = backends.make_prepare_bwrap(context)

    assert prepare(_StubTool("bwrap"), tmp_path, "echo hi") is None


def test_proot_backend_run_uses_non_login_shell(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Backend.run`` should propagate the non-login shell into execution."""
    backend = next(b for b in backends.create_backends() if b.name == "proot")
    stub = _StubTool("proot")
    executed: list[tuple[str, ...]] = []

    def fake_get_command(binary: str) -> SafeCmdBuilder:
        assert binary == backend.binary
        return typ.cast("SafeCmdBuilder", stub)

    def fake_run_cmd(cmd: SafeCmd, **_: object) -> object:
        executed.append(cmd.argv)
        return _outcome(cmd, 0)

    monkeypatch.setattr(backends, "get_command", fake_get_command)
    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    context = _make_context(container_tmp=tmp_path)

    outcome = backend.run(tmp_path, "echo hi", context=context)

    assert outcome == (backend.name, 0)
    assert len(stub.calls) == 2
    probe_call, exec_call = stub.calls
    assert probe_call[-2:] == ("-c", "true")
    assert exec_call[-2] == "-c"
    assert exec_call[-1] == "echo hi"
    assert executed == stub.calls


def test_backend_run_reports_the_child_status(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero exec status becomes the backend's reported status."""
    backend = next(b for b in backends.create_backends() if b.name == "proot")

    monkeypatch.setattr(
        backends,
        "get_command",
        lambda _b: typ.cast("SafeCmdBuilder", _StubTool("proot")),
    )

    def fake_run_cmd(cmd: SafeCmd, **_: object) -> object:
        status = 0 if cmd.argv[:1] == ("-R",) and "true" in cmd.argv else 7
        return _outcome(cmd, status)

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    assert backend.run(
        tmp_path, "false", context=_make_context(container_tmp=tmp_path)
    ) == (
        "proot",
        7,
    )


def test_probe_bwrap_userns_uses_context_timeout(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_probe_bwrap_userns`` passes the context timeout to ``run_cmd``."""
    timeouts: list[int | None] = []

    def fake_run_cmd(cmd: SafeCmd, *, timeout: int | None, **_: object) -> object:
        assert cmd.argv[-1] == "true"
        timeouts.append(timeout)
        return _outcome(cmd, 0)

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: True)

    context = _make_context(container_tmp=tmp_path, timeout=99)

    result_flags = backends._probe_bwrap_userns(
        typ.cast("SafeCmdBuilder", _StubTool("bwrap")), context
    )

    assert result_flags == ["--unshare-user", "--uid", "0", "--gid", "0"]
    assert timeouts == [99]


def test_probe_bwrap_userns_permission_denied(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Permission denied on stderr should disable bubblewrap early."""

    def fake_run_cmd(cmd: SafeCmd, **_: object) -> object:
        return _outcome(cmd, 1, "", "bwrap: Permission denied")

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("SafeCmdBuilder", _StubTool("bwrap")),
            _make_context(container_tmp=tmp_path),
        )


def test_probe_bwrap_userns_oserror_eperm(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OS errors reporting ``EPERM`` disable bubblewrap immediately."""

    def fake_run_cmd(_cmd: SafeCmd, **_: object) -> object:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("SafeCmdBuilder", _StubTool("bwrap")),
            _make_context(container_tmp=tmp_path),
        )


def test_probe_bwrap_userns_missing_binary_is_not_fatal(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A binary cuprum cannot resolve is reported, not raised at the caller."""

    def fake_run_cmd(_cmd: SafeCmd, **_: object) -> object:
        raise FileNotFoundError(2, "No such file or directory", "bwrap")

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)
    logs: list[str] = []

    result_flags = backends._probe_bwrap_userns(
        typ.cast("SafeCmdBuilder", _StubTool("bwrap")),
        _make_context(container_tmp=tmp_path, logger=logs.append),
    )

    assert result_flags == []
    assert any("No such file or directory" in line for line in logs)


def test_probe_bwrap_userns_respects_sysctl(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The userns sysctl check short-circuits bubblewrap probing."""
    flag = tmp_path / "unprivileged_userns_clone"
    flag.write_text("0", encoding="utf-8")
    monkeypatch.setattr(backends, "_UNPRIVILEGED_USERNS_PATH", flag)
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: False)

    def fail_run_cmd(*_args: object, **_kwargs: object) -> typ.NoReturn:
        # ty misreads pytest.fail's decorated signature; the call is correct.
        pytest.fail(
            "bubblewrap should not be probed when sysctl=0"  # ty: ignore[invalid-argument-type]
        )
        raise AssertionError("unreachable")  # appease Pyright's flow analysis

    monkeypatch.setattr(backends, "run_cmd", fail_run_cmd)

    with pytest.raises(backends.BubblewrapUnavailable, match="requires unprivileged"):
        backends._probe_bwrap_userns(
            typ.cast("SafeCmdBuilder", _StubTool("bwrap")),
            _make_context(container_tmp=tmp_path),
        )


def test_probe_bwrap_userns_sysctl_missing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing sysctl files should not prevent probing."""
    monkeypatch.setattr(backends, "_UNPRIVILEGED_USERNS_PATH", tmp_path / "nonexistent")
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: False)

    stub = _StubTool("bwrap")
    executed: list[tuple[str, ...]] = []

    def fake_run_cmd(cmd: SafeCmd, **_: object) -> object:
        executed.append(cmd.argv)
        return _outcome(cmd, 0)

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    result_flags = backends._probe_bwrap_userns(
        typ.cast("SafeCmdBuilder", stub), _make_context(container_tmp=tmp_path)
    )

    assert result_flags == ["--unshare-user", "--uid", "0", "--gid", "0"]
    assert executed == stub.calls


def test_probe_bwrap_userns_sysctl_read_error(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected sysctl read errors should be logged but probing continues."""
    bad_path = tmp_path / "userns_dir"
    bad_path.mkdir()
    monkeypatch.setattr(backends, "_UNPRIVILEGED_USERNS_PATH", bad_path)
    monkeypatch.setattr(backends, "_is_privileged_user", lambda: False)

    stub = _StubTool("bwrap")
    logs: list[str] = []

    def fake_run_cmd(cmd: SafeCmd, **_: object) -> object:
        return _outcome(cmd, 0)

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    result_flags = backends._probe_bwrap_userns(
        typ.cast("SafeCmdBuilder", stub),
        _make_context(container_tmp=tmp_path, logger=logs.append),
    )

    assert result_flags == ["--unshare-user", "--uid", "0", "--gid", "0"]
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

    stub = _StubTool("bwrap")

    def fake_run_cmd(cmd: SafeCmd, **_: object) -> object:
        return _outcome(cmd, 0)

    monkeypatch.setattr(backends, "run_cmd", fake_run_cmd)

    result_flags = backends._probe_bwrap_userns(
        typ.cast("SafeCmdBuilder", stub), _make_context(container_tmp=tmp_path)
    )

    assert result_flags == ["--unshare-user", "--uid", "0", "--gid", "0"]
    assert len(stub.calls) == 1, "probe executed despite sysctl=0"


def test_backend_run_logs_bubblewrap_unavailability(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Backend.run`` logs and skips when bubblewrap becomes unavailable."""
    messages: list[str] = []

    def fake_prepare(
        _tool: SafeCmdBuilder,
        _root: object,
        _inner_cmd: object,
    ) -> list[str] | None:
        message = "bubblewrap unavailable"
        raise backends.BubblewrapUnavailable(message)

    backend = backends.Backend(
        name="bubblewrap",
        binary="bwrap",
        prepare_factory=lambda _context: fake_prepare,
    )

    monkeypatch.setattr(
        backends,
        "get_command",
        lambda _b: typ.cast("SafeCmdBuilder", _StubTool("bwrap")),
    )

    outcome = backend.run(
        tmp_path,
        "echo hi",
        context=_make_context(container_tmp=tmp_path, logger=messages.append),
    )

    assert outcome is None
    assert messages == ["bubblewrap unavailable"]
