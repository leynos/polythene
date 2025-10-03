"""Execution backends for the ``polythene exec`` command."""

from __future__ import annotations

import typing as typ
from dataclasses import dataclass
from pathlib import Path

from plumbum.commands.base import BaseCommand
from plumbum.commands.processes import ProcessExecutionError

from .cmd_utils import run_cmd
from .script_utils import ensure_directory, get_command

__all__ = [
    "Backend",
    "create_backends",
    "ensure_runtime_paths",
]


Logger = typ.Callable[[str], None]

PrepareFn = typ.Callable[
    [BaseCommand, Path, str, Logger, int | None, Path], list[str] | None
]


@dataclass(slots=True, frozen=True)
class Backend:
    """Descriptor for an execution backend."""

    name: str
    binary: str
    prepare: PrepareFn
    ensure_dirs: bool = True
    requires_root: bool = False

    def run(
        self,
        root: Path,
        inner_cmd: str,
        *,
        timeout: int | None,
        logger: Logger,
        container_tmp: Path,
    ) -> int | None:
        """Probe and run the backend, returning the exit status."""

        try:
            tool = get_command(self.binary)
        except SystemExit:
            return None

        if self.ensure_dirs:
            ensure_runtime_paths(root)

        args = self.prepare(tool, root, inner_cmd, logger, timeout, container_tmp)
        if args is None:
            return None

        logger(f"Executing via {self.name}")
        result = run_cmd(tool[tuple(args)], fg=True, timeout=timeout)
        return int(result) if result is not None else 0


def ensure_runtime_paths(root: Path) -> None:
    """Ensure directories required by execution backends exist."""

    for sub in ("dev", "tmp"):
        ensure_directory(root / sub)


def _probe_bwrap_userns(
    bwrap: BaseCommand,
    *,
    timeout: int | None,
    logger: Logger,
) -> list[str]:
    try:
        run_cmd(
            bwrap[
                (
                    "--unshare-user",
                    "--uid",
                    "0",
                    "--gid",
                    "0",
                    "--bind",
                    "/",
                    "/",
                    "true",
                )
            ],
            fg=True,
            timeout=timeout,
        )
    except (ProcessExecutionError, SystemExit, OSError) as exc:
        logger(f"User namespace probe failed: {exc}")
        return []
    return ["--unshare-user", "--uid", "0", "--gid", "0"]


def _probe_bwrap_proc(
    bwrap: BaseCommand,
    base_flags: list[str],
    root: Path,
    *,
    timeout: int | None,
) -> list[str]:
    probe = [
        *base_flags,
        "--bind",
        str(root),
        "/",
        "--proc",
        "/proc",
        "true",
    ]
    try:
        run_cmd(bwrap[tuple(probe)], fg=True, timeout=timeout)
    except (ProcessExecutionError, SystemExit, OSError):
        return []
    return ["--proc", "/proc"]


def _prepare_bwrap(
    bwrap: BaseCommand,
    root: Path,
    inner_cmd: str,
    logger: Logger,
    timeout: int | None,
    container_tmp: Path,
) -> list[str] | None:
    base_flags = _probe_bwrap_userns(bwrap, timeout=timeout, logger=logger)
    base_flags.extend(["--unshare-pid", "--unshare-ipc", "--unshare-uts"])
    proc_flags = _probe_bwrap_proc(bwrap, base_flags, root, timeout=timeout)
    probe_args = [
        *base_flags,
        "--bind",
        str(root),
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        *proc_flags,
        "--tmpfs",
        str(container_tmp),
        "--chdir",
        "/",
        "/bin/sh",
        "-c",
        "true",
    ]
    try:
        run_cmd(bwrap[tuple(probe_args)], fg=True, timeout=timeout)
    except (ProcessExecutionError, SystemExit, OSError):
        return None

    return [
        *base_flags,
        "--bind",
        str(root),
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        *proc_flags,
        "--tmpfs",
        str(container_tmp),
        "--chdir",
        "/",
        "/bin/sh",
        "-lc",
        inner_cmd,
    ]


def _prepare_proot(
    proot: BaseCommand,
    root: Path,
    inner_cmd: str,
    _logger: Logger,
    timeout: int | None,
    _container_tmp: Path,
) -> list[str] | None:
    probe_args = ["-R", str(root), "-0", "/bin/sh", "-c", "true"]
    try:
        run_cmd(proot[tuple(probe_args)], fg=True, timeout=timeout)
    except (ProcessExecutionError, SystemExit, OSError):
        return None
    return ["-R", str(root), "-0", "/bin/sh", "-lc", inner_cmd]


def _prepare_chroot(
    chroot: BaseCommand,
    root: Path,
    inner_cmd: str,
    _logger: Logger,
    timeout: int | None,
    _container_tmp: Path,
) -> list[str] | None:
    probe_args = [str(root), "/bin/sh", "-c", "true"]
    try:
        run_cmd(chroot[tuple(probe_args)], fg=True, timeout=timeout)
    except (ProcessExecutionError, SystemExit, OSError):
        return None
    return [
        str(root),
        "/bin/sh",
        "-lc",
        f"export PATH=/bin:/sbin:/usr/bin:/usr/sbin; {inner_cmd}",
    ]


def create_backends() -> tuple[Backend, ...]:
    """Return the supported execution backends in priority order."""

    return (
        Backend(
            name="bubblewrap",
            binary="bwrap",
            prepare=_prepare_bwrap,
        ),
        Backend(
            name="proot",
            binary="proot",
            prepare=_prepare_proot,
        ),
        Backend(
            name="chroot",
            binary="chroot",
            prepare=_prepare_chroot,
            ensure_dirs=False,
            requires_root=True,
        ),
    )
