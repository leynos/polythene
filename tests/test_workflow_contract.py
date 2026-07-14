"""Contract tests for the mutation-testing caller workflow.

The executable logic lives in the ``leynos/shared-actions`` reusable
workflow, which carries its own unit and integration tests; polythene's
caller is declarative configuration. These tests parse the caller with
PyYAML and assert that it references the correct reusable workflow at a
commit SHA, so drift (repointing the pin at a branch, widening
permissions, or losing the flat-layout configuration) fails CI on the
pull request rather than surfacing in a scheduled or manual run.
Dependabot owns the pinned SHA value; these tests only pin its shape.
"""

from __future__ import annotations

import re
import typing as typ
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "mutation-testing.yml"
)

pytestmark = pytest.mark.skipif(
    not WORKFLOW_PATH.exists(),
    reason=(
        "workflow file not present in this working copy (for example "
        "inside mutmut's mutants/ sandbox, which does not copy .github/)"
    ),
)

USES_RE = re.compile(
    r"^leynos/shared-actions/\.github/workflows/mutation-mutmut\.yml@[0-9a-f]{40}$"
)

EXPECTED_WITH = {
    "paths": "polythene/",
    "module-prefix-strip": "",
}


def _as_mapping(value: object, message: str) -> dict[str, object]:
    """Assert ``value`` is a mapping and narrow its type."""
    assert isinstance(value, dict), message
    return typ.cast("dict[str, object]", value)


def _load() -> dict[str, object]:
    """Parse the workflow file."""
    return _as_mapping(
        yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8")),
        "the workflow must be a YAML mapping",
    )


def _triggers(workflow: dict[str, object]) -> dict[str, object]:
    """Return the ``on:`` mapping (PyYAML parses the bare key as True)."""
    raw = typ.cast("dict[object, object]", workflow)
    return _as_mapping(
        raw.get("on", raw.get(True)),
        "the workflow must declare an on: mapping",
    )


def _mutation_job(workflow: dict[str, object]) -> dict[str, object]:
    """Return the single calling job."""
    jobs = _as_mapping(workflow.get("jobs"), "the workflow must declare a jobs mapping")
    assert jobs, "the workflow must declare at least one job"
    assert list(jobs) == ["mutation"], (
        f"expected a single job named 'mutation', found {sorted(jobs)}"
    )
    return _as_mapping(jobs["mutation"], "jobs.mutation must be a mapping")


def test_uses_reference_is_pinned_to_a_commit_sha() -> None:
    """The job must reference the correct path, pinned to a commit SHA.

    The ref must be a full commit SHA, not a mutable branch or tag.
    Dependabot owns the exact SHA value, so it is not asserted here.
    """
    uses = _mutation_job(_load()).get("uses")
    assert isinstance(uses, str), "jobs.mutation.uses is missing"
    assert USES_RE.match(uses), (
        "jobs.mutation.uses must reference "
        "leynos/shared-actions/.github/workflows/mutation-mutmut.yml "
        f"pinned to a full 40-character lowercase hex commit SHA, got {uses!r}"
    )


def test_job_permissions_are_exactly_least_privilege() -> None:
    """The job grants contents: read and id-token: write, nothing broader."""
    permissions = _mutation_job(_load()).get("permissions")
    assert permissions == {"contents": "read", "id-token": "write"}, (
        "jobs.mutation.permissions must be exactly "
        f"{{'contents': 'read', 'id-token': 'write'}}, got {permissions!r}"
    )


def test_workflow_default_permissions_are_empty() -> None:
    """The workflow-level default token scope is empty."""
    workflow = _load()
    assert workflow.get("permissions") == {}, (
        f"top-level permissions must be an empty mapping, got "
        f"{workflow.get('permissions')!r}"
    )


def test_concurrency_serializes_per_ref_without_cancelling() -> None:
    """Runs queue per ref instead of cancelling one another."""
    concurrency = _as_mapping(
        _load().get("concurrency"), "the workflow must declare concurrency"
    )
    assert concurrency.get("group") == "mutation-testing-${{ github.ref }}", (
        f"concurrency.group must key on the triggering ref, got "
        f"{concurrency.get('group')!r}"
    )
    assert concurrency.get("cancel-in-progress") is False, (
        f"concurrency.cancel-in-progress must be false, got "
        f"{concurrency.get('cancel-in-progress')!r}"
    )


def test_triggers_keep_schedule_and_plain_dispatch() -> None:
    """The daily schedule stays; dispatch declares no inputs."""
    triggers = _triggers(_load())
    schedule = triggers.get("schedule")
    assert schedule == [{"cron": "50 5 * * *"}], (
        f"on.schedule must be the daily 05:50 UTC cron, got {schedule!r}"
    )
    assert "workflow_dispatch" in triggers, "on.workflow_dispatch is missing"
    dispatch = _as_mapping(
        triggers.get("workflow_dispatch") or {},
        "on.workflow_dispatch must be a mapping",
    )
    inputs = dispatch.get("inputs") or {}
    assert not inputs, (
        "on.workflow_dispatch must not declare inputs; the Actions "
        "run-workflow control selects the ref"
    )


def test_with_block_carries_the_flat_layout_configuration() -> None:
    """The caller sets flat-layout paths and nothing else."""
    with_block = _mutation_job(_load()).get("with")
    assert with_block == EXPECTED_WITH, (
        f"jobs.mutation.with must be exactly {EXPECTED_WITH!r}, got {with_block!r}"
    )
