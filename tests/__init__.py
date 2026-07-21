"""Test package for Polythene.

Making ``tests`` a real package (rather than relying on pytest's rootdir
path-insertion for directories without ``__init__.py``) gives every test
module a single, unambiguous dotted import path such as
``tests.support.cli``. See ``tests/support/__init__.py`` for why this
matters for mutmut's sandboxed test runs.
"""

from __future__ import annotations
