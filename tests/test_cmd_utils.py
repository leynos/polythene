"""Unit tests for :mod:`polythene.cmd_utils`."""

from __future__ import annotations

import os
import subprocess
import sys
import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

import pytest
from plumbum import local
from plumbum.commands.processes import (
    ProcessTimedOut,
)

from polythene.cmd_utils import TimeoutConflictError, _merge_timeout, run_cmd


def _stream_payload() -> str:
    """Return a snippet writing distinct markers to stdout and stderr."""
    return (
        "import sys;"
        " sys.stdout.write('child-stdout-marker\\n');"
        " sys.stderr.write('child-stderr-marker\\n')"
    )


def test_run_cmd_command_logs_and_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A plumbum command runs in the foreground and logs the invocation."""
    cmd = local["echo"]["hi"]
    capsys.readouterr()
    result = run_cmd(cmd, fg=True)
    captured = capsys.readouterr()
    assert result == 0
    assert "echo hi" in captured.err


def test_run_cmd_adapter_handles_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Adapters run successfully and log their invocation."""
    cmd = local["python"]["-c", "print('unit')"]
    capsys.readouterr()
    result = run_cmd(cmd, fg=True)
    captured = capsys.readouterr()
    assert result == 0
    assert "python -c" in captured.err


def test_run_cmd_foreground_inherits_stdout_without_overrides(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A foreground call without stream overrides still inherits stdout."""
    cmd = local[sys.executable]["-c", _stream_payload()]

    assert run_cmd(cmd, fg=True) == 0

    captured = capfd.readouterr()
    assert "child-stdout-marker" in captured.out
    assert "child-stderr-marker" in captured.err


@pytest.mark.parametrize("timeout", [None, 30])
def test_run_cmd_foreground_honours_stdout_sink(
    timeout: int | None,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """An explicit stdout sink silences the child with or without a timeout.

    The sink is checked with ``capfd`` because it must reach the child's real
    file descriptor; ``capsys`` would only see Python-level writes.
    """
    cmd = local[sys.executable]["-c", _stream_payload()]

    assert run_cmd(cmd, fg=True, timeout=timeout, stdout=subprocess.DEVNULL) == 0

    captured = capfd.readouterr()
    assert "child-stdout-marker" not in captured.out
    # The echo of the invocation also reaches stderr, so assert the exact line
    # the child wrote rather than a substring match.
    assert "child-stderr-marker" in captured.err.splitlines()


def test_run_cmd_foreground_overrides_inherit_stdin(tmp_path: Path) -> None:
    """A stdout override must not cost the child its inherited stdin.

    ``FG`` hard-codes inherited streams, so it preserves stdin; but a caller
    that redirects only stdout takes the ``run`` path instead, where plumbum
    defaults an unspecified ``stdin`` to ``PIPE``. ``run_proc`` then drains that
    pipe with no input, handing the child an immediate EOF.

    Pointing file descriptor 0 at a real file is what makes that difference
    observable: an inherited descriptor yields the file's contents, whereas a
    drained pipe yields nothing. The descriptor is swapped for the duration and
    restored in ``finally`` so pytest's own capture is left intact.
    """
    seen = tmp_path / "stdin.txt"
    payload = (
        f"import pathlib,sys;pathlib.Path({str(seen)!r}).write_text(sys.stdin.read())"
    )
    cmd = local[sys.executable]["-c", payload]

    saved_stdin = os.dup(0)
    try:
        with (tmp_path / "parent-stdin.txt").open("w+") as feed:
            feed.write("inherited-stdin\n")
            feed.flush()
            feed.seek(0)
            os.dup2(feed.fileno(), 0)
            assert run_cmd(cmd, fg=True, timeout=30, stdout=subprocess.DEVNULL) == 0
    finally:
        os.dup2(saved_stdin, 0)
        os.close(saved_stdin)

    assert seen.read_text() == "inherited-stdin\n"


def test_run_cmd_rejects_string_commands() -> None:
    """Passing a bare string raises an informative :class:`TypeError`."""
    with pytest.raises(TypeError, match="must satisfy SupportsFormulate"):
        run_cmd(typ.cast("typ.Any", "echo oops"))

    with pytest.raises(TypeError, match="must satisfy SupportsFormulate"):
        run_cmd(typ.cast("typ.Any", b"echo oops"))

    with pytest.raises(TypeError, match="must satisfy SupportsFormulate"):
        run_cmd(typ.cast("typ.Any", bytearray(b"echo oops")))

    with pytest.raises(TypeError, match="must satisfy SupportsFormulate"):
        run_cmd(typ.cast("typ.Any", 12345))

    with pytest.raises(TypeError, match="must satisfy SupportsFormulate"):
        run_cmd(typ.cast("typ.Any", None))


def test_run_cmd_timeout_conflict() -> None:
    """Providing timeout via both argument and kwargs raises an error."""
    with pytest.raises(TimeoutConflictError):
        _merge_timeout(1, {"timeout": 2})


def test_run_cmd_timeout_passthrough() -> None:
    """Timeout merges into keyword arguments for adapters."""
    calls: dict[str, object] = {}

    class _Stub:
        def formulate(self) -> list[str]:
            return ["stub"]

        def run(self, **kwargs: object) -> object:
            calls.update(kwargs)
            return 0

        def __call__(self, *args: object, **kwargs: object) -> object:
            return 0

    stub = _Stub()
    assert run_cmd(stub, timeout=5) == 0
    assert calls["timeout"] == 5


def test_run_cmd_timeout_with_unsupported_command() -> None:
    """Providing a timeout to a command without ``run`` raises ``TypeError``."""

    class _NoTimeout:
        def formulate(self) -> list[str]:
            return ["noop"]

        def __call__(self, *args: object, **kwargs: object) -> int:
            return 0

    no_timeout = _NoTimeout()

    with pytest.raises(TypeError, match="timeout execution"):
        run_cmd(no_timeout, fg=True, timeout=1)


def test_run_cmd_timeout_raises_timeout_error_on_expiry() -> None:
    """Commands that time out propagate :class:`TimeoutError`."""

    class _AlwaysTimeout:
        def formulate(self) -> list[str]:
            return ["timeout"]

        def run(self, **kwargs: object) -> object:
            raise ProcessTimedOut("timeout", 0.0)

        def __call__(self, *args: object, **kwargs: object) -> int:
            return 0

    cmd = _AlwaysTimeout()

    with pytest.raises(TimeoutError):
        run_cmd(cmd, fg=True, timeout=1)
