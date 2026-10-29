"""Read the cuprum version each dependency site records.

Cuprum is pinned exactly because it is pre-release, so the pin is a deliberate
choice rather than an interval the resolver may satisfy however it likes. That
choice is recorded three times: as a requirement in ``pyproject.toml``, as a
resolved package and as a copied requirement in ``uv.lock``, and as whatever
the interpreter running the suite actually imported. Nothing keeps the three
together on its own, and a partial bump is a real failure mode: Dependabot
edits ``pyproject.toml`` and ``uv.lock`` and knows nothing about the installed
environment.

The readers live here rather than in the contract test for the reason
:mod:`tests.helpers.ci_workflows` gives: their rejection paths are tested
separately, so a broken reader is reported against the reader rather than
against whichever assertion it happened to break. They raise
:class:`AssertionError` naming the site, because a document that cannot be read
as the contract expects is a contract failure, not a caller error.

Version strings are returned exactly as each site spells them. Two PEP 440
spellings can name the same release (``0.2.0b2`` and ``0.2.0-beta2``), so
comparisons go through :func:`same_version` rather than ``==`` on the raw text.
"""

from __future__ import annotations

import importlib.metadata
import tomllib
import typing as typ

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

#: The distribution under contract, and the name `uv.lock` records for it.
CUP = "cuprum"

#: The project whose lockfile carries the recorded requirement. A project lock
#: resolves the project itself, so the requirement sits in this package's
#: metadata rather than in a top-level manifest.
PROJECT = "polythene-isolate"


def _project_table(pyproject_text: str) -> dict[str, object]:
    """Return ``[project]``, refusing a manifest that declares no such table."""
    document = tomllib.loads(pyproject_text)
    project = document.get("project")
    if not isinstance(project, dict):
        message = "pyproject.toml must declare a [project] table"
        raise AssertionError(message)  # noqa: TRY004 - a contract failure, not a caller type error.
    return typ.cast("dict[str, object]", project)


def _requirements(pyproject_text: str) -> list[Requirement]:
    """Parse the project's declared dependencies, naming any that does not parse."""
    dependencies = _project_table(pyproject_text).get("dependencies", [])
    if not isinstance(dependencies, list):
        message = "pyproject.toml's [project] dependencies must be an array"
        raise AssertionError(message)  # noqa: TRY004 - a contract failure, not a caller type error.
    requirements: list[Requirement] = []
    for entry in dependencies:
        if not isinstance(entry, str):
            message = f"a dependency must be a string, got {entry!r}"
            raise AssertionError(message)  # noqa: TRY004 - a contract failure, not a caller type error.
        try:
            requirements.append(Requirement(entry))
        except InvalidRequirement as error:
            message = f"pyproject.toml declares an unparseable dependency: {entry!r}"
            raise AssertionError(message) from error
    return requirements


def declared_pin(pyproject_text: str) -> str:
    r"""Return the exact cuprum version ``pyproject.toml`` requires.

    Parameters
    ----------
    pyproject_text : str
        The text of the repository's ``pyproject.toml``.

    Returns
    -------
    str
        The version named by the single ``==`` specifier on cuprum, spelled as
        the manifest spells it.

    Raises
    ------
    AssertionError
        If the project declares cuprum more than once, not at all, or with any
        requirement other than one exact pin. A range is refused because the
        whole point of the pin is that the suite has exercised one beta and not
        the next one the index happens to publish.

    Examples
    --------
    >>> declared_pin('[project]\ndependencies = ["cuprum==0.2.0b2"]\n')
    '0.2.0b2'

    """
    requirements = [
        requirement
        for requirement in _requirements(pyproject_text)
        if canonicalize_name(requirement.name) == CUP
    ]
    if len(requirements) != 1:
        message = (
            "pyproject.toml must declare cuprum exactly once, "
            f"found {len(requirements)}"
        )
        raise AssertionError(message)
    requirement = requirements[0]
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1 or specifiers[0].operator != "==":
        message = (
            "pyproject.toml must pin cuprum with a single '==', "
            f"found {requirement.specifier}"
        )
        raise AssertionError(message)
    return specifiers[0].version


def _packages(lock_text: str) -> list[dict[str, object]]:
    """Return the lockfile's package entries, refusing a document without them."""
    document = tomllib.loads(lock_text)
    packages = document.get("package")
    if not isinstance(packages, list):
        message = "uv.lock must hold a package array"
        raise AssertionError(message)  # noqa: TRY004 - a contract failure, not a caller type error.
    entries: list[dict[str, object]] = []
    for entry in packages:
        if not isinstance(entry, dict):
            message = (
                f"a uv.lock package entry must be a table, got {type(entry).__name__}"
            )
            raise AssertionError(message)  # noqa: TRY004 - a contract failure, not a caller type error.
        entries.append(typ.cast("dict[str, object]", entry))
    return entries


