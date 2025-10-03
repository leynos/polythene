"""Unit tests for :mod:`polythene.cmd_utils`."""

from __future__ import annotations

import pytest
from plumbum import local

from polythene.cmd_utils import TimeoutConflictError, _merge_timeout, run_cmd


def test_run_cmd_sequence_logs_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    """A simple sequence runs in the foreground and logs the command."""
    capsys.readouterr()
    result = run_cmd(["echo", "hi"], fg=True)
    captured = capsys.readouterr()
    assert result == 0
    assert "$ echo hi" in captured.err


def test_run_cmd_adapter_handles_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Adapters run successfully and log their invocation."""
    cmd = local["python"]["-c", "print('unit')"]
    capsys.readouterr()
    result = run_cmd(cmd, fg=True)
    captured = capsys.readouterr()
    assert result == 0
    assert "python -c" in captured.err


def test_run_cmd_rejects_string_commands() -> None:
    """Passing a bare string raises an informative :class:`TypeError`."""
    with pytest.raises(TypeError, match="Command strings must be provided"):
        run_cmd("echo oops")


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

    stub = _Stub()
    assert run_cmd(stub, timeout=5) == 0
    assert calls["timeout"] == 5
