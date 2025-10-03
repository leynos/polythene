"""Compatibility loader for :mod:`polythene.cmd_utils` from the ``src`` tree."""

from __future__ import annotations

import typing as typ

from ._src_loader import load

_MODULE = load(__name__)

if typ.TYPE_CHECKING:  # pragma: no cover - only evaluated statically
    from src.polythene.cmd_utils import (  # noqa: F401
        Command,
        TimeoutConflictError,
        _merge_timeout,
        run_cmd,
    )
