"""Start a real child process from a test, through cuprum.

A few tests cannot observe what they need in-process: a scrubbed environment
only exists once a fresh interpreter reads it, and a console-script entry point
has to be executed rather than imported. Those runs cross a real process
boundary, and they still go through cuprum so the suite has one way to start a
process rather than two.

Each call builds a catalogue admitting exactly the program it starts, named by
absolute path where the caller supplies one. A resolved path keeps the run free
of ``PATH`` lookup, so a fixture's own ``PATH`` scrubbing decides what the
*child* sees without also deciding which binary this helper starts.
"""

from __future__ import annotations

import sys
import typing as typ

from cuprum import (
    CommandResult,
    ExecutionContext,
    Program,
    ProgramCatalogue,
    ProjectSettings,
    RunOutputOptions,
    sh,
)
from cuprum.context import EnvMode

from tests.support.cli import CliResult

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "PYTHON",
    "run_child",
    "run_command",
    "to_cli_result",
]

#: How long a child may run before the test fails. It bounds a child left
#: blocked on a read that never completes, so a broken implementation reports a
#: failure rather than hanging the suite.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: The interpreter running the suite, so a child needs no ``PATH`` resolution.
PYTHON = Program(sys.executable)


def _catalogue_for(program: Program) -> ProgramCatalogue:
    """Return a one-program catalogue, keeping each run's allowlist minimal."""
    return ProgramCatalogue(
        projects=(
            ProjectSettings(
                name="polythene-tests",
                programs=(program,),
                documentation_locations=("docs/developers-guide.md",),
                noise_rules=(),
            ),
        )
    )


def run_command(
    argv: cabc.Sequence[str],
    *,
    cwd: Path | None = None,
    env: cabc.Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CommandResult:
    """Run ``argv`` as one captured child process and return its result.

    Parameters
    ----------
    argv : collections.abc.Sequence[str]
        The program followed by its arguments. Give the program as an absolute
        path to keep the run independent of ``PATH``.
    cwd : Path | None
        Working directory for the child. ``None`` inherits the caller's.
    env : collections.abc.Mapping[str, str] | None
        The complete environment for the child, replacing the parent's. A
        caller that wants an overlay passes ``dict(os.environ)`` with its
        changes already applied, which keeps the difference between the two
        visible at the call site.
    timeout : float
        Seconds to allow the child.

    Returns
    -------
    cuprum.CommandResult
        The child's outcome, with both streams captured as text. A non-zero
        exit is data; callers check ``.exit_code`` rather than catching.

    Raises
    ------
    cuprum.UnknownProgramError
        If ``argv`` is empty.

    """
    program = Program(argv[0])
    command = sh.make(program, catalogue=_catalogue_for(program))(*argv[1:])
    context = ExecutionContext(
        cwd=cwd,
        env=dict(env) if env is not None else None,
        env_mode=EnvMode.REPLACE if env is not None else EnvMode.OVERLAY,
    )
    return command.run_sync(
        output=RunOutputOptions(capture=True),
        context=context,
        timeout=timeout,
    )


def run_child(
    source: str,
    *args: str,
    cwd: Path | None = None,
    env: cabc.Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CommandResult:
    """Run ``source`` under this interpreter as ``-c``, with ``args`` after it."""
    return run_command(
        [str(PYTHON), "-c", source, *args],
        cwd=cwd,
        env=env,
        timeout=timeout,
    )


def to_cli_result(outcome: CommandResult) -> CliResult:
    """Project a captured command result onto the CLI result shape."""
    return CliResult(
        exit_code=outcome.exit_code,
        stdout=outcome.stdout or "",
        stderr=outcome.stderr or "",
    )
