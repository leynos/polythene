"""Contract tests for main-owned CodeScene coverage publication."""

from __future__ import annotations

import typing as typ
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
MAIN_COVERAGE_WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "coverage-main.yml"
)
GENERATE_COVERAGE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage"
UPLOAD_CODESCENE_ACTION = (
    "leynos/shared-actions/.github/actions/upload-codescene-coverage"
)


def _load_workflow(path: Path) -> dict[str, object]:
    """Return one workflow after normalising PyYAML's YAML 1.1 ``on`` key."""
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), f"{path} must contain a mapping"
    if True in workflow:
        workflow["on"] = workflow.pop(True)
    return typ.cast("dict[str, object]", workflow)


def _job(workflow: dict[str, object], name: str) -> dict[str, object]:
    """Return a named workflow job after validating its mapping shape."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must declare a jobs mapping"
    jobs_by_name = typ.cast("dict[str, object]", jobs)
    job = jobs_by_name.get(name)
    assert isinstance(job, dict), f"workflow must declare the {name!r} job"
    return typ.cast("dict[str, object]", job)


def _step(job: dict[str, object], name: str) -> dict[str, object]:
    """Return a named job step after validating its list and mapping shape."""
    steps = job.get("steps")
    assert isinstance(steps, list), "job must declare a steps list"
    step = next(
        (
            typ.cast("dict[str, object]", candidate)
            for candidate in steps
            if isinstance(candidate, dict)
            and typ.cast("dict[str, object]", candidate).get("name") == name
        ),
        None,
    )
    assert isinstance(step, dict), f"job must declare a {name!r} step"
    return step


def _uses(step: dict[str, object]) -> str:
    """Return a step's action reference after validating its scalar shape."""
    uses = step.get("uses")
    assert isinstance(uses, str), f"step uses must be a string, got {uses!r}"
    return uses


def test_pull_request_coverage_uses_only_the_local_ratchet() -> None:
    """Keep pull-request coverage local and independent of CodeScene."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    triggers = workflow.get("on")
    assert isinstance(triggers, dict), "ci.yml must declare a trigger mapping"
    assert "pull_request" in triggers, "ci.yml must run on pull requests"

    workflow_environment = workflow.get("env", {})
    assert isinstance(workflow_environment, dict), "ci.yml env must be a mapping"
    assert "CS_ACCESS_TOKEN" not in workflow_environment, (
        "ci.yml workflow env must not expose CS_ACCESS_TOKEN"
    )
    assert "CODESCENE_CLI_SHA256" not in workflow_environment, (
        "ci.yml workflow env must not expose the CodeScene CLI hash"
    )

    lint_test = _job(workflow, "lint-test")
    job_environment = lint_test.get("env", {})
    assert isinstance(job_environment, dict), "lint-test.env must be a mapping"
    assert "CS_ACCESS_TOKEN" not in job_environment, (
        "lint-test job env must not expose CS_ACCESS_TOKEN"
    )
    assert "CODESCENE_CLI_SHA256" not in job_environment, (
        "lint-test job env must not expose the CodeScene CLI hash"
    )

    checkout = _step(lint_test, "Check out repository")
    checkout_inputs = checkout.get("with", {})
    assert isinstance(checkout_inputs, dict), "checkout.with must be a mapping"
    checkout_inputs = typ.cast("dict[str, object]", checkout_inputs)
    assert checkout_inputs.get("fetch-depth") not in {0, "0"}, (
        "pull-request checkout must not request full history"
    )

    coverage = _step(lint_test, "Generate coverage")
    coverage_condition = coverage.get("if")
    assert isinstance(coverage_condition, str), "coverage step must be conditional"
    assert "github.event_name == 'pull_request'" in coverage_condition, (
        "coverage generation must be limited to pull requests"
    )
    assert _uses(coverage).startswith(GENERATE_COVERAGE_ACTION), (
        "pull-request coverage must use the shared generate-coverage action"
    )
    coverage_inputs = coverage.get("with")
    assert isinstance(coverage_inputs, dict), "coverage.with must be a mapping"
    coverage_inputs = typ.cast("dict[str, object]", coverage_inputs)
    assert coverage_inputs.get("language") == "python", (
        "pull-request coverage must select Python explicitly"
    )
    assert coverage_inputs.get("python-source") == "./polythene", (
        "pull-request coverage must measure the polythene package"
    )
    assert coverage_inputs.get("pytest-workers") == "", (
        "pull-request coverage must run pytest serially"
    )
    assert coverage_inputs.get("with-ratchet") == "true", (
        "pull-request coverage must enable the local ratchet"
    )

    steps = lint_test.get("steps")
    assert isinstance(steps, list), "lint-test must declare a steps list"
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_mapping = typ.cast("dict[str, object]", step)
        uses = step_mapping.get("uses")
        if isinstance(uses, str):
            assert UPLOAD_CODESCENE_ACTION not in uses, (
                "pull-request jobs must not upload to CodeScene"
            )
        environment = step_mapping.get("env", {})
        if isinstance(environment, dict):
            assert "CS_ACCESS_TOKEN" not in environment, (
                "pull-request steps must not expose CS_ACCESS_TOKEN"
            )
        run = step_mapping.get("run", "")
        if isinstance(run, str):
            assert "cs-coverage" not in run, (
                "pull-request steps must not run the CodeScene CLI"
            )
    assert "codescene.io" not in CI_WORKFLOW_PATH.read_text(encoding="utf-8"), (
        "pull-request workflow must not reference CodeScene"
    )


def test_main_coverage_writes_the_ratchet_and_uploads() -> None:
    """Keep publication on main pushes and select explicit upload mode."""
    workflow = _load_workflow(MAIN_COVERAGE_WORKFLOW_PATH)
    assert workflow.get("on") == {
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    }, "coverage-main.yml must run on main pushes and manual dispatch"

    coverage_upload = _job(workflow, "coverage-upload")
    coverage = _step(coverage_upload, "Generate coverage")
    assert _uses(coverage).startswith(GENERATE_COVERAGE_ACTION), (
        "main coverage must use the shared generate-coverage action"
    )
    coverage_inputs = coverage.get("with")
    assert isinstance(coverage_inputs, dict), "coverage.with must be a mapping"
    coverage_inputs = typ.cast("dict[str, object]", coverage_inputs)
    assert coverage_inputs.get("language") == "python", (
        "main coverage must select Python explicitly"
    )
    assert coverage_inputs.get("python-source") == "./polythene", (
        "main coverage must measure the polythene package"
    )
    assert coverage_inputs.get("pytest-workers") == "", (
        "main coverage must run pytest serially"
    )
    assert coverage_inputs.get("with-ratchet") == "true", (
        "main coverage must enable the ratchet"
    )

    upload = _step(coverage_upload, "Upload coverage data to CodeScene")
    assert _uses(upload).startswith(UPLOAD_CODESCENE_ACTION), (
        "main coverage must use the shared CodeScene upload action"
    )
    upload_inputs = upload.get("with")
    assert isinstance(upload_inputs, dict), "upload.with must be a mapping"
    upload_inputs = typ.cast("dict[str, object]", upload_inputs)
    assert upload_inputs.get("mode") == "upload", (
        "main coverage upload must use upload mode"
    )
