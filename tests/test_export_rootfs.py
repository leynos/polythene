"""Tests for the image acquisition contract in :func:`polythene.export_rootfs`."""

from __future__ import annotations

import subprocess
import typing as typ

import pytest
from plumbum.commands.processes import ProcessExecutionError

import polythene.isolation as isolation
from tests.support.podman import RecordingTools, install_recording_tools

if typ.TYPE_CHECKING:
    from pathlib import Path

IMAGE = "localhost/example:latest"
CONTAINER_ID = "0123456789abcdef"

# Only ``podman pull`` and ``podman rm`` write to stdout, so those two calls
# take the sink that keeps ``polythene pull`` down to the UUID line. Every
# other call inherits the caller's streams.
STDOUT_SINK = {"stdout": subprocess.DEVNULL}
PULL_FAILURE = ProcessExecutionError(
    ["/usr/bin/podman", "pull", IMAGE],
    125,
    "",
    "pinging container registry localhost: connection refused",
)


def _run_export(
    tmp_path: Path,
    *,
    image: str = IMAGE,
    timeout: int | None = None,
) -> Path:
    """Run ``export_rootfs`` against the recording doubles and return ``dest``."""
    dest = tmp_path / "rootfs"
    isolation.export_rootfs(image, dest, timeout=timeout)
    return dest


def _script_create(tools: RecordingTools) -> None:
    """Make ``podman create`` report ``CONTAINER_ID``."""
    tools.podman.script("create", outcome=(0, f"{CONTAINER_ID}\n", ""))


def test_export_rootfs_reuses_existing_local_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A locally present image is exported without contacting a registry."""
    tools = install_recording_tools(monkeypatch)
    tools.podman.script("image", "exists", outcome=(0, "", ""))
    _script_create(tools)

    dest = _run_export(tmp_path)

    assert tools.requested == ["podman", "tar"]
    # No global --storage-driver or --events-backend flags are added.
    assert [record.argv for record in tools.podman.calls] == [
        ("podman", "image", "exists", IMAGE),
        ("podman", "create", "--pull=never", IMAGE, "true"),
        (
            "podman",
            "export",
            CONTAINER_ID,
            "|",
            "tar",
            "-C",
            str(dest),
            "-x",
        ),
        ("podman", "rm", CONTAINER_ID),
    ]
    assert [record.run_kwargs for record in tools.podman.calls] == [
        {"retcode": None},
        {},
        {},
        STDOUT_SINK,
    ]
    assert tools.podman.find("image", "exists")[0].argv == (
        "podman",
        "image",
        "exists",
        IMAGE,
    )
    create = tools.podman.find("create")[0]
    assert create.argv == ("podman", "create", "--pull=never", IMAGE, "true")
    assert create.fg is False
    assert create.run_kwargs == {}
    assert create.timeout is None
    rm = tools.podman.find("rm")[0]
    assert rm.argv == ("podman", "rm", CONTAINER_ID)
    assert rm.run_kwargs == STDOUT_SINK
    assert dest.is_dir()
    assert "pull" not in capsys.readouterr().err


def test_export_rootfs_pulls_when_image_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An absent image keeps the existing pull-before-create behaviour."""
    tools = install_recording_tools(monkeypatch)
    tools.podman.script("image", "exists", outcome=(1, "", ""))
    tools.podman.script("pull", outcome=(0, "", ""))
    _script_create(tools)

    dest = _run_export(tmp_path)

    assert [record.argv for record in tools.podman.calls] == [
        ("podman", "image", "exists", IMAGE),
        ("podman", "pull", IMAGE),
        ("podman", "create", "--pull=never", IMAGE, "true"),
        (
            "podman",
            "export",
            CONTAINER_ID,
            "|",
            "tar",
            "-C",
            str(dest),
            "-x",
        ),
        ("podman", "rm", CONTAINER_ID),
    ]
    assert [record.run_kwargs for record in tools.podman.calls] == [
        {"retcode": None},
        STDOUT_SINK,
        {},
        {},
        STDOUT_SINK,
    ]
    pull = tools.podman.find("pull")[0]
    assert pull.argv == ("podman", "pull", IMAGE)
    assert pull.fg is True
    assert pull.run_kwargs == STDOUT_SINK
    assert tools.podman.find("rm")[0].run_kwargs == STDOUT_SINK
    assert dest.is_dir()


