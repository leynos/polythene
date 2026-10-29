"""Echo and run external commands, and name the programs they may run.

Cuprum is the only way Polythene starts a process, so this module also owns
the catalogue that says which executables exist. Two pieces belong together:

* :data:`POLYTHENE_CATALOGUE` and :func:`program`, which turn a program name
  into a curated, typed value instead of a string quoted onto a command line;
* :func:`run_cmd`, the single entry point that echoes ``$ <command>`` and then
  runs it; and
* :func:`fail_on_error`, which turns cuprum's result-as-data into the process
  status a CLI should exit with.

Examples
--------
Capture a probe's status instead of raising on a non-zero exit:

>>> result = run_cmd(program("podman")("image", "exists", "busybox"))  # doctest: +SKIP
>>> result.exit_code  # doctest: +SKIP
1

"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from cuprum import (
    CommandResult,
    ExecutionContext,
    Pipeline,
    PipelineResult,
    Program,
    ProgramCatalogue,
    ProjectSettings,
    RunOutputOptions,
    SafeCmd,
    SafeCmdBuilder,
    StdioTarget,
    sh,
)

__all__ = [
    "POLYTHENE_CATALOGUE",
    "Command",
    "CommandOutcome",
    "command_result",
    "fail_on_error",
    "failure_detail",
    "program",
    "run_cmd",
]

#: Every executable Polythene starts. Cuprum refuses a name missing from a
#: catalogue when the command is *built*, so a typo in a backend's binary
#: fails before any probe spawns.
POLYTHENE_CATALOGUE = ProgramCatalogue(
    projects=(
        ProjectSettings(
            name="polythene",
            programs=(
                Program("podman"),
                Program("tar"),
                Program("bwrap"),
                Program("proot"),
                Program("chroot"),
            ),
            documentation_locations=("docs/developers-guide.md",),
            noise_rules=(),
        ),
    )
)

Command = SafeCmd | Pipeline
"""One curated command, or stages joined by ``|``."""

CommandOutcome = CommandResult | PipelineResult
"""One command's result, or one result per pipeline stage."""

#: A target may name a file for the stream. cuprum opens it just before the
#: spawn and closes it straight after, so it never outlives the run. A `str`
#: is accepted for callers that pass `os.devnull` or a path they hold as text;
#: it is resolved exactly as the equivalent `Path` is.
StdioOverride = StdioTarget | str | Path | None


def program(name: str, *, catalogue: ProgramCatalogue | None = None) -> SafeCmdBuilder:
    """Return a builder for the curated program ``name``.

    Parameters
    ----------
    name : str
        The executable's name, which must appear in ``catalogue``.
    catalogue : ProgramCatalogue | None, default=None
        The catalogue to resolve ``name`` against. Defaults to
        :data:`POLYTHENE_CATALOGUE`.

    Returns
    -------
    SafeCmdBuilder
        A callable that produces :class:`cuprum.SafeCmd` values.

    Raises
    ------
    cuprum.UnknownProgramError
        If ``name`` is not in the catalogue. The check runs here, not at
        spawn time.

    Examples
    --------
    >>> builder = program("podman")  # doctest: +SKIP
    >>> builder("image", "exists", "busybox")  # doctest: +SKIP

    """
    resolved = POLYTHENE_CATALOGUE if catalogue is None else catalogue
    return sh.make(Program(name), catalogue=resolved)


def _require_command(cmd: object) -> Command:
    """Narrow ``cmd`` to something cuprum can run, or explain what to pass."""
    if isinstance(cmd, SafeCmd | Pipeline):
        return cmd
    msg = (
        "Command must be a cuprum SafeCmd or Pipeline "
        f"(build one with `program(...)`); got {type(cmd).__name__}"
    )
    raise TypeError(msg)


def _describe(cmd: Command) -> str:
    """Render ``cmd`` the way the echo line spells it, one ``|`` per stage."""
    stages = (cmd,) if isinstance(cmd, SafeCmd) else cmd.parts
    return " | ".join(shlex.join(stage.argv_with_program) for stage in stages)


def _as_target(name: str, override: StdioOverride) -> StdioTarget:
    """Resolve one stream override to a cuprum target.

    Raises
    ------
    TypeError
        If the override is neither a target nor a path.

    """
    if isinstance(override, StdioTarget):
        return override
    if isinstance(override, str):
        return StdioTarget.path(Path(override))
    if isinstance(override, Path):
        return StdioTarget.path(override)
    msg = (
        f"{name} must be a StdioTarget or a path, got {type(override).__name__}; "
        "cuprum spells redirection StdioTarget.path(...) or StdioTarget.inherit()"
    )
    raise TypeError(msg)


