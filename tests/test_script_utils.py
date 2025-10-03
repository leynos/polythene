"""Unit tests for :mod:`polythene.script_utils`."""

from __future__ import annotations

from pathlib import Path

import pytest

from polythene import script_utils


def test_ensure_directory_creates_path(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir"
    script_utils.ensure_directory(target)
    assert target.exists()


def test_ensure_exists_passes_when_present(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("ok", encoding="utf-8")
    script_utils.ensure_exists(file_path, "file")


def test_ensure_exists_exits_when_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        script_utils.ensure_exists(tmp_path / "missing", "missing file")
    assert isinstance(excinfo.value, SystemExit)
    assert excinfo.value.code == 2


def test_unique_match_returns_single_path(tmp_path: Path) -> None:
    file_path = tmp_path / "only.txt"
    file_path.touch()
    result = script_utils.unique_match([file_path], description="file")
    assert result == file_path


def test_unique_match_errors_on_multiple(tmp_path: Path) -> None:
    files = [tmp_path / name for name in ("a", "b")]
    for path in files:
        path.touch()
    with pytest.raises(SystemExit) as excinfo:
        script_utils.unique_match(files, description="file")
    assert isinstance(excinfo.value, SystemExit)
    assert excinfo.value.code == 2
