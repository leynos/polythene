"""Core CLI and isolation logic for Polythene."""

from __future__ import annotations

import contextlib
import os
import shlex
import sys
import tempfile
import time
import typing as typ
from pathlib import Path

import cyclopts
from cyclopts import App, Parameter
from plumbum.commands.processes import ProcessExecutionError
from uuid6 import uuid7

from .backends import Backend, create_backends, ensure_runtime_paths
from .script_utils import ensure_directory, get_command, run_cmd

# -------------------- Configuration --------------------

CONTAINER_TMP = Path(tempfile.gettempdir())
BACKENDS: tuple[Backend, ...] = create_backends()
_DEFAULT_STORE_FALLBACK = Path(tempfile.gettempdir()) / "polythene"
DEFAULT_STORE = Path(
    os.environ.get("POLYTHENE_STORE", str(_DEFAULT_STORE_FALLBACK))
).resolve()
VERBOSE = bool(os.environ.get("POLYTHENE_VERBOSE"))

IS_ROOT = os.geteuid() == 0

# Make Podman as “quiet and simple” as possible for nested/sandboxed execution.
os.environ.setdefault("CONTAINERS_STORAGE_DRIVER", "vfs")
os.environ.setdefault("CONTAINERS_EVENTS_BACKEND", "file")

app = App()
app.help = "polythene — Temu podman for Codex"
app.config = (cyclopts.config.Env("POLYTHENE_", command=False),)
app.end_of_options_delimiter = "--"

ImageArgument = typ.Annotated[
    str,
    Parameter(
        help="Image reference, e.g. docker.io/library/busybox:latest",
    ),
]
UuidArgument = typ.Annotated[
    str, Parameter(help="UUID of the exported filesystem (from `polythene pull`)")
]
StoreOption = typ.Annotated[
    Path,
    Parameter(
        alias=["-s", "--store"],
        env_var="POLYTHENE_STORE",
        help="Directory to store UUID rootfs trees",
    ),
]
TimeoutOption = typ.Annotated[
    int | None,
    Parameter(alias=["-t", "--timeout"], help="Timeout in seconds to allow"),
]
CommandToken = typ.Annotated[
    str,
    Parameter(
        name="CMD",
        help="Command and arguments to execute inside the rootfs",
        allow_leading_hyphen=True,
    ),
]

IsolationName = typ.Literal["bubblewrap", "proot", "chroot"]
ISOLATION_NAMES: tuple[IsolationName, ...] = typ.cast(
    "tuple[IsolationName, ...]", typ.get_args(IsolationName)
)
IsolationOption = typ.Annotated[
    IsolationName | None,
    Parameter(
        alias=["-i", "--isolation"],
        env_var="POLYTHENE_ISOLATION",
        help=(
            "Preferred isolation backend. When provided, the requested backend "
            "is probed first with the remaining fallbacks tried afterwards."
        ),
    ),
]


def _error(message: str) -> None:
    """Print ``message`` to stderr without additional formatting."""
    print(message, file=sys.stderr)


def _normalise_retcode(retcode: int | None) -> int:
    """Return a sensible exit status when a command lacks a numeric code."""
    if not retcode:
        return 1
    return int(retcode)


def log(msg: str) -> None:
    """Print ``msg`` to stderr with a timestamp when verbose mode is enabled."""
    if VERBOSE:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", file=sys.stderr)


def store_path_for(uuid: str, store: Path) -> Path:
    """Return the absolute path for ``uuid`` under ``store``."""
    return (store / uuid).resolve()


def generate_uuid() -> str:
    """Generate a UUID for a new root filesystem."""
    return str(uuid7())


# -------------------- Image export (“pull”) --------------------