def _foreground_output(
    *,
    stdout: StdioOverride,
    stderr: StdioOverride,
) -> RunOutputOptions:
    """Build the options that hand a foreground child the caller's streams.

    Cuprum does not inherit the parent's streams by default. With ``capture``
    and ``echo`` both off, an *unset* target still resolves to a library pipe;
    because nothing consumes it, the child's output is discarded rather than
    passed through. Foreground execution therefore has to name
    ``StdioTarget.inherit()`` explicitly; that is what makes a run
    foregrounded rather than merely uncaptured.
    """
    return RunOutputOptions(
        capture=False,
        echo=False,
        stdout=StdioTarget.inherit()
        if stdout is None
        else _as_target("stdout", stdout),
        stderr=StdioTarget.inherit()
        if stderr is None
        else _as_target("stderr", stderr),
    )


def _captured_output(
    *,
    stdout: StdioOverride,
    stderr: StdioOverride,
) -> RunOutputOptions:
    """Build options that capture both streams.

    Raises
    ------
    ValueError
        If a stream is redirected. Capture reads from a parent-side pipe that
        a redirected stream does not have, so cuprum refuses the combination;
        refusing it here names the caller's own mistake rather than cuprum's.

    """
    if stdout is not None or stderr is not None:
        msg = (
            "stdout/stderr overrides require fg=True: a captured run keeps both "
            "streams for its caller"
        )
        raise ValueError(msg)
    return RunOutputOptions(capture=True, echo=False)


def _pipeline_output(*, fg: bool) -> RunOutputOptions:
    """Build options for a pipeline, whose streams cuprum binds across stages.

    A pipeline refuses ``RunOutputOptions`` stdio targets because its
    intermediate streams belong to the stages' plumbing, so there is no place
    to put a caller's file or inherited descriptor. Echoing is the only way a
    foreground pipeline can reach the caller at all: with capture and echo
    both off, its output is discarded just as a lone command's would be.
    """
    return RunOutputOptions(capture=not fg, echo=fg)


def run_cmd(  # noqa: PLR0913 - one entry point; splitting it would scatter the echo
    cmd: object,
    *,
    fg: bool = False,
    timeout: float | None = None,
    context: ExecutionContext | None = None,
    stdout: StdioOverride = None,
    stderr: StdioOverride = None,
) -> CommandOutcome:
    """Echo ``cmd`` to stderr, run it, and return its result.

    A non-zero exit is data, not an exception: check ``result.exit_code``, or
    hand the result to :func:`fail_on_error`.

    Parameters
    ----------
    cmd : SafeCmd | Pipeline
        The command to run, built through :func:`program`.
    fg : bool, default=False
        Whether the child inherits this process's streams. ``False`` captures
        both streams onto the result instead.
    timeout : float | None, default=None
        Seconds to allow the command; exceeding it raises
        :class:`cuprum.TimeoutExpired`, a :class:`TimeoutError`.
    context : ExecutionContext | None, default=None
        Execution settings such as an environment overlay or working
        directory.
    stdout : StdioTarget | Path | None, default=None
        Where a foreground child's stdout goes. ``None`` inherits it; a path
        sends it to that file, which is how ``polythene pull`` keeps
        ``podman pull`` off its own stdout.
    stderr : StdioTarget | Path | None, default=None
        As ``stdout``, for standard error. A pipeline honours neither, because
        cuprum binds a pipeline's streams across stages.

    Returns
    -------
    CommandOutcome
        A :class:`cuprum.CommandResult` for one command, or a
        :class:`cuprum.PipelineResult` carrying every stage.

    Raises
    ------
    TypeError
        If ``cmd`` is not a cuprum command, or an override is not a target or
        path.
    ValueError
        If stream overrides are given without ``fg``.
    FileNotFoundError
        If the program names no executable the host can resolve.

    Examples
    --------
    >>> run_cmd(program("echo")("hi"), fg=True).exit_code  # doctest: +SKIP
    0

    """
    command = _require_command(cmd)
    output: RunOutputOptions
    if isinstance(command, Pipeline):
        if stdout is not None or stderr is not None:
            msg = (
                "a pipeline cannot redirect stdout/stderr: cuprum binds a "
                "pipeline's streams across stages, so redirect one SafeCmd instead"
            )
            raise ValueError(msg)
        output = _pipeline_output(fg=fg)
    else:
        output = (
            _foreground_output(stdout=stdout, stderr=stderr)
            if fg
            else _captured_output(stdout=stdout, stderr=stderr)
        )

    print(f"$ {_describe(command)}", file=sys.stderr)
    return command.run_sync(output=output, timeout=timeout, context=context)


