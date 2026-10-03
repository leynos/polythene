"""Typed recording doubles that stand in for the Podman toolchain.

``polythene.isolation`` shells out through ``get_command`` and ``run_cmd``.
:func:`install_recording_tools` replaces both with doubles so tests can drive
``export_rootfs`` end to end without a container runtime, asserting the exact
argv, ordering, and run options Polythene produces.
"""

from __future__ import annotations

import dataclasses as dc
import shlex
import typing as typ

import polythene.isolation as isolation

if typ.TYPE_CHECKING:
    import pytest

__all__ = [
    "CommandRecord",
    "RecordingCommand",
    "RecordingPodman",
    "RecordingTools",
    "install_recording_tools",
]


@dc.dataclass(slots=True, frozen=True)
class CommandRecord:
    """A single ``run_cmd`` invocation captured by a recording double."""

    argv: tuple[str, ...]
    fg: bool
    timeout: float | None
    run_kwargs: dict[str, object]

    def __str__(self) -> str:
        """Render the invocation so assertion failures stay readable."""
        rendered = shlex.join(self.argv)
        options: list[str] = []
        if self.fg:
            options.append("fg")
        if self.timeout is not None:
            options.append(f"timeout={self.timeout}")
        options.extend(f"{key}={value!r}" for key, value in self.run_kwargs.items())
        suffix = f" ({', '.join(options)})" if options else ""
        return f"{rendered}{suffix}"


@dc.dataclass(slots=True, frozen=True)
class RecordingCommand:
    """A plumbum-like command that knows the argv it would execute.

    Only ``formulate``, indexing, and the ``|`` operator are needed because the
    recorder replaces ``run_cmd`` before any command actually runs.
    """

    argv: tuple[str, ...]

    def formulate(self) -> tuple[str, ...]:
        """Return the argv this command represents."""
        return self.argv

    def __getitem__(self, args: tuple[str, ...]) -> RecordingCommand:
        """Return a new command with ``args`` appended."""
        return RecordingCommand((*self.argv, *args))

    def __or__(self, other: RecordingCommand) -> RecordingCommand:
        """Return a pipeline command joining both sides with ``|``."""
        return RecordingCommand((*self.argv, "|", *other.argv))


@dc.dataclass(slots=True)
class RecordingPodman:
    """Recording stand-in for a plumbum binary such as ``podman`` or ``tar``."""

    binary: str
    default_outcome: object = 0
    calls: list[CommandRecord] = dc.field(default_factory=list[CommandRecord])
    _outcomes: list[tuple[tuple[str, ...], object]] = dc.field(
        default_factory=list[tuple[tuple[str, ...], object]]
    )

    def script(self, *args: str, outcome: object) -> None:
        """Produce ``outcome`` for commands whose arguments start with ``args``.

        ``outcome`` may be a value returned by ``run_cmd``, or an exception
        instance, which is raised at the call site.
        """
        self._outcomes.append((args, outcome))

    def find(self, *args: str) -> list[CommandRecord]:
        """Return recorded calls whose arguments start with ``args``."""
        prefix = (self.binary, *args)
        return [record for record in self.calls if record.argv[: len(prefix)] == prefix]

    def __getitem__(self, args: tuple[str, ...]) -> RecordingCommand:
        """Return a command rooted at this binary."""
        return RecordingCommand((self.binary, *args))

    def run_cmd(
        self,
        cmd: RecordingCommand,
        *,
        fg: bool = False,
        timeout: float | None = None,
        **run_kwargs: object,
    ) -> object:
        """Stand in for :func:`polythene.cmd_utils.run_cmd`."""
        argv = tuple(cmd.formulate())
        self.calls.append(
            CommandRecord(
                argv=argv,
                fg=fg,
                timeout=timeout,
                run_kwargs=dict(run_kwargs),
            )
        )
        outcome = self._outcome_for(argv)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def _outcome_for(self, argv: tuple[str, ...]) -> object:
        """Return the scripted outcome for ``argv``, or the default."""
        args = argv[1:]
        for prefix, outcome in self._outcomes:
            if args[: len(prefix)] == prefix:
                return outcome
        return self.default_outcome


@dc.dataclass(slots=True)
class RecordingTools:
    """Recording doubles installed in place of the Podman toolchain."""

    podman: RecordingPodman
    tar: RecordingPodman
    requested: list[str] = dc.field(default_factory=list[str])


def install_recording_tools(monkeypatch: pytest.MonkeyPatch) -> RecordingTools:
    """Patch ``polythene.isolation`` so tooling resolves to recording doubles."""
    tools = RecordingTools(
        podman=RecordingPodman("podman"),
        tar=RecordingPodman("tar"),
    )
    binaries = {"podman": tools.podman, "tar": tools.tar}

    def fake_get_command(name: str) -> RecordingPodman:
        tools.requested.append(name)
        return binaries[name]

    monkeypatch.setattr(isolation, "get_command", fake_get_command)
    monkeypatch.setattr(isolation, "run_cmd", tools.podman.run_cmd)
    return tools
