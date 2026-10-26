# Scripting standards

Project scripts must prioritize clarity, reproducibility, and testability. The
baseline tooling is Python and the [`uv`](https://github.com/astral-sh/uv)
launcher so that scripts remain dependency‑self‑contained and easy to execute
in Continuous Integration (CI) or locally.

Cyclopts is the default command‑line interface (CLI) framework for new and
updated scripts. This document supersedes prior guidance that recommended Typer
as a default.

## Rationale for adopting Cyclopts

- Environment‑first configuration without glue. Cyclopts reads environment
  variables with a defined prefix (for example, `INPUT_`) and maps them to
  parameters directly. Bash argument assembly and bespoke parsing can be
  removed.
- Typed lists and paths from env. Parameters annotated as `list[str]` or
  `list[pathlib.Path]` are populated from whitespace‑ or delimiter‑separated
  environment values. Custom split/trim helpers are unnecessary.
- Clear precedence model. CLI flags override environment variables, which
  override code defaults. Behaviour is predictable in both CI and local runs.
- Small API surface. The API is explicit and integrates cleanly with type
  hints, aiding readability and testing.
- Backwards‑compatible migration. Option aliases and per‑parameter
  environment variable names permit preservation of existing interfaces while
  removing shell glue.

## Language and runtime

- Target Python 3.13 for all new scripts. Older versions may only be used when
  integration constraints require them, and any exception must be documented
  inline.
- Each script starts with an `uv` script block so runtime and dependency
  expectations travel with the file. Prefer the shebang
  `#!/usr/bin/env -S uv run python` followed by the metadata block shown in the
  example below.
- External processes are invoked via
  [`cuprum`](https://pypi.org/project/cuprum/) to provide curated, structured
  command execution rather than ad‑hoc shell strings. Cuprum is pre-release, so
  a script pins the exact beta it was written against; the repository's own pin
  is the one the suite has run.
- File‑system interactions use `pathlib.Path`. Higher‑level operations (for
  example, copying or removing trees) go through the `shutil` standard library
  module.

### Minimal script (no CLI)

```python
#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.13"
# dependencies = ["cuprum==0.2.0b2"]
# ///

from __future__ import annotations

from pathlib import Path

from cuprum import (
    ExecutionContext,
    Program,
    ProgramCatalogue,
    RunOutputOptions,
    StdioTarget,
    sh,
)

#: Every executable this script may start. Cuprum refuses any other name when
#: the command is built, so a typo fails before anything spawns.
CATALOGUE = ProgramCatalogue.from_programs(Program("tofu"), name="infra")

#: Foreground: the plan's output reaches the terminal as the tool wrote it.
FOREGROUND = RunOutputOptions(
    capture=False,
    stdout=StdioTarget.inherit(),
    stderr=StdioTarget.inherit(),
)


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    cluster_dir = project_root / "infra" / "clusters" / "dev"
    # The builder is not the command: call it, even with no arguments.
    plan = sh.make(Program("tofu"), catalogue=CATALOGUE)("plan")
    result = plan.run_sync(output=FOREGROUND, context=ExecutionContext(cwd=cluster_dir))
    raise SystemExit(result.exit_code)


if __name__ == "__main__":
    main()
```

Two details are easy to get wrong. `sh.make` returns a builder, so the command
is `sh.make(...)("plan")` and not `sh.make(...)`; a bare builder echoed into a
log tells you nothing about what ran. And with `capture` and `echo` both off,
cuprum gives the child a pipe nobody reads, so its output is *discarded* rather
than passed through. A foreground command has to say `StdioTarget.inherit()`
explicitly.

### Cyclopts CLI pattern (environment‑first)

Employ Cyclopts when a script requires parameters, particularly under CI with
`INPUT_*` variables.

```python
#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.13"
# dependencies = ["cyclopts>=4.25,<6.0", "cuprum==0.2.0b2"]
# ///

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import cyclopts
from cyclopts import App, Parameter
from cuprum import (
    ExecutionContext,
    Program,
    ProgramCatalogue,
    RunOutputOptions,
    StdioTarget,
    sh,
)

#: Every executable this script may start.
CATALOGUE = ProgramCatalogue.from_programs(Program("tofu"), name="infra")

FOREGROUND = RunOutputOptions(
    capture=False,
    stdout=StdioTarget.inherit(),
    stderr=StdioTarget.inherit(),
)

# Map INPUT_<PARAM> → function parameter without additional glue
app = App(config=cyclopts.config.Env("INPUT_", command=False))


@app.default
def main(
    *,
    # Required parameters
    bin_name: Annotated[str, Parameter(required=True)],
    version: Annotated[str, Parameter(required=True)],

    # Optional scalars
    package_name: Optional[str] = None,
    target: Optional[str] = None,
    outdir: Optional[Path] = None,
    dry_run: bool = False,

    # Lists (whitespace/newline separated by default)
    formats: list[str] | None = None,
    man_paths: Annotated[list[Path] | None, Parameter(env_var="INPUT_MAN_PATHS")] = None,
    deb_depends: list[str] | None = None,
    rpm_depends: list[str] | None = None,
):
    name = package_name or bin_name

    project_root = Path(__file__).resolve().parents[1]
    build_dir = (outdir or (project_root / "dist")) / name

    if dry_run:
        print({
            "name": name,
            "version": version,
            "target": target,
            "formats": formats,
            "man_paths": [str(p) for p in (man_paths or [])],
            "deb_depends": deb_depends,
            "rpm_depends": rpm_depends,
            "build_dir": str(build_dir),
        })
        return

    build_dir.mkdir(parents=True, exist_ok=True)
    # Replace the planned target with the real build tooling.
    plan = sh.make(Program("tofu"), catalogue=CATALOGUE)("plan")
    result = plan.run_sync(output=FOREGROUND, context=ExecutionContext(cwd=build_dir))
    if result.exit_code != 0:
        raise SystemExit(result.exit_code)


if __name__ == "__main__":
    app()
```

Guidance:

- Parameter names should be descriptive and stable. Where a legacy flag name
  must remain available, add an alias:

  ```python
  package_name: Annotated[Optional[str], Parameter(aliases=["--name"])] = None
  ```

- Where a specific delimiter is required for an environment list (for example,
  comma‑separated `formats`), specify it per parameter:

  ```python
  formats: Annotated[list[str] | None, Parameter(env_var_split=",")] = None
  ```

- Per‑parameter environment names can be pinned for backwards compatibility:

  ```python
  config_out: Annotated[Optional[Path], Parameter(env_var="INPUT_CONFIG_PATH")] = None
  ```

## cuprum: command calling and pipelines

### Basics: curated programs, capturing output, handling failures

```python
from __future__ import annotations

import sys

from cuprum import Program, ProgramCatalogue, RunOutputOptions, sh

CATALOGUE = ProgramCatalogue.from_programs(
    Program("git"), Program("grep"), Program("sed"), Program("wc"),
    name="repo",
)


def git(*args: str):
    """Build one git command from this module's catalogue."""
    return sh.make(Program("git"), catalogue=CATALOGUE)(*args)


# Capture stdout. A non-zero exit does NOT raise: it is data on the result.
result = git("--no-pager", "log", "-1", "--pretty=%H").run_sync(
    output=RunOutputOptions(capture=True)
)
if result.exit_code != 0:
    # Handle gracefully; result.stderr holds the tool's own diagnostic.
    raise SystemExit(result.exit_code)
last_commit = result.stdout.strip()

# Pipelines join with |, and the result carries every stage.
shortlog = (git("--no-pager", "log", "--oneline") | sh.make(
    Program("grep"), catalogue=CATALOGUE
)("fix")).run_sync(output=RunOutputOptions(capture=True))

if not shortlog.ok:
    # `failure` and `failure_index` name the stage that actually failed; the
    # pipeline's `final` stage may only report that it was killed.
    failed = shortlog.failure
    print(f"stage {shortlog.failure_index}: {failed.stderr}", file=sys.stderr)
```

`RunOutputOptions(capture=True)` is the default, so a bare `run_sync()`
captures as well; naming it makes the read of `stdout`/`stderr` explicit.
`run_sync` takes its options as keyword arguments only —
`run_sync(RunOutputOptions(...))` is a `TypeError`.

### Working directory and environment management

Cuprum has no ambient working-directory stack. The directory and the
environment travel with the *execution*, so two commands run with different
settings cannot interfere with one another:

```python
from pathlib import Path

from cuprum import ExecutionContext, RunOutputOptions
from cuprum.context import EnvMode

repo_dir = Path(__file__).resolve().parents[1]

tags = git("tag", "--list").run_sync(
    output=RunOutputOptions(capture=True),
    context=ExecutionContext(cwd=repo_dir),
)

# An environment named on the context is an OVERLAY on the live process
# environment by default: variables set after import stay visible.
identity = git("var", "GIT_AUTHOR_IDENT").run_sync(
    output=RunOutputOptions(capture=True),
    context=ExecutionContext(
        cwd=repo_dir,
        env={"GIT_AUTHOR_NAME": "CI", "GIT_AUTHOR_EMAIL": "ci@example.org"},
    ),
)
assert identity.stdout.startswith("CI <ci@example.org>")

# REPLACE renders from an empty environment instead; use it to prove what the
# child can see, or to keep a credential-bearing variable out of it.
scrubbed = git("status").run_sync(
    context=ExecutionContext(env={"PATH": "/usr/bin:/bin"}, env_mode=EnvMode.REPLACE)
)
```

`cuprum.env(...)` is the ambient equivalent when a whole block of code, not one
execution, must see a variable:

```python
from cuprum import env

with env(GIT_AUTHOR_NAME="CI", GIT_AUTHOR_EMAIL="ci@example.org"):
    git("var", "GIT_AUTHOR_IDENT").run_sync(output=RunOutputOptions(capture=True))
```

### Foreground execution and background jobs

```python
import asyncio

from cuprum import RunOutputOptions, StdioTarget

# Foreground: name the inherited streams. capture=False alone would DISCARD
# the child's output, because cuprum hands it a pipe nobody reads.
FOREGROUND = RunOutputOptions(
    capture=False,
    stdout=StdioTarget.inherit(),
    stderr=StdioTarget.inherit(),
)

make = sh.make(Program("make"), catalogue=CATALOGUE)("-j4")
make.run_sync(output=FOREGROUND)


async def background() -> None:
    """Start a child, use the handle, and let the handle settle it."""
    echo = sh.make(Program("echo"), catalogue=CATALOGUE)("done")
    # start() is a coroutine returning a handle that owns the child; leaving
    # the `async with` block stops a child that is still running.
    handle = await echo.start()  # captures by default
    async with handle as owned:
        result = await owned.wait()
    print(result.exit_code, result.stdout)

    sleep = sh.make(Program("sleep"), catalogue=CATALOGUE)("5")
    handle = await sleep.start()
    result = await handle.terminate()  # SIGTERM, then the grace period
    print(result.exit_code)  # signal-derived, so negative


asyncio.run(background())
```

`SafeCmd.start()` is a coroutine, so the handle must be awaited before
`async with` can be used on it. Capture is **forced on** for a handle — the
whole point of one is to be able to ask what the child said, and a child whose
streams went to a pipe nothing reads cannot answer. An inherited target is
therefore refused outright:

```plaintext
ValueError: RunOutputOptions stdout cannot be redirected to 'inherit' while
capture or echo is enabled
```

To watch a long-running child while it works, echo instead of inheriting:
`RunOutputOptions(capture=True, echo=True)` mirrors each line to the parent and
still returns both streams. The handle offers `wait()`, `signal()`,
`terminate()`, and `kill()`, all coroutines, and every one of them is
idempotent.

### Piping stdin and redirection

```python
from pathlib import Path

from cuprum import RunOutputOptions, StdinInput, StdioTarget

# Provide stdin explicitly. A bare string is not accepted: the run-time type
# check reaches `.resolve()` on it first and reports AttributeError, so wrap
# the text in StdinInput.
stripped = sh.make(Program("sed"), catalogue=CATALOGUE)(
    "-n", "s/^v//p"
).run_sync(
    output=RunOutputOptions(capture=True),
    stdin=StdinInput(text="v1.2.3\nv2.0.0\n"),
)
assert stripped.stdout.splitlines() == ["1.2.3", "2.0.0"]

# Multi-stage pipeline: the last stage's stdout is `PipelineResult.stdout`.
count = (git("--no-pager", "log", "--oneline") | sh.make(
    Program("grep"), catalogue=CATALOGUE
)("chore") | sh.make(
    Program("wc"), catalogue=CATALOGUE
)("-l")).run_sync(output=RunOutputOptions(capture=True))
assert count.stdout.strip().isdigit()

# Redirection is a StdioTarget on one command, never on a pipeline: cuprum
# binds a pipeline's intermediate streams across stages.
log = Path("dist/git.log")
git("status").run_sync(
    output=RunOutputOptions(
        capture=False,
        stdout=StdioTarget.path(log),
        stderr=StdioTarget.inherit(),
    )
)
```

A pipeline refuses `RunOutputOptions` stdio targets with
`ValueError: Pipeline.run does not support RunOutputOptions stdout, stderr
targets`.
It also has no `stdin`, so a stage that reads input must be given it some
other way — feed the data between two `run_sync` calls, or redirect a single
command instead of a pipeline.

## pathlib: robust path manipulation

### Project roots, joins, and ensuring directories

```python
from __future__ import annotations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST = PROJECT_ROOT / "dist"
(DIST / "artifacts").mkdir(parents=True, exist_ok=True)

# Portable joins and normalization
cfg = PROJECT_ROOT.joinpath("config", "release.toml").resolve()
```

### Reading / writing files and atomic updates

```python
from pathlib import Path
import tempfile

f = Path("./dist/version.txt")

# Text I/O
f.write_text("1.2.3\n", encoding="utf-8")
version = f.read_text(encoding="utf-8").strip()

# Atomic write pattern (tmp → replace)
with tempfile.NamedTemporaryFile("w", delete=False, dir=f.parent, encoding="utf-8") as tmp:
    tmp.write("new-contents\n")
    tmp_path = Path(tmp.name)

tmp_path.replace(f)  # atomic on POSIX
```

### Globbing, filtering, and safe deletion

```python
from pathlib import Path

# Recursive glob
md_files = sorted(Path("docs").glob("**/*.md"))

# Filter by suffix / size
small_md = [p for p in md_files if p.stat().st_size < 4096 and p.suffix == ".md"]

# Safe deletion (ignore missing)
try:
    (Path("build") / "temp.bin").unlink()
except FileNotFoundError:
    pass
```

## Cyclopts + cuprum + pathlib together (reference script)

```python
#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.13"
# dependencies = ["cyclopts>=4.25,<6.0", "cuprum==0.2.0b2"]
# ///

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import cyclopts
from cyclopts import App, Parameter
from cuprum import (
    ExecutionContext,
    Program,
    ProgramCatalogue,
    RunOutputOptions,
    StdioTarget,
    sh,
)

#: Every executable this script may start.
CATALOGUE = ProgramCatalogue.from_programs(Program("git"), name="release")

#: Foreground: inherited streams, so the tag command's own output is shown.
FOREGROUND = RunOutputOptions(
    capture=False,
    stdout=StdioTarget.inherit(),
    stderr=StdioTarget.inherit(),
)

app = App(config=cyclopts.config.Env("INPUT_", command=False))


@app.default
def main(
    *,
    bin_name: Annotated[str, Parameter(required=True)],
    version: Annotated[str, Parameter(required=True)],
    formats: list[str] | None = None,
    outdir: Optional[Path] = None,
    dry_run: bool = False,
):
    project_root = Path(__file__).resolve().parents[1]
    dist = (outdir or (project_root / "dist")) / bin_name
    dist.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        tag = sh.make(Program("git"), catalogue=CATALOGUE)("tag", f"v{version}")
        result = tag.run_sync(
            output=FOREGROUND, context=ExecutionContext(cwd=project_root)
        )
        if result.exit_code != 0:
            raise SystemExit(result.exit_code)

    print({
        "bin_name": bin_name,
        "version": version,
        "formats": formats or [],
        "dist": str(dist),
    })


if __name__ == "__main__":
    app()
```

## Testing expectations

- Automated coverage via `pytest` is required for every script. `monkeypatch`
  covers Python‑level substitution; external executables are replaced by
  pointing `PATH` at a shim script, which cuprum resolves at spawn time just as
  it would a real binary.
- Behavioural flows that map cleanly to scenarios should adopt Behaviour‑Driven
  Development (BDD) via `pytest-bdd` so that intent is captured in
  human‑readable Given/When/Then narratives.
- Tests reside in `scripts/tests/`, mirroring script names. For example,
  `scripts/bootstrap_doks.py` pairs with `scripts/tests/test_bootstrap_doks.py`.
- Where scripts rely on environment variables, both happy paths and failure
  modes must be asserted; tests should demonstrate graceful error handling
  rather than opaque stack traces.

### Python dependencies and environment (monkeypatch)

```python
from cyclopts.testing import invoke
from scripts.package import app


def test_reads_env_and_defaults(monkeypatch):
    # Arrange env for Cyclopts
    monkeypatch.setenv("INPUT_BIN_NAME", "demo")
    monkeypatch.setenv("INPUT_VERSION", "1.2.3")
    monkeypatch.setenv("INPUT_FORMATS", "deb rpm")  # whitespace or newlines

    # Exercise
    result = invoke(app, [])

    # Assert
    assert result.exit_code == 0
    assert '"version": "1.2.3"' in result.stdout


def test_patched_helper(monkeypatch):
    # Substitute a helper rather than starting the process it would run.
    from scripts import helpers

    monkeypatch.setattr(helpers, "compute_checksum", lambda _data: "deadbeef")
    assert helpers.compute_checksum(b"abc") == "deadbeef"
```

### Replacing external executables with a PATH shim

Cuprum resolves an executable when the command *runs*, not when it is built, so
a shim earlier on `PATH` stands in for the real binary without patching the
module under test. The shim records the arguments it was given, which is how a
test asserts what would have run:

```python
import os
import stat
from pathlib import Path

import pytest

from scripts.package import tag_release


@pytest.fixture
def git_shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a recording ``git`` on PATH and return its transcript path."""
    transcript = tmp_path / "git.log"
    shim = tmp_path / "git"
    shim.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> {transcript}\n'
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return transcript


def test_tag_release_passes_the_version(git_shim: Path) -> None:
    tag_release("1.2.3")

    assert git_shim.read_text(encoding="utf-8").split() == ["tag", "v1.2.3"]


def test_tag_release_propagates_a_refusal(
    git_shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rewrite the shim so the command the script sees exits non-zero.
    git_shim.with_name("git").write_text(
        "#!/bin/sh\nprintf 'denied\\n' >&2\nexit 1\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        tag_release("1.2.3")

    assert excinfo.value.code == 1
```

Because the child is a real process, the shim is the only thing standing in for
it: the script's own `RunOutputOptions`, its `PATH` handling, and its exit-code
translation are all exercised exactly as they are in production. A shim that
merely replaces the module's `run_cmd`, by contrast, proves nothing about the
part that was broken.

## Operational guidelines

- Scripts must be idempotent. Re‑running should converge state without
  destructive side effects. Guard conditions (for example, checking the secrets
  manager for existing secrets) should precede writes or rotations.
- Pure functions that accept configuration objects are preferred over global
  state so that tests can exercise logic deterministically.
- Exit codes should follow UNIX conventions: `0` for success, non‑zero for
  actionable failures. Human‑friendly error messages should highlight
  remediation steps.
- Dependencies must remain minimal. Any new package should be added to the `uv`
  block and the rationale documented within the script or companion tests.

## Migration guidance (Typer → Cyclopts)

1. Dependencies: replace Typer with Cyclopts in the script’s `uv` block.
2. Entry point: replace `app = typer.Typer(...)` with `app = App(...)` and
   configure `Env("INPUT_", command=False)` where environment variables are
   authoritative in CI.
3. Parameters: replace `typer.Option(...)` with annotations and
   `Parameter(...)`. Mark required options with `required=True`. Map any
   non‑matching environment names via `env_var=...`.
4. Lists: remove custom split/trim code. Use list‑typed parameters; add
   `env_var_split=","` where a non‑whitespace delimiter is required.
5. Compatibility: retain legacy flag names using `aliases=["--old-name"]`.
6. Bash glue: delete argument arrays and conditional appends in GitHub
   Actions. Export `INPUT_*` environment variables and call `uv run` on the
   script.

## CI wiring: GitHub Actions (Cyclopts‑first)

```yaml
- name: Build
  shell: bash
  working-directory: ${{ inputs.project-dir }}
  env:
    INPUT_BIN_NAME: ${{ inputs.bin-name }}
    INPUT_VERSION: ${{ inputs.version }}
    INPUT_FORMATS: ${{ inputs.formats }}               # multiline or space‑sep
    INPUT_OUTDIR: ${{ inputs.outdir }}
  run: |
    set -euo pipefail
    uv run "${GITHUB_ACTION_PATH}/scripts/package.py"
```

## Notes and gotchas

- Newline‑separated lists are preferred for CI inputs to avoid shell quoting
  issues across platforms.
- A non‑zero exit is data on the result, not an exception: inspect
  `result.exit_code` and translate it once, at the point a caller needs a
  process status.
- Production code should present friendly error messages; tests may assert raw
  behaviours (non‑zero exits, stderr contents) by reading the result, or by
  giving a `PATH` shim a fixed exit status.
- `cuprum.TimeoutExpired` derives from `TimeoutError`, so an existing
  `except TimeoutError` keeps working; there is no second timeout exception to
  catch.
- A program missing from the catalogue fails when the command is *built* with
  `UnknownProgramError`. A program that is curated but not installed fails when
  the command *runs* with `FileNotFoundError`.
- On Windows, newline‑separated lists are recommended for `list[Path]` to
  sidestep `;`/`:` semantics.

This document should be referenced when introducing or updating automation
scripts to maintain a consistent developer experience across the repository.