def failure_detail(outcome: CommandOutcome) -> str:
    """Return a one-line description of why ``outcome`` failed.

    Cuprum reports failures as data, so there is no exception to render. The
    captured stderr carries the tool's own diagnostic when one was written;
    otherwise the exit status is all there is to report.

    A pipeline names the stage that actually failed and its index, because a
    caller told only "exit status 1" cannot tell a broken archive from a
    missing container. A foreground run captures nothing, so its detail is the
    status alone.

    Parameters
    ----------
    outcome : CommandOutcome
        A single command's :class:`cuprum.CommandResult` or a
        :class:`cuprum.PipelineResult`. A successful outcome is accepted, but
        its detail then reads as an exit status of ``0``.

    Returns
    -------
    str
        A single line: ``exit status N`` for a command, optionally followed by
        ``: DETAIL`` when stderr was captured, or
        ``stage N (exit status M)`` for a pipeline's failing stage, again with
        ``: DETAIL`` appended when the stage's stderr was captured.

    Examples
    --------
    >>> failure_detail(run_cmd(program("false")("false")))  # doctest: +SKIP
    'exit status 1'

    """
    if isinstance(outcome, PipelineResult):
        failed = outcome.failure
        if failed is None:
            return f"exit status {_normalize_retcode(outcome.final.exit_code)}"
        stage = f"stage {outcome.failure_index} (exit status {failed.exit_code})"
        return f"{stage}: {failed.stderr.strip()}" if failed.stderr else stage
    detail = (outcome.stderr or "").strip()
    return (
        f"exit status {_normalize_retcode(outcome.exit_code)}: {detail}"
        if detail
        else (f"exit status {_normalize_retcode(outcome.exit_code)}")
    )


def command_result(outcome: CommandOutcome) -> CommandResult:
    """Narrow a run's outcome to a single command's result.

    Callers that read a captured stream need the shape a single command
    returns; a pipeline's per-stage results would answer a different question.

    Parameters
    ----------
    outcome : CommandOutcome
        The result :func:`run_cmd` returned. A single command's result is
        returned unchanged.

    Returns
    -------
    cuprum.CommandResult
        ``outcome`` itself, narrowed from the union.

    Raises
    ------
    TypeError
        If ``outcome`` is a pipeline result.

    Examples
    --------
    >>> command_result(run_cmd(program("true")("true"))).exit_code  # doctest: +SKIP
    0

    """
    if isinstance(outcome, CommandResult):
        return outcome
    msg = "expected a single command result, got a pipeline result"
    raise TypeError(msg)


def _normalize_retcode(retcode: int | None) -> int:
    """Return a sensible exit status when a command lacks a numeric code."""
    if not retcode:
        return 1
    return int(retcode)


def fail_on_error(outcome: CommandOutcome) -> int:
    """Return the status a caller should exit with when ``outcome`` failed.

    Cuprum reports a non-zero exit as data, so the translation back to a
    process status happens here, once, rather than at every call site.

    A pipeline that failed early has two candidate statuses. The failing stage
    reports what went wrong — ``tar`` exits ``1`` on a truncated archive —
    while the final stage reports ``-15`` because cuprum killed it once its
    input died. The failing stage is the one whose status a caller can act on,
    so that is the one returned.

    Parameters
    ----------
    outcome : CommandOutcome
        The result :func:`run_cmd` returned.

    Returns
    -------
    int
        ``0`` when everything succeeded; otherwise the failing command's exit
        status. A signal-derived negative value is returned unchanged, because
        it is already non-zero; only a missing or zero code becomes ``1``.

    Examples
    --------
    >>> fail_on_error(run_cmd(program("false")("false")))  # doctest: +SKIP
    1

    """
    if isinstance(outcome, PipelineResult):
        failed = outcome.failure
        if failed is None:
            return 0 if outcome.ok else _normalize_retcode(outcome.final.exit_code)
        return _normalize_retcode(failed.exit_code)
    return _normalize_retcode(outcome.exit_code) if not outcome.ok else 0
