"""Compatibility loader for :mod:`polythene.__main__` from the ``src`` tree."""

from __future__ import annotations

import typing as typ

from ._src_loader import load

_MODULE = load(__name__)

if typ.TYPE_CHECKING:  # pragma: no cover - only evaluated statically
    from src.polythene.__main__ import main as main
