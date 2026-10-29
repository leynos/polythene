"""Typed recording doubles that stand in for the Podman toolchain.

``polythene.isolation`` shells out through ``get_command`` and ``run_cmd``.
:func:`install_recording_tools` keeps ``get_command`` real, because a cuprum
builder is an ordinary offline value, and replaces only ``run_cmd``. Tests
therefore assert the exact argv Polythene builds — assembled by the production
catalogue, not by a stand-in — while no container runtime is ever contacted.
"""

from __future__ import annotations

import dataclasses as dc
import shlex
import typing as typ

from cuprum import CommandResult, Pipeline, PipelineResult, SafeCmd, SafeCmdBuilder

import polythene.isolation as isolation
from polythene.cmd_utils import POLYTHENE_CATALOGUE, CommandOutcome, program

if typ.TYPE_CHECKING:
    import pytest

    from polythene.cmd_utils import StdioOverride

__all__ = [
    "CommandRecord",
    "RecordingPodman",
    "RecordingTools",
    "install_recording_tools",
    "result",
]


def _stages(cmd: SafeCmd | Pipeline) -> tuple[SafeCmd, ...]:
    """Return ``cmd``'s stages, one for a lone command."""
    return (cmd,) if isinstance(cmd, SafeCmd) else cmd.parts


def flatten(cmd: SafeCmd | Pipeline) -> tuple[str, ...]:
    """Render ``cmd`` as one argv, with ``"|"`` between pipeline stages.

    A pipeline has no single argv of its own, so the separator keeps each
    stage's argument vector readable in a recorded call and in a failure
    message.
    """
    argv: list[str] = []
    for index, stage in enumerate(_stages(cmd)):
        if index:
            argv.append("|")
        argv.extend(stage.argv_with_program)
    return tuple(argv)


def result(
    cmd: SafeCmd | Pipeline,
    exit_code: int | tuple[int, ...],
    stdout: str = "",
    stderr: str = "",
) -> CommandOutcome:
    """Build the outcome ``cmd`` would report had it exited with ``exit_code``.

    Pipeline stages other than the last hand their output to the next stage,
    so cuprum reports ``None`` for them; the double mirrors that rather than
    inventing captured text no real run would produce.

    A pipeline accepts one code per stage, which is how a test says that
    ``tar`` failed while ``podman export`` succeeded. Splatting a single code
    across every stage would blame the first one, and ``failure_index`` — the
    thing ``failure_detail`` and ``fail_on_error`` read — would point at the
    wrong stage.
    """
    stages = _stages(cmd)
    codes = (exit_code,) * len(stages) if isinstance(exit_code, int) else exit_code
    if len(codes) != len(stages):
        msg = f"{len(codes)} exit codes for a {len(stages)}-stage command"
        raise ValueError(msg)
    results = tuple(
        CommandResult(
            program=stage.program,
            argv=stage.argv,
            exit_code=code,
            pid=0,
            stdout=stdout if index == len(stages) - 1 else None,
            stderr=stderr,
        )
        for index, (stage, code) in enumerate(zip(stages, codes, strict=True))
    )
    if isinstance(cmd, SafeCmd):
        return results[0]
    return PipelineResult(stages=results, failure_index=_first_failure(codes))


def _first_failure(codes: tuple[int, ...]) -> int | None:
    """Return the index of the first non-zero code, or ``None``."""
    return next((index for index, code in enumerate(codes) if code), None)


@dc.dataclass(slots=True, frozen=True)
class CommandRecord:
    """A single ``run_cmd`` invocation captured by a recording double."""

    argv: tuple[str, ...]
    fg: bool
    timeout: float | None
    stdout: StdioOverride
    stderr: StdioOverride

    def __str__(self) -> str:
        """Render the invocation so assertion failures stay readable."""
        rendered = shlex.join(self.argv)
        options: list[str] = []
        if self.fg:
            options.append("fg")
        if self.timeout is not None:
            options.append(f"timeout={self.timeout}")
        if self.stdout is not None:
            options.append(f"stdout={self.stdout!r}")
        if self.stderr is not None:
            options.append(f"stderr={self.stderr!r}")
        suffix = f" ({', '.join(options)})" if options else ""
        return f"{rendered}{suffix}"


