"""Exercise CI's source-distribution count check.

The release publishes whichever single ``.tar.gz`` sits beside the pure wheel,
so a pull request whose build produced none or two must fail there rather than
at tag time. This runs the checked-in glob-count step against zero, one, and
two candidate files, and holds the composite action to building both rather
than the wheel alone.
"""

from __future__ import annotations

import sys
import typing as typ

import pytest

from tests.helpers.ci_workflows import ROOT
from tests.helpers.release_workflow import run_bash, step_script

if typ.TYPE_CHECKING:
    from pathlib import Path

WORKFLOW = "ci.yml"
JOB = "wheel-build"
STEP = "Require exactly one sdist to travel with the wheel"
ACTION = ROOT / ".github" / "actions" / "pure-python-wheel" / "action.yml"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The CI workflow's steps run under Bash on Linux.",
)


def _run_with_sdist_count(tmp_path: Path, count: int) -> tuple[int, str]:
    """Run the step with one pure wheel and ``count`` source distributions."""
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir(parents=True)
    (wheel_dir / "polythene_isolate-1.0-py3-none-any.whl").touch()
    for index in range(count):
        (wheel_dir / f"polythene_isolate-1.0-{index}.tar.gz").touch()
    result = run_bash(
        step_script(JOB, STEP, workflow=WORKFLOW),
        tmp_path,
        {"WHEEL_DIR": "dist"},
    )
    return result.returncode, result.stderr


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "fail"), (1, "pass"), (2, "fail")],
    ids=["no-sdist", "one-sdist", "two-sdists"],
)
def test_the_sdist_count_is_exactly_one(
    tmp_path: Path, count: int, expected: str
) -> None:
    """No sdist and two sdists are as wrong as each other; one alone passes."""
    returncode, stderr = _run_with_sdist_count(tmp_path, count)

    if expected == "pass":
        assert returncode == 0, stderr
        return
    assert returncode != 0, f"{count} sdists must fail the step, got {stderr!r}"
    assert "Expected exactly one source distribution." in stderr, (
        f"missing the expected diagnostic, got {stderr!r}"
    )


def test_the_wheel_count_is_also_exactly_one(tmp_path: Path) -> None:
    """A build that produced no wheel must fail rather than pass vacuously."""
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "polythene_isolate-1.0.tar.gz").touch()

    completed = run_bash(
        step_script(JOB, STEP, workflow=WORKFLOW),
        tmp_path,
        {"WHEEL_DIR": "dist"},
    )

    assert completed.returncode != 0
    assert "Expected exactly one pure Python wheel." in completed.stderr


def test_the_composite_action_builds_the_sdist_and_the_wheel() -> None:
    """A plain ``uv build`` builds the sdist first, then the wheel from it."""
    action = ACTION.read_text(encoding="utf-8")
    build = next(
        line.strip()
        for line in action.splitlines()
        if line.strip().startswith("uv build")
    )

    assert build == "uv build --out-dir dist", (
        "asking for one artefact would skip the proof that the sdist builds"
    )
    assert "*.tar.gz" in action, "the sdist must be uploaded with the wheel"
