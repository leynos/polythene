# Architectural decision record (ADR) 003: Adopt cuprum for process execution

## Status

Accepted, 2026-10-26. Polythene starts every external process through cuprum,
and neither `subprocess` nor `plumbum` remains in the tree. The dependency is
pinned to one exact pre-release, `cuprum==0.2.0b2`.

## Date

2026-10-26.

## Context and problem statement

Polythene started its sandbox probes, image pulls, and exports through
`subprocess`, wrapped by a helper that raised `ProcessExecutionError` on a
non-zero status. The helper echoed the command, normalised signal-derived
negative statuses, and translated a failure into an exception the CLI caught
and turned into an exit code. Behaviour therefore lived in the call sites: a
caller that wanted to *read* a probe's status had to opt into a different
return shape, and a caller that wanted the child's output and the child's exit
status had to read both from a tuple or from `CompletedProcess`.

The repository also had no answer to a simpler question: which executables may
the package start? Any name that reached the helper was run if `PATH` happened
to contain it, so a typo surfaced as a missing-binary error at the far end of a
probe rather than at the line that named the program.

Two further constraints matter here. Polythene's documented CLI contract
includes a `127` exit with a one-line diagnostic when a required tool is
missing, so a missing binary must stay a clean message rather than a traceback.
And the test suite must be able to stand in for a command without turning
itself into a mock of the module under test.

## Decision drivers

- One way to start a process, so behaviour such as echoing, capture, and exit
  handling cannot differ between call sites.
- The set of startable programs should be stated once and enforced before a
  child is spawned.
- A non-zero exit should be ordinary data, translated into a process status
  once, at the point a caller needs one.
- The `127` missing-binary contract must survive the change.
- The dependency must be deployable today; a beta is acceptable if the suite
  pins it.

## Options considered

### Option A: Keep `subprocess` behind the existing helper

Rejected. It leaves the allowed-program question unanswered, and it keeps the
raise-on-failure shape that makes reading a probe's status the special case.

### Option B: Adopt `plumbum`

Rejected. `plumbum` gives pipelines and a shell-like surface, but it resolves
programs from `PATH` on demand, so it does not answer the curation question,
and its raise-on-non-zero default is the behaviour being moved away from.

### Option C: Adopt cuprum, pinned to `0.2.0b2`

Accepted. cuprum builds a command from a `Program` that a `ProgramCatalogue`
must already allowlist; refuses an uncurated name at build time; reports a
non-zero exit as data on `CommandResult`; carries `cwd` and environment on an
`ExecutionContext` rather than in process-global state; and joins stages with
`|` into a `Pipeline` whose `PipelineResult` reports every stage.

## Decision outcome

`polythene/cmd_utils.py` is the only module that touches cuprum. It owns:

- `POLYTHENE_CATALOGUE`, the `ProgramCatalogue` naming every executable the
  package starts: `podman`, `tar`, `bwrap`, `proot`, and `chroot`;
- `program(name)`, which asks cuprum for a `SafeCmdBuilder` for one of those
  names and raises `UnknownProgramError` for any other;
- `run_cmd`, the single entry point that echoes `$ <command>` and calls
  `run_sync`; and
- `fail_on_error` and `failure_detail`, which turn a result into a process
  status and a one-line diagnostic.

`polythene/script_utils.py` re-exports `run_cmd` and adds `get_command`, which
performs the `shutil.which` check that keeps the `127` contract before it asks
`program` for a builder. The split is deliberate: cuprum's own check is on the
*name*, at build time, while the CLI's contract is about the *host*, at the
point a caller would otherwise spawn.

### Consequences for callers

- A non-zero exit no longer raises. Call sites check `result.exit_code` or hand
  the result to `fail_on_error`.
- A pipeline's status comes from its *failing stage*, not from `.final`, which
  may only report that cuprum killed it once its input died.
- A timeout raises `cuprum.TimeoutExpired`, a subclass of `TimeoutError`.

### Streams are explicit

cuprum does not inherit the parent's streams by default: with `capture` and
`echo` both off, an unset target is a library pipe whose far end nothing reads,
so the child's output is discarded. `run_cmd(fg=True)` therefore builds
`StdioTarget.inherit()` for each stream the caller left unset, and
`run_cmd(fg=False)` captures both. A pipeline refuses stdio targets outright,
because cuprum binds a pipeline's intermediate streams across stages.

### Testing

The suite uses no mocking framework. Doubles return real `CommandResult` and
`PipelineResult` values, so a test cannot pass by satisfying an attribute the
real type does not have. Where a test must cross a real process boundary, it
goes through `tests/support/process.py`, which builds a one-program catalogue
per call; `tests/conftest.py` uses it for the CLI entry points, and the
workflow contracts use it for `git`, `uv`, and `make -n`.

### The pin

Cuprum is pre-release, so `pyproject.toml` names one exact beta rather than an
interval: the suite has exercised that beta and no other.
`tests/workflow_contracts/test_cuprum_pin.py` holds the manifest, both halves of
`uv.lock` (the resolved package and the recorded requirement), and the
interpreter's installed version together, and reads the expected version from
the manifest rather than restating it. Its freshness check resolves the
*committed* `pyproject.toml` and `uv.lock` in a scratch directory, because
`make build` runs `uv sync`, which would silently repair a stale lock before a
working-tree check could see it.

## Known risks and limitations

- A pre-release dependency can change under a patch-level bump. The exact pin
  and its contract test contain that risk to one reviewed edit.
- cuprum's surface is large, and several behaviours are only discoverable by
  running it: `capture=False` with `echo=False` discards output, a handle from
  `start()` forces capture on, and stdin text must be wrapped in `StdinInput`.
  The developer guide records the ones that cost real time.
- `ProgramCatalogue` exposes membership through its `allowlist` property; there
  is no public `.projects`. Nothing in polythene depends on it, but a future
  reader looking for the declared projects will not find them there.

## Architectural rationale

The package's process surface is now two questions with one answer each: what
may run, and what happened. Both live in one module, and a typo in a backend's
binary is a build-time error rather than a probe-time surprise.
