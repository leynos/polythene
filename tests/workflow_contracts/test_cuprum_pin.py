"""Contract for the exact cuprum pin every dependency site must agree with.

Cuprum is pre-release, so ``pyproject.toml`` pins one exact beta rather than an
interval: the suite has exercised that beta and no other. A pin recorded in one
place and not the others is how the suite ends up testing a version the
repository does not ship. Three sites have to agree:

* ``pyproject.toml``, which decides what the resolver may pick;
* ``uv.lock``, which decides what the gate installs, both in its resolved
  package entry and in the copy of the requirement it records;
* the interpreter running the suite, which is what the assertions in the rest
  of the suite actually exercised.

The expected version is read from ``pyproject.toml`` and no version literal
appears below, so a bump is a single edit that either moves every site or fails
and names the one that lagged.

The freshness check reconstructs ``pyproject.toml`` and ``uv.lock`` from the
Git index and resolves them in a scratch directory. Reading the working tree
would not do: ``make build`` runs ``uv sync``, which silently re-locks a stale
``uv.lock`` before the suite starts, so a tree-based freshness check could never
fail under ``make test`` and a stale lock committed to the repository would ship
green. It is skipped where ``uv`` or the Git index is absent, since neither can
be replaced by an in-process check.

Run via ``make test``.
"""

from __future__ import annotations

import shutil
import typing as typ
from pathlib import Path

import pytest

from tests.helpers.cuprum_pin import (
    declared_pin,
    installed_version,
    lock_pin,
    lock_specifier,
    same_version,
)
from tests.support.process import run_command

if typ.TYPE_CHECKING:
    import pathlib as pth

#: Resolved rather than left to ``PATH`` at exec time, so the skip condition and
#: the command that runs are the same binary.
UV_BINARY = shutil.which("uv")
GIT_BINARY = shutil.which("git")

#: `git show` reads the index, which exists only in a real checkout. mutmut's
#: sandbox copies neither ``.git`` nor the index.
_NO_GIT_CHECKOUT = "no Git checkout to read indexed files from"

#: Resolving a stale pair may reach the index; a fresh one is answered from the
#: lockfile and needs no network. The bound is the module's own, above pytest's
#: 30-second default, so a slow index cannot fail the check as a hang.
_LOCK_TIMEOUT_SECONDS = 120.0

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
LOCKFILE = ROOT / "uv.lock"

pytestmark = pytest.mark.timeout(180)


def _committed(path: Path) -> str:
    """Return one tracked file's content as of the Git index.

    Parameters
    ----------
    path : Path
        The tracked file, which must lie inside the repository.

    Returns
    -------
    str
        The blob the index records for ``path``.

    Raises
    ------
    AssertionError
        If Git cannot read the blob, so an environment problem is reported as
        that rather than as a stale lock.

    """
    relative = path.relative_to(ROOT).as_posix()
    outcome = run_command(
        [typ.cast("str", GIT_BINARY), "show", f":{relative}"],
        cwd=ROOT,
    )
    assert outcome.exit_code == 0, (
        f"could not read the committed {relative} from the index; git said:\n"
        f"{outcome.stderr}"
    )
    return outcome.stdout or ""


def _assert_site_agrees(site: str, version: str, expected: str) -> None:
    """Fail the contract when one site names a version other than ``expected``."""
    assert same_version(version, expected), (
        f"{site} names cuprum {version}, but pyproject.toml pins {expected}"
    )


def test_every_site_declares_the_same_exact_cuprum_pin() -> None:
    """Hold the manifest, both halves of the lock, and the venv to one version.

    The expected value comes from ``pyproject.toml``, so this asserts alignment
    rather than a particular release. Each assertion names the site that
    disagreed, because the failure mode being guarded against is a partial bump
    rather than a wholesale one.
    """
    expected = declared_pin(PYPROJECT.read_text(encoding="utf-8"))
    lock = LOCKFILE.read_text(encoding="utf-8")

    _assert_site_agrees("uv.lock's resolved cuprum package", lock_pin(lock), expected)
    _assert_site_agrees(
        "uv.lock's recorded requirement", lock_specifier(lock), expected
    )
    _assert_site_agrees(
        "the test interpreter's installed cuprum", installed_version(), expected
    )


def test_the_manifest_pins_rather_than_ranges() -> None:
    """A range would admit the next beta, which the suite has not exercised.

    The version is not restated here; :func:`declared_pin` reads it from the
    manifest and refuses anything but one exact ``==``.
    """
    declared_pin(PYPROJECT.read_text(encoding="utf-8"))


@pytest.mark.skipif(
    UV_BINARY is None or GIT_BINARY is None,
    reason="the lock check needs both uv and git on PATH",
)
@pytest.mark.skipif(
    not (ROOT / ".git").exists(),
    reason=_NO_GIT_CHECKOUT,
)
def test_the_project_lock_is_fresh_as_committed(tmp_path: pth.Path) -> None:
    """``uv.lock`` matches ``pyproject.toml`` as committed, not as rebuilt.

    The pair is written into a scratch directory and resolved there with
    ``--check``, which never writes. That is what keeps the assertion from
    being vacuous: reading the working tree would observe a lock that ``make
    build`` had already repaired.
    """
    (tmp_path / PYPROJECT.name).write_text(_committed(PYPROJECT), encoding="utf-8")
    (tmp_path / LOCKFILE.name).write_text(_committed(LOCKFILE), encoding="utf-8")

    outcome = run_command(
        [typ.cast("str", UV_BINARY), "lock", "--check"],
        cwd=tmp_path,
        timeout=_LOCK_TIMEOUT_SECONDS,
    )

    assert outcome.exit_code == 0, (
        "uv.lock is stale as committed; run 'uv lock'. uv said:\n"
        f"{outcome.stdout}{outcome.stderr}"
    )
