"""Behavioural tests for the CLI using pytest-bdd."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Callable, Sequence

import pytest
from conftest import CliResult
from pytest_bdd import given, parsers, scenarios, then, when

import polythene

scenarios("../features/polythene_cli.feature")


@pytest.fixture()
def cli_context() -> dict[str, object]:
    return {}


@given("a clean store directory")
def clean_store(tmp_path: Path, cli_context: dict[str, object]) -> Path:
    cli_context["store"] = tmp_path
    return tmp_path


@given(parsers.parse('UUID generation returns "{value}"'))
def stub_uuid(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(polythene, "generate_uuid", lambda: value)


@given("image export succeeds")
def stub_export(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(image: str, dest: Path, *, timeout: int | None = None) -> None:
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(polythene, "export_rootfs", _fake)


@when(parsers.parse('I run the CLI with arguments "{raw}"'))
def run_cli_command(
    raw: str,
    run_cli: Callable[[Sequence[str]], CliResult],
    cli_context: dict[str, object],
) -> None:
    store = Path(cli_context["store"])
    formatted = raw.format(store=store.as_posix())
    args = shlex.split(formatted)
    cli_context["result"] = run_cli(args)


@when(parsers.parse('I run the module CLI with arguments "{raw}"'))
def run_module_cli_command(
    raw: str,
    run_module_cli: Callable[[Sequence[str]], CliResult],
    cli_context: dict[str, object],
) -> None:
    store = Path(cli_context["store"])
    formatted = raw.format(store=store.as_posix())
    args = shlex.split(formatted)
    cli_context["result"] = run_module_cli(args)


@then(parsers.parse("the CLI exits with code {code:d}"))
def assert_exit(cli_context: dict[str, object], code: int) -> None:
    result = cli_context["result"]
    assert isinstance(result, CliResult)
    assert result.exit_code == code


@then(parsers.parse('stdout equals "{value}"'))
def assert_stdout(cli_context: dict[str, object], value: str) -> None:
    result = cli_context["result"]
    assert isinstance(result, CliResult)
    assert result.stdout.strip() == value


@then(parsers.parse('stderr contains "{value}"'))
def assert_stderr_contains(cli_context: dict[str, object], value: str) -> None:
    result = cli_context["result"]
    assert isinstance(result, CliResult)
    assert value in result.stderr


@then(parsers.parse('the rootfs directory "{uuid}" exists'))
def assert_rootfs_exists(cli_context: dict[str, object], uuid: str) -> None:
    store = Path(cli_context["store"])
    assert (store / uuid).is_dir()