def lock_pin(lock_text: str) -> str:
    r"""Return the cuprum version ``uv.lock`` resolves to.

    Parameters
    ----------
    lock_text : str
        The text of the repository's ``uv.lock``.

    Returns
    -------
    str
        The ``version`` of the lock's single cuprum package entry.

    Raises
    ------
    AssertionError
        If the lock holds no cuprum entry, or holds more than one. Two entries
        would mean the lock resolves cuprum twice, which uv does not produce
        and which nothing downstream could interpret.

    Examples
    --------
    >>> lock_pin('[[package]]\nname = "cuprum"\nversion = "0.2.0b2"\n')
    '0.2.0b2'

    """
    locked = [
        entry["version"]
        for entry in _packages(lock_text)
        if entry.get("name") == CUP and "version" in entry
    ]
    if len(locked) != 1:
        message = (
            f"uv.lock must contain exactly one cuprum package entry, found {locked}"
        )
        raise AssertionError(message)
    version = locked[0]
    if not isinstance(version, str):
        message = f"cuprum's uv.lock version must be a string, got {version!r}"
        raise AssertionError(message)  # noqa: TRY004 - a contract failure, not a caller type error.
    return version


def lock_specifier(lock_text: str) -> str:
    r"""Return the version named by the lockfile's own recorded requirement.

    A lockfile records the resolved version *and* a copy of the requirement
    that produced it. Checking both catches the lock that was regenerated
    while ``pyproject.toml`` moved on: the resolved entry is current, but the
    copied requirement is stale and would drive the next update.

    Parameters
    ----------
    lock_text : str
        The text of the repository's ``uv.lock``.

    Returns
    -------
    str
        The version pinned by the requirement ``uv.lock`` records against the
        project package's metadata.

    Raises
    ------
    AssertionError
        If the lock holds no project package entry or no cuprum requirement,
        or if that requirement is not a single exact pin.

    Examples
    --------
    >>> text = (
    ...     '[[package]]\nname = "polythene-isolate"\n'
    ...     '[package.metadata]\n'
    ...     'requires-dist = [{ name = "cuprum", specifier = "==0.2.0b2" }]\n'
    ... )
    >>> lock_specifier(text)
    '0.2.0b2'

    """
    projects = [entry for entry in _packages(lock_text) if entry.get("name") == PROJECT]
    if len(projects) != 1:
        message = f"uv.lock must contain exactly one {PROJECT} package entry"
        raise AssertionError(message)
    metadata = projects[0].get("metadata", {})
    if not isinstance(metadata, dict):
        message = f"uv.lock's {PROJECT} metadata must be a table"
        raise AssertionError(message)  # noqa: TRY004 - a contract failure, not a caller type error.
    requirement_entries = typ.cast("dict[str, object]", metadata).get(
        "requires-dist", []
    )
    if not isinstance(requirement_entries, list):
        message = f"uv.lock's {PROJECT} requires-dist must be an array"
        raise AssertionError(message)  # noqa: TRY004 - a contract failure, not a caller type error.
    specifiers = [
        entry["specifier"]
        for entry in requirement_entries
        if isinstance(entry, dict) and entry.get("name") == CUP and "specifier" in entry
    ]
    if len(specifiers) != 1:
        message = (
            f"uv.lock must record exactly one cuprum requirement, found {specifiers}"
        )
        raise AssertionError(message)
    specifier = specifiers[0]
    if not isinstance(specifier, str) or not specifier.startswith("=="):
        message = (
            "uv.lock's recorded cuprum requirement must be a single '==', "
            f"found {specifier!r}"
        )
        raise AssertionError(message)
    return specifier.removeprefix("==")


def installed_version() -> str:
    """Return the version of cuprum the test interpreter imported.

    Returns
    -------
    str
        The installed distribution's version, as its metadata records it.

    Raises
    ------
    AssertionError
        If cuprum is not installed in this interpreter, which means the suite
        is running against an environment ``uv sync`` did not build.

    Examples
    --------
    >>> same_version(installed_version(), "0.2.0b2")
    True

    """
    try:
        return importlib.metadata.version(CUP)
    except importlib.metadata.PackageNotFoundError as error:
        message = f"{CUP} is not installed in the test interpreter; run 'uv sync'"
        raise AssertionError(message) from error


def same_version(left: str, right: str) -> bool:
    """Return whether two PEP 440 spellings name the same release.

    Parameters
    ----------
    left : str
        One version string, as some site spells it.
    right : str
        The version string to compare it with.

    Returns
    -------
    bool
        True when both parse and are equal as versions. Raw text equality is
        wrong here: ``0.2.0b2`` and ``0.2.0-beta2`` are the same release, and a
        manifest may spell the pin either way.

    Raises
    ------
    AssertionError
        If either string is not a PEP 440 version, so a malformed site fails as
        a contract rather than as a comparison that silently returned False.

    Examples
    --------
    >>> same_version("0.2.0-beta2", "0.2.0b2")
    True

    """
    try:
        return Version(left) == Version(right)
    except InvalidVersion as error:
        message = f"{error.args[0]!r} is not a version this contract can compare"
        raise AssertionError(message) from error
