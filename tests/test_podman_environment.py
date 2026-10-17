"""Regression tests for Podman environment inherited by Polythene."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from plumbum import local

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_IMPORT_SCRIPT = """
import json
import os
import sys

names = (
    "CONTAINERS_STORAGE_DRIVER",
    "CONTAINERS_EVENTS_BACKEND",
    "STORAGE_DRIVER",
)
for name in names:
    os.environ.pop(name, None)
for name, value in json.loads(sys.argv[1]).items():
    os.environ[name] = value

before = {name: os.environ.get(name) for name in names}
import polythene.isolation
after = {name: os.environ.get(name) for name in names}
print(json.dumps({"before": before, "after": after}))
"""


@pytest.mark.parametrize(
    ("caller_values", "expected_values"),
    [
        pytest.param(
            {},
            {
                "CONTAINERS_STORAGE_DRIVER": None,
                "CONTAINERS_EVENTS_BACKEND": None,
                "STORAGE_DRIVER": None,
            },
            id="variables-unset",
        ),
        pytest.param(
            {
                "CONTAINERS_STORAGE_DRIVER": "caller-storage-value",
                "CONTAINERS_EVENTS_BACKEND": "caller-events-value",
            },
            {
                "CONTAINERS_STORAGE_DRIVER": "caller-storage-value",
                "CONTAINERS_EVENTS_BACKEND": "caller-events-value",
                "STORAGE_DRIVER": None,
            },
            id="caller-values-preserved",
        ),
    ],
)
def test_import_preserves_podman_environment(
    caller_values: dict[str, str],
    expected_values: dict[str, str | None],
) -> None:
    """Importing isolation leaves caller Podman settings unchanged."""
    with local.cwd(REPOSITORY_ROOT):
        exit_code, stdout, stderr = local[sys.executable][
            "-c", ENVIRONMENT_IMPORT_SCRIPT, json.dumps(caller_values)
        ].run(retcode=None, timeout=10)

    assert exit_code == 0, f"fresh interpreter failed: {stderr}"
    assert json.loads(stdout) == {
        "before": expected_values,
        "after": expected_values,
    }
