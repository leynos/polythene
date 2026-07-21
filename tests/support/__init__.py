"""Shared test-support helpers imported by name via ``tests.support``.

Keeping these helpers in a real, importable package (rather than defining
them in ``conftest.py``) ensures every consumer resolves the same module
object. ``conftest.py`` files are collected specially by pytest, and a bare
``from conftest import X`` performed by a test module can end up importing a
*second*, distinct copy of ``conftest`` under some sandboxing/import-mode
combinations (notably mutmut's isolated test run). That produces classes
that are structurally identical yet fail ``isinstance`` checks against each
other. Routing all imports through ``tests.support`` avoids the ambiguity.
"""

from __future__ import annotations
