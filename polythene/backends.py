"""Execution backends for the ``polythene exec`` command."""

from __future__ import annotations

import dataclasses as dc
import errno
import os
import typing as typ
from pathlib import Path

from plumbum.commands.base import BaseCommand
from plumbum.commands.processes import ProcessExecutionError

from .cmd_utils import run_cmd
from .script_utils import ensure_directory, get_command

__all__ = [
    "Backend",
    "BackendContext",
    "BubblewrapUnavailable",
    "create_backends",
    "ensure_runtime_paths",
]


Logger = typ.Callable[[str], None]


@dc.dataclass(slots=True, frozen=True)
class BackendContext:
    """Configuration shared between backend probes and execution."""

    logger: Logger
    timeout: int | None
    container_tmp: Path


PrepareFn = typ.Callable[[BaseCommand, Path, str], list[str] | None]
PrepareFactory = typ.Callable[[BackendContext], PrepareFn]


class BubblewrapUnavailable(RuntimeError):  # noqa: N818 - aligns with CLI wording
    """Raised when the host kernel forbids bubblewrap user namespaces."""


_UNPRIVILEGED_USERNS_PATH = Path("/proc/sys/kernel/unprivileged_userns_clone")
_BWRAP_SYSCTL_DISABLED = (
    "bubblewrap requires unprivileged user namespaces; falling back to proot"
)
_BWRAP_PERMISSION_DENIED = "unprivileged user namespaces disabled"


def _is_privileged_user() -> bool:
    """Return ``True`` when the current process is allowed privileged actions."""
    # ``geteuid`` is not available on Windows, but Polythene only targets Linux.
    # Guard in case someone executes the tests elsewhere.
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return False
    return geteuid() == 0


def _is_bwrap_perm_error(exc: Exception) -> bool:
    """Return ``True`` when ``exc`` indicates user namespace permissions."""
    if isinstance(exc, ProcessExecutionError):
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="ignore")
        else:
            stderr = stderr or ""
        errno_value = getattr(exc, "errno", None)
        if "Permission denied" in stderr:
            return True
        return "Permission denied" in str(exc) or errno_value == errno.EPERM

    if isinstance(exc, OSError):
        return exc.errno == errno.EPERM

    return False


@dc.dataclass(slots=True, frozen=True)
class Backend:
    """Descriptor for an execution backend."""

    name: str
    binary: str
    prepare_factory: PrepareFactory
    ensure_dirs: bool = True
    requires_root: bool = False

    def run(
        self,
        root: Path,
        inner_cmd: str,
        *,
        context: BackendContext,
    ) -> tuple[str, int] | None:
        """Probe and run the backend, returning the chosen name and exit status."""
        logger = context.logger
        timeout = context.timeout
        try:
            tool = get_command(self.binary)
        except SystemExit as exc:
            logger(f"{self.name} unavailable: {exc}")
            return None

        if self.ensure_dirs:
            ensure_runtime_paths(root)

        try:
            prepare = self.prepare_factory(context)
            args = prepare(tool, root, inner_cmd)
        except BubblewrapUnavailable as exc:
            logger(str(exc))
            return None

        if args is None:
            logger(f"{self.name} unavailable during preparation")
            return None

        logger(f"Executing via {self.name}")
        result = run_cmd(tool[tuple(args)], fg=True, timeout=timeout)
        exit_code = int(result) if result is not None else 0
        return (self.name, exit_code)


def ensure_runtime_paths(root: Path) -> None:
    """Ensure directories required by execution backends exist."""
    for sub in ("dev", "tmp"):
        ensure_directory(root / sub)


def _probe_bwrap_userns(bwrap: BaseCommand, context: BackendContext) -> list[str]:
    logger = context.logger
    timeout = context.timeout
    if not _is_privileged_user():
        try:
            value = _UNPRIVILEGED_USERNS_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger(f"Unable to read /proc/sys/kernel/unprivileged_userns_clone: {exc}")
        else:
            if value == "0":
                raise BubblewrapUnavailable(_BWRAP_SYSCTL_DISABLED)

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
    except (ProcessExecutionError, OSError) as exc:
        if _is_bwrap_perm_error(exc):
            raise BubblewrapUnavailable(_BWRAP_PERMISSION_DENIED) from exc
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


def make_prepare_bwrap(context: BackendContext) -> PrepareFn:
    timeout = context.timeout
    container_tmp = context.container_tmp

    def _prepare_bwrap(
        bwrap: BaseCommand,
        root: Path,
        inner_cmd: str,
    ) -> list[str] | None:
        base_flags = _probe_bwrap_userns(bwrap, context)
        base_flags.extend(["--unshare-pid", "--unshare-ipc", "--unshare-uts"])
        proc_flags = _probe_bwrap_proc(
            bwrap,
            base_flags,
            root,
            timeout=timeout,
        )
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
            "-c",
            inner_cmd,
        ]

    return _prepare_bwrap


def make_prepare_proot(context: BackendContext) -> PrepareFn:
    timeout = context.timeout

    def _prepare_proot(
        proot: BaseCommand,
        root: Path,
        inner_cmd: str,
    ) -> list[str] | None:
        probe_args = ["-R", str(root), "-0", "/bin/sh", "-c", "true"]
        try:
            run_cmd(proot[tuple(probe_args)], fg=True, timeout=timeout)
        except (ProcessExecutionError, SystemExit, OSError):
            return None
        return ["-R", str(root), "-0", "/bin/sh", "-c", inner_cmd]

    return _prepare_proot


def make_prepare_chroot(context: BackendContext) -> PrepareFn:
    timeout = context.timeout

    def _prepare_chroot(
        chroot: BaseCommand,
        root: Path,
        inner_cmd: str,
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

    return _prepare_chroot


def create_backends() -> tuple[Backend, ...]:
    """Return the supported execution backends in priority order."""
    return (
        Backend(
            name="bubblewrap",
            binary="bwrap",
            prepare_factory=make_prepare_bwrap,
        ),
        Backend(
            name="proot",
            binary="proot",
            prepare_factory=make_prepare_proot,
        ),
        Backend(
            name="chroot",
            binary="chroot",
            prepare_factory=make_prepare_chroot,
            ensure_dirs=False,
            requires_root=True,
        ),
    )
