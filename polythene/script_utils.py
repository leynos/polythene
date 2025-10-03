"""Compatibility loader for :mod:`polythene.script_utils` from the ``src`` tree."""

from __future__ import annotations

import typing as typ

from ._src_loader import load

_MODULE = load(__name__)

if typ.TYPE_CHECKING:  # pragma: no cover - only evaluated statically
    from src.polythene.script_utils import (  # noqa: F401
        ensure_directory,
        ensure_exists,
        get_command,
        unique_match,
    )
