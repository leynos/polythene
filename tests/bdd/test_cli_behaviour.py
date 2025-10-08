"""Behaviour-driven tests covering the Polythene CLI interface."""

from __future__ import annotations

import shlex
import typing as typ
from pathlib import Path

import pytest
from conftest import CliResult
from pytest_bdd import given, parsers, scenarios, then, when

import polythene.backends as backend_module
import polythene.isolation as isolation

Context = dict[str, object]

scenarios("../features/polythene_cli.feature")


class _RecordingCommand:
    """Capture proot invocations to assert shell arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __getitem__(self, args: tuple[str, ...]) -> tuple[str, ...]:
        self.calls.append(args)
        return args


@pytest.fixture
def cli_context() -> Context:
    """Provide a mutable context shared across step implementations."""
    return {}


@given("a clean store directory")
def clean_store(tmp_path: Path, cli_context: Context) -> Path:
    """Record the temporary directory used to store exported rootfs trees."""
    cli_context["store"] = tmp_path
    return tmp_path


@given(parsers.parse('the rootfs "{uuid}" exists'))
def ensure_rootfs(cli_context: Context, uuid: str) -> None:
    """Create a rootfs directory for ``uuid`` inside the store."""
    store = Path(cli_context["store"])
    (store / uuid).mkdir(parents=True, exist_ok=True)


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


@given("proot execution is stubbed")
def stub_proot(monkeypatch: pytest.MonkeyPatch, cli_context: Context) -> None:
    """Limit execution to proot and record its invocations."""
    proot_backend = next(
        backend
        for backend in backend_module.create_backends()
        if backend.name == "proot"
    )
    stub = _RecordingCommand()
    executions: list[tuple[str, ...]] = []

    def fake_get_command(binary: str) -> _RecordingCommand:
        assert binary == proot_backend.binary
        return stub

    def fake_run_cmd(cmd: tuple[str, ...], *, fg: bool, timeout: int | None) -> int:
        executions.append(cmd)
        return 0

    monkeypatch.setattr(isolation, "BACKENDS", (proot_backend,))
    monkeypatch.setattr(backend_module, "get_command", fake_get_command)
    monkeypatch.setattr(backend_module, "run_cmd", fake_run_cmd)
    cli_context["proot_stub"] = stub
    cli_context["proot_executions"] = executions


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


@then("proot ran without requesting a login shell")
def assert_proot_non_login(cli_context: Context) -> None:
    """Verify that the stubbed proot invocation avoids ``-lc``."""
    stub = cli_context.get("proot_stub")
    executions = cli_context.get("proot_executions")
    assert isinstance(stub, _RecordingCommand)
    assert isinstance(executions, list)
    assert stub.calls == executions
    assert len(stub.calls) == 2
    probe_call, exec_call = stub.calls
    assert probe_call[-2:] == ("-c", "true")
    assert exec_call[-2] == "-c"
    assert exec_call[-1] == "true"