ScriptedOutcome = tuple[int | tuple[int, ...], str, str] | BaseException
"""What a test can script for one call, or an exception to raise.

A result triple's first element is either one status for every stage or, for a
pipeline, one status per stage in order.
"""


@dc.dataclass(slots=True)
class RecordingPodman:
    """Recording stand-in for the ``run_cmd`` that would start a container tool."""

    binary: str
    default_outcome: int = 0
    calls: list[CommandRecord] = dc.field(default_factory=list[CommandRecord])
    _outcomes: list[tuple[tuple[str, ...], ScriptedOutcome]] = dc.field(
        default_factory=list[tuple[tuple[str, ...], ScriptedOutcome]]
    )

    def script(
        self,
        *args: str,
        outcome: ScriptedOutcome,
    ) -> None:
        """Produce ``outcome`` for commands whose arguments start with ``args``.

        ``outcome`` is a ``(status, stdout, stderr)`` triple, which this turns
        into the result cuprum would have returned for that command, or an
        exception instance, which is raised at the call site instead. A triple
        is the short form because most tests care about the status and one
        message, not the whole result record.
        """
        self._outcomes.append((args, outcome))

    def find(self, *args: str) -> list[CommandRecord]:
        """Return recorded calls whose arguments start with ``args``."""
        prefix = (self.binary, *args)
        return [record for record in self.calls if record.argv[: len(prefix)] == prefix]

    def run_cmd(  # noqa: PLR0913 - mirrors the signature it stands in for
        self,
        cmd: SafeCmd | Pipeline,
        *,
        fg: bool = False,
        timeout: float | None = None,
        context: object = None,
        stdout: StdioOverride = None,
        stderr: StdioOverride = None,
    ) -> CommandOutcome:
        """Stand in for :func:`polythene.cmd_utils.run_cmd`."""
        argv = flatten(cmd)
        self.calls.append(
            CommandRecord(
                argv=argv,
                fg=fg,
                timeout=timeout,
                stdout=stdout,
                stderr=stderr,
            )
        )
        outcome = self._outcome_for(argv)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, tuple):
            return result(cmd, *outcome)
        return result(cmd, self.default_outcome)

    def _outcome_for(self, argv: tuple[str, ...]) -> ScriptedOutcome | None:
        """Return the scripted outcome for ``argv``, or ``None``.

        ``None`` means nothing was scripted, so the default status applies.
        """
        args = argv[1:]
        for prefix, outcome in self._outcomes:
            if args[: len(prefix)] == prefix:
                return outcome
        return None


@dc.dataclass(slots=True)
class RecordingTools:
    """Recording doubles installed in place of the Podman toolchain."""

    podman: RecordingPodman
    tar: RecordingPodman
    requested: list[str] = dc.field(default_factory=list[str])


def install_recording_tools(monkeypatch: pytest.MonkeyPatch) -> RecordingTools:
    """Patch ``polythene.isolation.run_cmd`` so no runtime is contacted.

    ``get_command`` is left alone: the builders it returns come from
    :data:`polythene.cmd_utils.POLYTHENE_CATALOGUE` and never touch ``PATH``
    until a command runs. Recording the names it was asked for is the one
    observation the real function cannot offer, so it is wrapped rather than
    replaced.
    """
    tools = RecordingTools(
        podman=RecordingPodman("podman"),
        tar=RecordingPodman("tar"),
    )

    def recording_get_command(name: str) -> SafeCmdBuilder:
        tools.requested.append(name)
        return program(name, catalogue=POLYTHENE_CATALOGUE)

    monkeypatch.setattr(isolation, "get_command", recording_get_command)
    monkeypatch.setattr(isolation, "run_cmd", tools.podman.run_cmd)
    return tools
