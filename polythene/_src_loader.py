"""Helper utilities for loading modules from the src/ tree at runtime.

These shims let legacy tooling that expects a top-level ``polythene`` package
import the modern ``src`` layout without duplicating the implementation files.
"""

from __future__ import annotations

import sys
import typing as typ
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

if typ.TYPE_CHECKING:  # pragma: no cover - import for typing only
    from types import ModuleType

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def load(module_name: str) -> ModuleType:
    """Load ``module_name`` from the ``src`` tree and return it.

    The helper mirrors :func:`importlib.import_module` but bypasses normal
    package resolution so we can map ``polythene`` back to ``src/polythene``
    without mutating :data:`sys.path` for callers.
    """
    parts = module_name.split(".")
    target = _SRC_ROOT.joinpath(*parts)
    target = target / "__init__.py" if target.is_dir() else target.with_suffix(".py")

    spec = spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive guard
        msg = f"Cannot locate {module_name!r} in the src/ tree."
        raise ImportError(msg)

    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
