"""Shared helpers for invoking external tooling."""

from __future__ import annotations

import sys
import typing as typ
from pathlib import Path

from plumbum import local

from .cmd_utils import run_cmd

if typ.TYPE_CHECKING:
    from plumbum.commands.base import BaseCommand

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


def get_command(name: str) -> BaseCommand:
    """Return a ``plumbum`` command, exiting with an error if it is missing."""

    try:
        return local[name]
    except Exception as exc:  # pragma: no cover - error path
        print(f"Required command not found: {name}", file=sys.stderr)
        raise SystemExit(127) from exc


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
