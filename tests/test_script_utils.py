"""Unit tests for :mod:`polythene.script_utils`."""

from __future__ import annotations

import typing as typ

import pytest
from cuprum import SafeCmd

from polythene import script_utils

if typ.TYPE_CHECKING:
    from pathlib import Path


def test_get_command_returns_a_builder_for_an_installed_tool() -> None:
    """A curated tool on ``PATH`` comes back as a builder for real commands."""
    command = script_utils.get_command("tar")("-tf", "archive.tar")

    assert isinstance(command, SafeCmd)
    assert command.argv_with_program == ("tar", "-tf", "archive.tar")


def test_get_command_exits_127_when_the_tool_is_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing binary keeps the documented exit status and diagnostic.

    Cuprum resolves an executable when the command runs, so without the check
    the failure would surface as a traceback from inside a probe instead of
    the CLI's own one-line message.
    """
    with pytest.raises(SystemExit) as excinfo:
        script_utils.get_command("polythene-definitely-not-installed")

    assert excinfo.value.code == 127
    assert (
        "Required command not found: polythene-definitely-not-installed"
        in capsys.readouterr().err
    )


def test_get_command_rejects_a_program_the_catalogue_does_not_curate() -> None:
    """``PATH`` is not the only gate; the catalogue must admit the name too."""
    from cuprum import UnknownProgramError

    with pytest.raises(UnknownProgramError, match="not in the catalogue"):
        script_utils.get_command("cat")


def test_ensure_directory_creates_path(tmp_path: Path) -> None:
    """``ensure_directory`` creates nested directories when needed."""
    target = tmp_path / "nested" / "dir"
    script_utils.ensure_directory(target)
    assert target.exists()


def test_ensure_exists_passes_when_present(tmp_path: Path) -> None:
    """``ensure_exists`` returns when the path already exists."""
    file_path = tmp_path / "file.txt"
    file_path.write_text("ok", encoding="utf-8")
    script_utils.ensure_exists(file_path, "file")


def test_ensure_exists_exits_when_missing(tmp_path: Path) -> None:
    """``ensure_exists`` exits with code 2 when the path is missing."""
    with pytest.raises(SystemExit) as excinfo:
        script_utils.ensure_exists(tmp_path / "missing", "missing file")
    assert isinstance(excinfo.value, SystemExit)
    assert excinfo.value.code == 2


def test_unique_match_returns_single_path(tmp_path: Path) -> None:
    """``unique_match`` returns the only matching path."""
    file_path = tmp_path / "only.txt"
    file_path.touch()
    result = script_utils.unique_match([file_path], description="file")
    assert result == file_path


def test_unique_match_errors_on_multiple(tmp_path: Path) -> None:
    """``unique_match`` exits when multiple matches are provided."""
    files = [tmp_path / name for name in ("a", "b")]
    for path in files:
        path.touch()
    with pytest.raises(SystemExit) as excinfo:
        script_utils.unique_match(files, description="file")
    assert isinstance(excinfo.value, SystemExit)
    assert excinfo.value.code == 2
