"""Compat shim so tooling referencing the legacy package layout keeps working.

The upstream shared-actions workflows expect a ``polythene`` directory at the
repository root when running coverage under Slipcover.  The library now lives in
``src/polythene`` instead, so importing :mod:`polythene` directly from the repo
would previously fail during instrumentation.  We load the real module from the
``src`` tree and replace ourselves in :data:`sys.modules` to keep every runtime
path consistent while avoiding code duplication.
"""

from __future__ import annotations

import typing as typ

from ._src_loader import load

_MODULE = load(__name__)

if typ.TYPE_CHECKING:  # pragma: no cover - only evaluated statically
    from src.polythene import app as app
    from src.polythene import backends as backends
    from src.polythene import cmd_utils as cmd_utils
    from src.polythene import main as main
    from src.polythene import script_utils as script_utils
