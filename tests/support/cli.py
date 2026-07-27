"""CLI result type shared by fixtures and BDD assertions.

This lives outside ``conftest.py`` so every consumer imports it via the
single canonical path ``tests.support.cli``, regardless of whether the
consumer is a fixture defined in a ``conftest.py`` or a step/assertion
defined in a BDD test module. See ``tests/support/__init__.py`` for the
rationale.
"""

from __future__ import annotations

import dataclasses as dc


@dc.dataclass(slots=True)
class CliResult:
    """Container capturing CLI output and exit status."""

    exit_code: int
    stdout: str
    stderr: str