def test_export_rootfs_reports_storage_failure_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A storage error from the probe is fatal and leaves nothing behind."""
    tools = install_recording_tools(monkeypatch)
    tools.podman.script("image", "exists", outcome=(125, "", "no storage"))
    _script_create(tools)

    with pytest.raises(SystemExit) as excinfo:
        _run_export(tmp_path)

    assert excinfo.value.code == 125
    assert "Failed to check for local image" in capsys.readouterr().err
    assert [record.argv[1] for record in tools.podman.calls] == ["image"]
    assert not (tmp_path / "rootfs").exists()


def test_export_rootfs_reports_unexpected_probe_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unexpected probe statuses surface rather than reading as absence."""
    tools = install_recording_tools(monkeypatch)
    tools.podman.script("image", "exists", outcome=(2, "", "usage error"))

    with pytest.raises(SystemExit) as excinfo:
        _run_export(tmp_path)

    assert excinfo.value.code == 2
    assert "Failed to check for local image" in capsys.readouterr().err
    assert [record.argv[1] for record in tools.podman.calls] == ["image"]


def test_export_rootfs_preserves_pull_failure_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed pull after an absent verdict keeps its message and exit code."""
    tools = install_recording_tools(monkeypatch)
    tools.podman.script("image", "exists", outcome=(1, "", ""))
    tools.podman.script("pull", outcome=PULL_FAILURE)
    _script_create(tools)

    with pytest.raises(SystemExit) as excinfo:
        _run_export(tmp_path)

    assert excinfo.value.code == 125
    assert f"Failed to pull image {IMAGE}" in capsys.readouterr().err
    assert tools.podman.find("create") == []


def test_export_rootfs_forwards_timeout_to_every_podman_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The caller's timeout reaches the probe, pull, create, export, and rm."""
    tools = install_recording_tools(monkeypatch)
    tools.podman.script("image", "exists", outcome=(0, "", ""))
    _script_create(tools)

    _run_export(tmp_path, timeout=30)

    assert [record.argv[1] for record in tools.podman.calls] == [
        "image",
        "create",
        "export",
        "rm",
    ]
    assert [record.timeout for record in tools.podman.calls] == [30, 30, 30, 30]
    assert tools.podman.find("image", "exists")[0].run_kwargs == {"retcode": None}


def test_export_rootfs_silences_pull_and_rm_stdout_with_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The pull path keeps the stdout sink when a timeout is supplied."""
    tools = install_recording_tools(monkeypatch)
    tools.podman.script("image", "exists", outcome=(1, "", ""))
    tools.podman.script("pull", outcome=(0, "", ""))
    _script_create(tools)

    _run_export(tmp_path, timeout=30)

    assert [record.argv[1] for record in tools.podman.calls] == [
        "image",
        "pull",
        "create",
        "export",
        "rm",
    ]
    assert [record.timeout for record in tools.podman.calls] == [30, 30, 30, 30, 30]
    assert tools.podman.find("pull")[0].run_kwargs == STDOUT_SINK
    assert tools.podman.find("rm")[0].run_kwargs == STDOUT_SINK


def test_export_rootfs_uses_one_podman_command_for_probe_and_create(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Both steps resolve identically, so they share the caller's store."""
    tools = install_recording_tools(monkeypatch)
    tools.podman.script("image", "exists", outcome=(0, "", ""))
    _script_create(tools)

    _run_export(tmp_path)

    assert tools.requested == ["podman", "tar"]
    probe = tools.podman.find("image", "exists")[0]
    create = tools.podman.find("create")[0]
    assert probe.argv[0] == create.argv[0] == tools.podman.binary
