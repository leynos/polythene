"""High level orchestration helpers for invoking the Polythene CLI."""

from __future__ import annotations

import dataclasses as dc
import os
import shlex
import typing as typ
from pathlib import Path

from .isolation import DEFAULT_STORE

__all__ = ["PolytheneSession"]

IsolationName = typ.Literal["bubblewrap", "proot", "chroot"]


class SandboxRunner(typ.Protocol):
    """Protocol describing the runner used to execute CLI commands."""

    def run(
        self,
        argv: typ.Sequence[str],
        *,
        timeout: int | None = None,
    ) -> int:  # pragma: no cover - protocol definition
        ...


def _normalise_store(store: Path | str | None) -> Path:
    """Return ``store`` as an absolute :class:`Path` with sensible defaults."""
    if store is None:
        return DEFAULT_STORE
    path = Path(store)
    return path if path.is_absolute() else path.resolve()


def _is_truthy(value: str | None) -> bool:
    """Return ``True`` when ``value`` represents an enabled flag."""
    if value is None:
        return False
    return value.lower() in {"1", "true", "yes", "on"}


@dc.dataclass(slots=True)
class PolytheneSession:
    """Helper for constructing Polythene CLI invocations.

    Parameters
    ----------
    sandbox:
        Object responsible for executing the generated argument vector.
    store:
        Root filesystem store directory. Defaults to
        :data:`polythene.isolation.DEFAULT_STORE` when ``None``.
    env:
        Environment mapping consulted for isolation defaults. When omitted the
        current :data:`os.environ` is used.
    uv_command:
        Executable invoked to run the CLI. Defaults to ``"uv"`` which matches
        the development workflow.

    """

    sandbox: SandboxRunner
    store: Path | str | None = None
    env: typ.Mapping[str, str] | None = None
    uv_command: str = "uv"
    _store_path: Path = dc.field(init=False)
    _env: dict[str, str] = dc.field(init=False)

    def __post_init__(self) -> None:
        """Normalise configuration derived from constructor arguments."""
        self._store_path = _normalise_store(self.store)
        # Copy the environment once to avoid accidental mutation during calls.
        self._env = dict(os.environ if self.env is None else self.env)

    def exec(
        self,
        uuid: str,
        command: typ.Sequence[str] | str,
        *,
        isolation: IsolationName | None = None,
        timeout: int | None = None,
    ) -> int:
        """Execute ``command`` inside the exported root filesystem.

        Parameters
        ----------
        uuid:
            Identifier of the exported root filesystem.
        command:
            Command to run inside the root filesystem. Strings are parsed with
            :func:`shlex.split` while sequences are used as provided.
        isolation:
            Optional isolation backend. When omitted an environment-driven
            default is applied.
        timeout:
            Optional timeout in seconds forwarded to the sandbox runner.

        Returns
        -------
        int
            Exit status returned by the sandbox runner.

        Raises
        ------
        ValueError
            If ``command`` does not contain any tokens.

        """
        argv = self._build_exec_argv(uuid, command, isolation)
        return self.sandbox.run(argv, timeout=timeout)

    # -------------------- Internal helpers --------------------

    def _build_exec_argv(
        self,
        uuid: str,
        command: typ.Sequence[str] | str,
        isolation: IsolationName | None,
    ) -> list[str]:
        tokens = (
            shlex.split(command, comments=False, posix=True)
            if isinstance(command, str)
            else list(command)
        )
        if not tokens:
            msg = "Command must contain at least one token"
            raise ValueError(msg)

        argv = [
            self.uv_command,
            "run",
            "polythene",
            "exec",
            uuid,
            "--store",
            str(self._store_path),
        ]

        default_isolation = self._default_isolation()
        preferred_isolation = isolation or default_isolation
        if preferred_isolation is not None:
            argv.append(f"--isolation={preferred_isolation}")

        argv.append("--")
        argv.extend(tokens)
        return argv

    def _default_isolation(self) -> IsolationName | None:
        explicit = self._env.get("POLYTHENE_ISOLATION")
        if explicit:
            return typ.cast("IsolationName", explicit)

        if _is_truthy(self._env.get("GITHUB_ACTIONS")):
            return "proot"

        return None
