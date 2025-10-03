"""Behaviour-driven tests covering the Polythene CLI interface."""

from __future__ import annotations

import shlex
import typing as typ
from pathlib import Path

import pytest
from conftest import CliResult
from pytest_bdd import given, parsers, scenarios, then, when

import polythene.isolation as isolation

Context = dict[str, object]

scenarios("../features/polythene_cli.feature")


@pytest.fixture
def cli_context() -> Context:
    """Provide a mutable context shared across step implementations."""
    return {}


@given("a clean store directory")
def clean_store(tmp_path: Path, cli_context: Context) -> Path:
    """Record the temporary directory used to store exported rootfs trees."""
    cli_context["store"] = tmp_path
    return tmp_path


@given(parsers.parse('UUID generation returns "{value}"'))
def stub_uuid(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Force the CLI to generate a predictable UUID."""
    monkeypatch.setattr(isolation, "generate_uuid", lambda: value)


@given("image export succeeds")
def stub_export(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``export_rootfs`` to create the destination without error."""

    def _fake(image: str, dest: Path, *, timeout: int | None = None) -> None:
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(isolation, "export_rootfs", _fake)


@when(parsers.parse('I run the CLI with arguments "{raw}"'))
def run_cli_command(
    raw: str,
    run_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    cli_context: Context,
) -> None:
    """Invoke the CLI fixture with the formatted arguments."""
    store = Path(cli_context["store"])
    formatted = raw.format(store=store.as_posix())
    args = shlex.split(formatted)
    cli_context["result"] = run_cli(args)


@when(parsers.parse('I run the module CLI with arguments "{raw}"'))
def run_module_cli_command(
    raw: str,
    run_module_cli: typ.Callable[[typ.Sequence[str]], CliResult],
    cli_context: Context,
) -> None:
    """Invoke ``python -m polythene`` via the fixture with formatted args."""
    store = Path(cli_context["store"])
    formatted = raw.format(store=store.as_posix())
    args = shlex.split(formatted)
    cli_context["result"] = run_module_cli(args)


@then(parsers.parse("the CLI exits with code {code:d}"))
def assert_exit(cli_context: Context, code: int) -> None:
    """Assert that the recorded result exited with the requested code."""
    result = cli_context["result"]
    assert isinstance(result, CliResult)
    assert result.exit_code == code


@then(parsers.parse('stdout equals "{value}"'))
def assert_stdout(cli_context: Context, value: str) -> None:
    """Assert that stdout matches ``value`` exactly."""
    result = cli_context["result"]
    assert isinstance(result, CliResult)
    assert result.stdout.strip() == value


@then(parsers.parse('stderr contains "{value}"'))
def assert_stderr_contains(cli_context: Context, value: str) -> None:
    """Assert that stderr includes ``value`` somewhere in its output."""
    result = cli_context["result"]
    assert isinstance(result, CliResult)
    assert value in result.stderr


@then(parsers.parse('the rootfs directory "{uuid}" exists'))
def assert_rootfs_exists(cli_context: Context, uuid: str) -> None:
    """Ensure the exported rootfs folder exists on disk."""
    store = Path(cli_context["store"])
    assert (store / uuid).is_dir()
