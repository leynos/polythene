"""CLI result type shared by fixtures and BDD assertions.

This lives outside ``conftest.py`` so every consumer imports it via the
single canonical path ``tests.support.cli``, regardless of whether the
consumer is a fixture defined in a ``conftest.py`` or a step/assertion
defined in a BDD test module. See ``tests/support/__init__.py`` for the
rationale.
"""

from __future__ import annotations

import dataclasses as dc
import re
import typing as typ

_BOX_DRAWING = re.compile(r"[\u2500-\u257f]")
_WHITESPACE = re.compile(r"\s+")


@dc.dataclass(slots=True)
class CliResult:
    """Container capturing CLI output and exit status."""

    exit_code: int
    stdout: str
    stderr: str


def normalise_cli_output(output: str) -> str:
    """Remove Rich box characters and collapse output whitespace."""
    without_borders = _BOX_DRAWING.sub("", output)
    return _WHITESPACE.sub(" ", without_borders).strip()


def assert_cli_diagnostic(
    result: CliResult,
    *fragments: str,
    stream: typ.Literal["stdout", "stderr"] = "stderr",
) -> None:
    """Assert a non-zero diagnostic on one stream and no output on the other."""
    diagnostic = normalise_cli_output(getattr(result, stream))
    other_stream = "stderr" if stream == "stdout" else "stdout"
    other_output = getattr(result, other_stream)

    assert result.exit_code != 0, "Expected the CLI to fail"  # noqa: S101
    for fragment in fragments:
        normalised_fragment = normalise_cli_output(fragment)
        assert normalised_fragment in diagnostic  # noqa: S101
    assert not other_output.strip(), f"Expected no output on {other_stream}"  # noqa: S101


def assert_no_process_launch(result: CliResult) -> None:
    """Assert that the CLI did not echo a child command launch."""
    assert not any(  # noqa: S101
        line.startswith("$ ") for line in result.stderr.splitlines()
    ), "Expected no child command launch echo"
