"""Unit tests for :mod:`polythene.cmd_utils`."""

from __future__ import annotations

import dataclasses as dc
import inspect
import os
import re
import sys
import typing as typ

import pytest
from cuprum import (
    CommandResult,
    PipelineResult,
    Program,
    ProgramCatalogue,
    ProjectSettings,
    SafeCmd,
    SafeCmdBuilder,
    TimeoutExpired,
)

from polythene import cmd_utils
from polythene.cmd_utils import (
    POLYTHENE_CATALOGUE,
    command_result,
    fail_on_error,
    failure_detail,
    program,
    run_cmd,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

PYTHON = Program(sys.executable)

#: A throwaway catalogue for probes. ``PYTHON`` is registered by its absolute
#: path, so these tests run the interpreter they are already running under
#: rather than whatever ``python`` happens to mean on ``PATH``.
PROBE_CATALOGUE = ProgramCatalogue(
    projects=(
        ProjectSettings(
            name="polythene-tests",
            programs=(PYTHON, Program("sh"), Program("cat"), Program("false")),
        ),
    )
)


def probe(name: str, *args: str) -> SafeCmd:
    """Build a command from :data:`PROBE_CATALOGUE`."""
    return _builder(name)(*args)


def _builder(name: str) -> SafeCmdBuilder:
    """Return a builder for ``name`` from the probe catalogue."""
    return program(name, catalogue=PROBE_CATALOGUE)


def _payload(source: str) -> SafeCmd:
    """Build a command running ``source`` under this interpreter."""
    return probe(str(PYTHON), "-c", source)


_STREAM_PAYLOAD = (
    "import sys;"
    " sys.stdout.write('child-stdout-marker\\n');"
    " sys.stderr.write('child-stderr-marker\\n')"
)


def test_run_cmd_echoes_the_invocation(capsys: pytest.CaptureFixture[str]) -> None:
    """The echo line names the program and every argument, on stderr."""
    capsys.readouterr()

    outcome = command_result(run_cmd(_payload("print('unit')"), fg=True))

    assert outcome.exit_code == 0
    echoed = capsys.readouterr().err
    assert f"$ {sys.executable} -c 'print" in echoed
    assert outcome.stdout is None, "a foreground run does not capture output"


def test_run_cmd_captures_both_streams_by_default() -> None:
    """A captured run returns the child's output instead of writing it."""
    outcome = command_result(run_cmd(_payload(_STREAM_PAYLOAD)))

    assert outcome.exit_code == 0
    assert outcome.ok
    assert outcome.stdout == "child-stdout-marker\n"
    assert outcome.stderr == "child-stderr-marker\n"


def test_run_cmd_foreground_inherits_streams_without_overrides(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A foreground call without overrides hands the child the caller's streams.

    ``capfd`` is required because the child writes to the inherited file
    descriptors; ``capsys`` would only see Python-level writes.
    """
    outcome = command_result(run_cmd(_payload(_STREAM_PAYLOAD), fg=True))

    assert outcome.exit_code == 0
    captured = capfd.readouterr()
    assert "child-stdout-marker" in captured.out
    # The echo line also reaches stderr, so match the child's exact line.
    assert "child-stderr-marker" in captured.err.splitlines()


@pytest.mark.parametrize("timeout", [None, 30])
def test_run_cmd_foreground_sends_stdout_to_a_path(
    timeout: int | None,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A path override diverts stdout while stderr still inherits."""
    sink = tmp_path / "sunk.txt"

    outcome = command_result(
        run_cmd(_payload(_STREAM_PAYLOAD), fg=True, timeout=timeout, stdout=sink)
    )

    assert outcome.exit_code == 0
    assert sink.read_text(encoding="utf-8") == "child-stdout-marker\n"
    captured = capfd.readouterr()
    assert "child-stdout-marker" not in captured.out
    assert "child-stderr-marker" in captured.err.splitlines()


def test_run_cmd_foreground_overrides_inherit_stdin(tmp_path: Path) -> None:
    """A stdout override must not cost the child its inherited stdin.

    Redirecting one stream cannot quietly turn the others into empty pipes:
    a child that reads stdin has to see the parent's descriptor. Poking file
    descriptor 0 at a real file is what makes that observable, because an
    inherited descriptor yields the file's contents and a drained pipe yields
    nothing. The descriptor is restored in ``finally`` so pytest's own capture
    is left intact.
    """
    seen = tmp_path / "stdin.txt"
    payload = (
        f"import pathlib,sys;pathlib.Path({str(seen)!r}).write_text(sys.stdin.read())"
    )
    saved_stdin = os.dup(0)
    try:
        with (tmp_path / "parent-stdin.txt").open("w+") as feed:
            feed.write("inherited-stdin\n")
            feed.flush()
            feed.seek(0)
            os.dup2(feed.fileno(), 0)
            outcome = command_result(
                run_cmd(_payload(payload), fg=True, timeout=30, stdout=os.devnull)
            )
    finally:
        os.dup2(saved_stdin, 0)
        os.close(saved_stdin)

    assert outcome.exit_code == 0
    assert seen.read_text(encoding="utf-8") == "inherited-stdin\n"


def test_run_cmd_returns_a_failed_status_as_data() -> None:
    """A non-zero exit is a result, not an exception."""
    outcome = command_result(run_cmd(probe("sh", "-c", "exit 3")))

    assert not outcome.ok
    assert outcome.exit_code == 3
    assert fail_on_error(outcome) == 3


def test_run_cmd_reports_the_child_diagnostic_on_failure() -> None:
    """The tool's own message reaches :func:`failure_detail`."""
    outcome = run_cmd(probe("sh", "-c", "echo broken >&2; exit 4"))

    assert failure_detail(outcome) == "exit status 4: broken"


def test_run_cmd_rejects_a_bare_string() -> None:
    """A string is not a command; the message names the correct form."""
    with pytest.raises(TypeError, match="cuprum SafeCmd or Pipeline"):
        run_cmd(typ.cast("typ.Any", "echo oops"))

    with pytest.raises(TypeError, match="cuprum SafeCmd or Pipeline"):
        run_cmd(typ.cast("typ.Any", None))


class _Recording:
    """Capture the options ``run_cmd`` passes down to cuprum."""

    @staticmethod
    def replace_run_sync(
        monkeypatch: pytest.MonkeyPatch,
    ) -> list[dict[str, object]]:
        """Stub ``SafeCmd.run_sync`` and return the recorded keyword arguments."""
        calls: list[dict[str, object]] = []

        def fake_run_sync(
            _cmd: SafeCmd,
            **kwargs: object,
        ) -> CommandResult:
            calls.append(kwargs)
            return CommandResult(
                program=PYTHON,
                argv=(),
                exit_code=0,
                pid=0,
                stdout="",
                stderr="",
            )

        monkeypatch.setattr(SafeCmd, "run_sync", fake_run_sync)
        return calls


def test_run_cmd_returns_the_kwargs_to_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``timeout`` and ``context`` are forwarded, not swallowed."""
    from cuprum import ExecutionContext

    calls = _Recording.replace_run_sync(monkeypatch)
    context = ExecutionContext(cwd="/")

    run_cmd(_payload(""), timeout=5, context=context)

    assert calls[0]["timeout"] == 5
    assert calls[0]["context"] is context


def test_run_cmd_timeout_raises_timeout_error() -> None:
    """A command that outlives its timeout raises :class:`TimeoutError`."""
    with pytest.raises(TimeoutExpired):
        run_cmd(_payload("import time; time.sleep(30)"), fg=True, timeout=0.2)


def test_run_cmd_captured_overrides_are_refused() -> None:
    """A captured run cannot redirect a stream it is meant to return."""
    with pytest.raises(ValueError, match="require fg=True"):
        run_cmd(_payload(""), stdout=os.devnull)


def test_run_cmd_rejects_an_unusable_override() -> None:
    """The override message names cuprum's two spellings for redirection."""
    with pytest.raises(TypeError, match=r"StdioTarget\.path"):
        run_cmd(_payload(""), fg=True, stdout=typ.cast("typ.Any", 7))


def test_run_cmd_pipeline_captures_the_final_stage() -> None:
    """A captured pipeline returns the last stage's output as ``.stdout``."""
    outcome = run_cmd(
        probe(str(PYTHON), "-c", "print('piped')") | probe("cat"),
    )

    assert isinstance(outcome, PipelineResult)
    assert outcome.ok
    assert outcome.stdout == "piped\n"
    assert outcome.stages[0].stdout is None, "stage 0 pipes into stage 1"


def test_run_cmd_pipeline_echoes_every_stage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The echo line renders each stage and the ``|`` between them."""
    capsys.readouterr()

    run_cmd(probe(str(PYTHON), "-c", "pass") | probe("cat") | probe("cat"))

    echoed = capsys.readouterr().err
    assert echoed.count(" | ") == 2, echoed
    assert echoed.count("cat") == 2, echoed


def test_run_cmd_pipeline_refuses_a_stream_target() -> None:
    """A pipeline's streams are bound across stages, so a target is refused."""
    pipeline = probe("cat") | probe("cat")

    with pytest.raises(ValueError, match="a pipeline cannot redirect"):
        run_cmd(pipeline, fg=True, stdout=os.devnull)


def test_fail_on_error_reports_the_failing_pipeline_stage() -> None:
    """The failing stage's status is the one a caller can act on.

    Cuprum kills the final stage once its input dies, so that stage reports a
    signal-derived status. Returning it would tell the shell nothing about
    what actually went wrong.
    """
    outcome = run_cmd(
        probe("sh", "-c", "printf x; exit 2") | probe("cat"),
    )

    assert not outcome.ok
    assert fail_on_error(outcome) == 2
    assert failure_detail(outcome) == "stage 0 (exit status 2)"


def test_command_result_rejects_a_pipeline_result() -> None:
    """Narrowing the wrong result type names the mismatch."""
    outcome = run_cmd(probe("cat") | probe("cat"))

    with pytest.raises(TypeError, match="expected a single command result"):
        command_result(outcome)


def test_failure_detail_reports_one_for_an_outcome_that_succeeded() -> None:
    """A successful outcome reads as status 1, matching ``_normalize_retcode``.

    ``failure_detail`` documents a successful outcome as an ``exit status``
    with no detail, and the value it renders is the normalized one. A caller
    that prints the detail to excuse a failure needs it to describe what
    ``fail_on_error`` would return, not the raw zero.
    """
    outcome = command_result(run_cmd(_payload("")))

    assert outcome.ok
    assert fail_on_error(outcome) == 0
    assert failure_detail(outcome) == "exit status 1"


def test_failure_detail_reports_one_for_a_pipeline_that_succeeded() -> None:
    """A pipeline with no failing stage renders the same normalized status."""
    outcome = run_cmd(_payload("") | probe("cat"))

    assert isinstance(outcome, PipelineResult)
    assert outcome.ok
    assert failure_detail(outcome) == "exit status 1"


def test_documented_examples_name_only_catalogued_programs() -> None:
    """Every ``program(...)`` in the public docstrings must build.

    A ``doctest: +SKIP`` example still teaches a caller a call they may copy,
    so an uncatalogued name there fails at their prompt rather than here.
    """
    documented = _documented_program_names()

    assert documented, "no program(...) calls found in the module docstrings"
    for name in documented:
        program(name)  # raises UnknownProgramError for an uncurated name


def _documented_program_names() -> set[str]:
    """Return the program names the public docstrings' examples pass to ``program``."""
    pattern = re.compile(r"""program\(\s*["']([^"']+)["']""")

    names: set[str] = set()
    for docstring in _public_docstrings():
        names.update(pattern.findall(docstring))
    return names


def _public_docstrings() -> typ.Iterator[str]:
    """Yield the docstring of every public function ``cmd_utils`` exports."""
    for name in cmd_utils.__all__:
        member = getattr(cmd_utils, name)
        if inspect.isfunction(member) and member.__doc__:
            yield member.__doc__


def test_polythene_catalogue_covers_every_program_the_package_starts() -> None:
    """The curated allowlist is the one place a program name is introduced."""
    names = {str(program) for program in POLYTHENE_CATALOGUE.allowlist}

    assert names == {"podman", "tar", "bwrap", "proot", "chroot"}


def test_program_rejects_a_name_outside_the_catalogue() -> None:
    """A name the catalogue does not curate fails before any spawn."""
    from cuprum import UnknownProgramError

    with pytest.raises(UnknownProgramError, match="not in the catalogue"):
        program("definitely-not-a-curated-tool")


def test_command_record_is_immutable() -> None:
    """The result types are values, so a test double cannot mutate one."""
    outcome = command_result(run_cmd(_payload("")))

    with pytest.raises(dc.FrozenInstanceError):
        typ.cast("typ.Any", outcome).exit_code = 1
