"""Self-tests for the readers :mod:`tests.helpers.cuprum_pin` exposes.

The alignment contract in ``test_cuprum_pin.py`` asserts that the repository's
real files agree. That is only worth anything if the readers reject the shapes
they are supposed to reject and return the values they claim to: a reader that
quietly found the first version-shaped string in a document would report a
broken lock as healthy, and the alignment test would pass for the wrong reason.

Each case here is a document the reader must refuse, or a pair of spellings it
must treat as equal. They are kept apart from the alignment assertions so a
broken reader is reported against the reader rather than against whichever
assertion it happened to break.
"""

from __future__ import annotations

import pytest

from tests.helpers.cuprum_pin import (
    declared_pin,
    lock_pin,
    lock_specifier,
    same_version,
)

_MANIFEST = """\
[project]
name = "polythene-isolate"
dependencies = {dependencies}
"""

_PROJECT_ENTRY = """\
[[package]]
name = "polythene-isolate"
version = "0.1.0"
source = {{ editable = "." }}

[package.metadata]
requires-dist = {requirements}
"""

_CUPRUM_ENTRY = """\
[[package]]
name = "cuprum"
version = {version}
source = {{ registry = "https://pypi.org/simple" }}
"""


def _manifest(*dependencies: str) -> str:
    """Return a manifest declaring ``dependencies`` verbatim."""
    rendered = ", ".join(f'"{entry}"' for entry in dependencies)
    return _MANIFEST.format(dependencies=f"[{rendered}]")


def _lock(
    *,
    version: str | None = "0.2.0b2",
    requirements: str = '[{ name = "cuprum", specifier = "==0.2.0b2" }]',
) -> str:
    """Return a lockfile with the given cuprum package and recorded requirement.

    ``version=None`` omits cuprum's package entry entirely, which is the lock
    that resolves nothing even though the project still requires it.
    """
    project = _PROJECT_ENTRY.format(requirements=requirements)
    if version is None:
        return project
    return project + _CUPRUM_ENTRY.format(version=f'"{version}"')


def test_declared_pin_reads_the_exact_pin() -> None:
    """The version comes back as the manifest spells it."""
    assert declared_pin(_manifest("cuprum==0.2.0b2")) == "0.2.0b2"


def test_declared_pin_refuses_a_range() -> None:
    """A range is what the pin exists to prevent, so it is not a pin."""
    with pytest.raises(AssertionError, match="single '=='"):
        declared_pin(_manifest("cuprum>=0.2.0b2"))


def test_declared_pin_refuses_an_upper_bound() -> None:
    """An interval, even a narrow one, admits a beta the suite has not seen."""
    with pytest.raises(AssertionError, match="single '=='"):
        declared_pin(_manifest("cuprum>=0.2.0b2,<0.3"))


def test_declared_pin_refuses_a_manifest_without_cuprum() -> None:
    """Absence is a failure, not a vacuous pass."""
    with pytest.raises(AssertionError, match="exactly once"):
        declared_pin(_manifest("cyclopts>=4.25"))


def test_declared_pin_refuses_two_declarations() -> None:
    """Two declarations could disagree, so neither is authoritative."""
    with pytest.raises(AssertionError, match="exactly once"):
        declared_pin(_manifest("cuprum==0.2.0b2", "cuprum==0.2.0b1"))


def test_declared_pin_names_the_dependency_it_cannot_parse() -> None:
    """An unparseable requirement is reported as the manifest's fault."""
    with pytest.raises(AssertionError, match="unparseable dependency"):
        declared_pin(_manifest("cuprum=="))


def test_declared_pin_requires_a_project_table() -> None:
    """A document with no ``[project]`` cannot declare a pin at all."""
    with pytest.raises(AssertionError, match=r"\[project\]"):
        declared_pin("[build-system]\nrequires = []\n")


def test_lock_pin_reads_the_resolved_version() -> None:
    """The package entry's own version is what the gate installs."""
    assert lock_pin(_lock()) == "0.2.0b2"


def test_lock_pin_refuses_a_lock_without_cuprum() -> None:
    """A lock that lost its cuprum entry resolves nothing to test against."""
    with pytest.raises(AssertionError, match="exactly one cuprum"):
        lock_pin(_lock(version=None))


def test_lock_pin_refuses_two_cuprum_entries() -> None:
    """Two entries would mean the lock resolves cuprum twice."""
    doubled = _lock() + (
        "\n[[package]]\n"
        'name = "cuprum"\nversion = "0.2.0b1"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
    )

    with pytest.raises(AssertionError, match="exactly one cuprum"):
        lock_pin(doubled)


def test_lock_specifier_reads_the_recorded_requirement() -> None:
    """The copied requirement is read, not the resolved entry."""
    assert lock_specifier(_lock()) == "0.2.0b2"


def test_lock_specifier_reports_a_stale_requirement() -> None:
    """A requirement that lagged the resolved entry is returned as written.

    Returning the lagging value rather than the resolved one is the point: the
    caller compares it with the manifest and reports the mismatch.
    """
    stale = _lock(requirements='[{ name = "cuprum", specifier = "==0.2.0b1" }]')

    assert lock_specifier(stale) == "0.2.0b1"


def test_lock_specifier_refuses_a_range() -> None:
    """A copied range cannot be compared with an exact pin."""
    ranged = _lock(requirements='[{ name = "cuprum", specifier = ">=0.2.0b2" }]')

    with pytest.raises(AssertionError, match="single '=='"):
        lock_specifier(ranged)


def test_lock_specifier_refuses_a_lock_without_a_project_entry() -> None:
    """Without the project package there is no metadata to read."""
    lock = _lock().replace('name = "polythene-isolate"', 'name = "something-else"')

    with pytest.raises(AssertionError, match="exactly one polythene-isolate"):
        lock_specifier(lock)


def test_lock_specifier_refuses_a_lock_without_a_requirement() -> None:
    """A project entry that records no cuprum requirement fails the contract."""
    with pytest.raises(AssertionError, match="exactly one cuprum requirement"):
        lock_specifier(_lock(requirements="[]"))


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("0.2.0b2", "0.2.0b2"),
        ("0.2.0-beta2", "0.2.0b2"),
        ("0.2.0-b2", "0.2.0b2"),
    ],
)
def test_same_version_accepts_equivalent_spellings(left: str, right: str) -> None:
    """Two spellings of one release are one version, so a manifest may use either."""
    assert same_version(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [("0.2.0b2", "0.2.0b1"), ("0.2.0", "0.2.0rc1")],
)
def test_same_version_rejects_a_different_release(left: str, right: str) -> None:
    """A near miss is a mismatch, not a rounding error."""
    assert not same_version(left, right)


def test_same_version_reports_an_unparseable_version() -> None:
    """A malformed version fails the contract rather than comparing as unequal."""
    with pytest.raises(AssertionError, match="not a version"):
        same_version("not-a-version", "0.2.0b2")
