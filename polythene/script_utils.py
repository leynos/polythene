"""Shared helpers for invoking external tooling and preparing paths."""

from __future__ import annotations

import shutil
import sys
import typing as typ
from pathlib import Path

from .cmd_utils import program, run_cmd

if typ.TYPE_CHECKING:
    from cuprum import SafeCmdBuilder

__all__ = [
    "PKG_DIR",
    "ensure_directory",
    "ensure_exists",
    "get_command",
    "run_cmd",
    "unique_match",
]

PKG_DIR = Path(__file__).resolve().parent

PathIterable = typ.Iterable[Path]


def _abort(message: str, *, code: int) -> typ.NoReturn:
    """Print an error message and terminate the process with ``code``."""
    print(message, file=sys.stderr)
    raise SystemExit(code)


def get_command(name: str) -> SafeCmdBuilder:
    """Return a builder for ``name``, exiting with an error if it is missing.

    Cuprum resolves a program's executable when the command *runs*, not when
    it is built, so a missing binary would otherwise surface as a traceback
    from deep inside a probe. Checking ``PATH`` here keeps the documented
    ``127`` exit status and the one-line diagnostic, and lets callers treat a
    returned builder as proof that the tool exists.

    Parameters
    ----------
    name : str
        The executable to resolve.

    Returns
    -------
    SafeCmdBuilder
        A builder for ``name``, drawing on :data:`polythene.cmd_utils.
        POLYTHENE_CATALOGUE`.

    Raises
    ------
    SystemExit
        With status ``127`` when ``name`` is not an executable on ``PATH``.

    Examples
    --------
    >>> podman = get_command("podman")  # doctest: +SKIP
    >>> podman("image", "exists", "busybox")  # doctest: +SKIP

    """
    if shutil.which(name) is None:
        _abort(f"Required command not found: {name}", code=127)
    return program(name)


def ensure_exists(path: Path, message: str) -> None:
    """Exit with an error if ``path`` does not exist."""
    if not path.exists():  # pragma: no cover - defensive check
        _abort(f"error: {message}: {path}", code=2)


def ensure_directory(path: Path, *, exist_ok: bool = True) -> Path:
    """Create ``path`` (and parents) if needed and return it."""
    path.mkdir(parents=True, exist_ok=exist_ok)
    return path


def unique_match(paths: PathIterable, *, description: str) -> Path:
    """Return the sole path in ``paths`` or exit with an error."""
    matches = list(paths)
    if len(matches) != 1:
        _abort(
            f"error: expected exactly one {description}, found {len(matches)}",
            code=2,
        )
    return matches[0]
