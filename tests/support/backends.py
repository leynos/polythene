"""Small backend doubles shared by CLI behaviour tests."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

    from polythene import backends


class _DummyBackend:
    def __init__(
        self,
        exit_code: int | None,
        *,
        requires_root: bool = False,
        name: str = "dummy",
    ) -> None:
        self.exit_code = exit_code
        self.requires_root = requires_root
        self.name = name
        self.calls: list[tuple[Path, str, int | None]] = []

    def run(
        self,
        root: Path,
        inner_cmd: str,
        *,
        context: backends.BackendContext,
    ) -> tuple[str, int] | None:
        self.calls.append((root, inner_cmd, context.timeout))
        return None if self.exit_code is None else (self.name, self.exit_code)
