"""Utilities for echoing and running external commands.

Provides a single entrypoint, :func:`run_cmd`, that uniformly echoes and
executes plumbum command invocations or pipelines.

Examples
--------
>>> from plumbum import local
>>> run_cmd(local["echo"]["hello"])

"""

from __future__ import annotations

import sys
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

__all__ = [
    "run_cmd",
]


class TimeoutConflictError(TypeError):
    """Raised when mutually exclusive timeout options are provided."""

    def __init__(self) -> None:
        super().__init__("timeout specified via parameter and run_kwargs")


@typ.runtime_checkable
class SupportsFormulate(typ.Protocol):
    """Objects that expose a shell representation via ``formulate``."""

    def formulate(self) -> cabc.Sequence[str]:  # pragma: no cover - protocol
        ...

    def __call__(
        self, *args: object, **run_kwargs: object
    ) -> object:  # pragma: no cover - protocol
        ...


@typ.runtime_checkable
class SupportsRun(typ.Protocol):
    """Commands that support ``run`` with keyword arguments."""

    def run(
        self, *args: object, **run_kwargs: object
    ) -> object:  # pragma: no cover - protocol
        ...


@typ.runtime_checkable
class SupportsRunFg(typ.Protocol):
    """Commands that expose ``run_fg`` for foreground execution."""

    def run_fg(self, **run_kwargs: object) -> object:  # pragma: no cover - protocol
        ...


@typ.runtime_checkable
class SupportsAnd(typ.Protocol):
    """Commands that implement ``cmd & FG`` semantics."""

    def __and__(self, other: object) -> object:  # pragma: no cover - protocol
        ...


Command = SupportsFormulate

KwargDict = dict[str, object]

# Stream keys that ``run_cmd`` may forward to a command's ``run``. A caller
# supplying one wants that stream redirected, which ``FG`` cannot express: it
# hard-codes inherited streams. Such calls therefore take the ``run`` path.
_STREAM_KEYS = frozenset({"stdin", "stdout", "stderr"})


def _merge_timeout(timeout: float | None, run_kwargs: KwargDict) -> float | None:
    """Return the timeout to enforce, preferring ``run_kwargs`` when present."""
    if "timeout" in run_kwargs:
        if timeout is not None:
            raise TimeoutConflictError
        value = run_kwargs.pop("timeout")
        return typ.cast("float | None", value)
    return timeout


def _run_fg_with_overrides(
    cmd: Command,
    timeout: float | None,
    run_kwargs: KwargDict,
) -> None:
    """Run ``cmd`` in the foreground on the ``run`` path.

    ``run`` is the only foreground route that honours explicit stream
    overrides, so calls that pass one arrive here. Unset streams default to
    ``None`` (inherit), which keeps the wrapper as transparent as ``FG``.
    """
    if not isinstance(cmd, SupportsRun):
        msg = "Command does not support timeout execution"
        raise TypeError(msg)
    run_kwargs.setdefault("stdout", None)
    run_kwargs.setdefault("stderr", None)
    from plumbum.commands.processes import (  # pyright: ignore[reportMissingTypeStubs]
        ProcessTimedOut,
    )

    try:
        cmd.run(timeout=timeout, **run_kwargs)
    except ProcessTimedOut as exc:
        raise TimeoutError from exc


def run_cmd(
    cmd: Command,
    *,
    fg: bool = False,
    timeout: float | None = None,
    **run_kwargs: object,
) -> object:
    """Execute ``cmd`` while echoing it to stderr.

    Foreground calls inherit this process's streams unless the caller passes an
    explicit ``stdin``, ``stdout`` or ``stderr`` override; only then does the
    command run through ``run`` instead of ``FG``. Pass ``subprocess.DEVNULL``
    as ``stdout`` to keep a chatty tool from writing to the caller's stdout.
    """
    timeout = _merge_timeout(timeout, run_kwargs)
    if not isinstance(cmd, SupportsFormulate):
        msg = "Command must be a plumbum invocation or pipeline"
        raise TypeError(msg)

    print(f"$ {cmd}", file=sys.stderr)
    if fg:
        if timeout is not None or _STREAM_KEYS & run_kwargs.keys():
            _run_fg_with_overrides(cmd, timeout, run_kwargs)
            return 0
        if isinstance(cmd, SupportsRunFg):
            cmd.run_fg(**run_kwargs)
            return 0
        if isinstance(cmd, SupportsAnd) and not run_kwargs:
            from plumbum import FG  # pyright: ignore[reportMissingTypeStubs]

            return cmd & FG
        if run_kwargs:
            msg = (
                "Command does not support foreground execution with keyword arguments: "
                f"{sorted(run_kwargs.keys())}"
            )
            raise TypeError(msg)
        result = cmd()
        return result if isinstance(result, int) else 0

    if timeout is not None:
        if isinstance(cmd, SupportsRun):
            run_kwargs.setdefault("timeout", timeout)
        else:
            msg = "Command does not support timeout execution"
            raise TypeError(msg)

    if run_kwargs:
        if isinstance(cmd, SupportsRun):
            return cmd.run(**run_kwargs)
        msg = f"Command does not accept keyword arguments: {sorted(run_kwargs.keys())}"
        raise TypeError(msg)
    return cmd()
