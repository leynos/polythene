"""Compatibility loader for :mod:`polythene.backends` from the ``src`` tree."""

from __future__ import annotations

import typing as typ

from ._src_loader import load

_MODULE = load(__name__)

if typ.TYPE_CHECKING:  # pragma: no cover - only evaluated statically
    from src.polythene.backends import (  # noqa: F401
        Backend,
        create_backends,
        ensure_runtime_paths,
    )