def export_rootfs(image: str, dest: Path, *, timeout: int | None = None) -> None:
    """Export a container image filesystem to dest/ via podman create+export."""
    podman = get_command("podman")
    tar = get_command("tar")

    # Pull explicitly (keeps exec fully offline later)
    log(f"Pulling {image} …")
    try:
        run_cmd(podman["pull", image], fg=True, timeout=timeout)
    except ProcessExecutionError as exc:
        _error(f"Failed to pull image {image}: {exc}")
        raise SystemExit(_normalise_retcode(exc.retcode)) from exc

    ensure_directory(dest, exist_ok=False)

    # Create a stopped container to export its rootfs
    try:
        create_result = run_cmd(
            podman["create", "--pull=never", image, "true"],
            timeout=timeout,
        )
        cid_output = (
            create_result[1] if isinstance(create_result, tuple) else create_result
        )
        cid = str(cid_output).strip()
    except ProcessExecutionError as exc:
        _error(f"Failed to create container from {image}: {exc}")
        raise SystemExit(_normalise_retcode(exc.retcode)) from exc
    try:
        log(f"Exporting rootfs of {cid} → {dest}")
        # Pipe: podman export CID | tar -C dest -x
        # plumbum pipes stream in FG without buffering the whole archive
        run_cmd(
            (podman["export", cid] | tar["-C", str(dest), "-x"]),
            fg=True,
            timeout=timeout,
        )
    finally:
        with contextlib.suppress(ProcessExecutionError):
            run_cmd(podman["rm", cid], fg=True, timeout=timeout)

    # Metadata (best-effort, does not affect functionality)
    meta = dest / ".polythene-meta"
    with contextlib.suppress(Exception):
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        meta.write_text(
            f"image={image}\ncreated={timestamp}\n",
            encoding="utf-8",
        )


# -------------------- CLI commands --------------------


@app.command(name="pull")
def cmd_pull(
    image: ImageArgument,
    *,
    store: StoreOption = DEFAULT_STORE,
    timeout: TimeoutOption = None,
) -> None:
    """Pull IMAGE, export it into STORE/UUID, and print the UUID."""
    ensure_directory(store)
    uid = generate_uuid()
    root = store_path_for(uid, store)
    try:
        export_rootfs(image, root, timeout=timeout)
    except FileExistsError:
        # Incredibly unlikely with v7; regenerate once
        uid = generate_uuid()
        root = store_path_for(uid, store)
        export_rootfs(image, root, timeout=timeout)

    # Ensure minimal dirs for later exec
    ensure_runtime_paths(root)

    print(uid)


@app.command(name="exec")
def cmd_exec(
    uuid: UuidArgument,
    *cmd: CommandToken,
    store: StoreOption = DEFAULT_STORE,
    timeout: TimeoutOption = None,
    isolation: IsolationOption = None,
) -> None:
    """Run ``CMD`` inside the UUID's rootfs with configurable backend priority."""
    if not cmd:
        _error("No command provided")
        raise SystemExit(2)

    root = store_path_for(uuid, store)
    if not root.is_dir():
        _error(f"No such UUID rootfs: {uuid} ({root})")
        raise SystemExit(1)

    tokens = list(cmd)
    inner_cmd = " ".join(shlex.quote(x) for x in tokens)

    selected_backends = BACKENDS
    if isolation is not None:
        backends_by_name = {backend.name: backend for backend in BACKENDS}
        try:
            preferred = backends_by_name[isolation]
        except KeyError:
            _error(f"Unsupported isolation backend requested: {isolation}")
            raise SystemExit(2) from None
        remaining = [backend for backend in BACKENDS if backend is not preferred]
        selected_backends = (preferred, *remaining)

    for backend in selected_backends:
        if backend.requires_root and not IS_ROOT:
            continue
        try:
            rc = backend.run(
                root,
                inner_cmd,
                timeout=timeout,
                logger=log,
                container_tmp=CONTAINER_TMP,
            )
        except ProcessExecutionError as exc:
            raise SystemExit(_normalise_retcode(exc.retcode)) from exc
        if rc is not None:
            if rc == 0:
                return
            raise SystemExit(rc)

    _error("All isolation modes unavailable (bwrap/proot/chroot).")
    raise SystemExit(126)


def main(argv: typ.Sequence[str] | None = None) -> None:
    """Invoke the Cyclopts CLI entry point."""
    if argv is None:
        argv = sys.argv[1:]
    app(list(argv))


__all__ = (
    "BACKENDS",
    "CONTAINER_TMP",
    "DEFAULT_STORE",
    "ISOLATION_NAMES",
    "IS_ROOT",
    "VERBOSE",
    "IsolationName",
    "app",
    "cmd_exec",
    "cmd_pull",
    "export_rootfs",
    "generate_uuid",
    "log",
    "main",
    "store_path_for",
)
