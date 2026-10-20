# Polythene users' guide

This guide explains how to install, configure, and operate Polythene. The
project wraps a pair of command line tools that automate the workflow of
exporting Podman images into disposable root filesystems and running commands
inside those filesystems without a dedicated container runtime.

Polythene exists to bridge very different execution environments. In OpenAI's
Codex sandbox you run as root without access to container engines, while GitHub
runners expose Podman to an unprivileged user. Polythene exposes the same
commands in both scenarios so package installation tests, filesystem mutation
checks, and other system-level automation run identically across local
development and continuous integration (CI).

## Installation workflow

Polythene is published to PyPI as the `polythene-isolate` distribution. Install
it with [uv](https://github.com/astral-sh/uv):

```shell
uv tool install polythene-isolate
# or
uv add polythene-isolate
```

The distribution name differs from the command it installs. The import package
is `polythene` and the console script is `polythene`, so after installation:

```shell
polythene --help
python -m polythene --help
```

Both forms behave identically. The `polythene-isolate` name on PyPI is only the
name the project is published under.

To work on Polythene itself, install from a checkout instead. The project uses
[uv](https://github.com/astral-sh/uv) to manage Python dependencies, and the
bundled Makefile targets run from the repository root:

```shell
make build
```

The command creates a virtual environment in `.venv` and installs the runtime
and development dependencies specified in `pyproject.toml`. You can verify the
installation and perform all quality gates with:

```shell
make all
```

The default target runs formatting checks, the pytest suite, and static typing
via `ty`.

## Command reference

Polythene exposes two Cyclopts commands. Both commands accept the optional
`--store` argument to override the root filesystem directory (defaults to
`/var/tmp/polythene`).

### Execution environments

Before running commands, decide how they interact with your host. Polythene
provides a single interface but adapts to the available tooling:

- **Codex sandbox** – You run as root without container engines. The
  `polythene pull` command still uses Podman inside the sandbox because Codex
  maintains the binary on disk, and `polythene exec` falls back to `bwrap`,
  `proot`, or a privileged `chroot`.
- **GitHub runners** – You run as an unprivileged user with Podman available.
  The CLI exports images in the same way but typically selects `bwrap` for
  execution, providing equivalent isolation to the Codex workflow.

In both environments the exported root filesystem is disposable, enabling
repeatable system-level tests without polluting the host.

### `polythene pull`

```shell
uv run polythene pull docker.io/library/busybox:latest
# or
python -m polythene pull docker.io/library/busybox:latest
```

The pull command:

- ensures the store directory exists,
- probes the active Podman store with `podman image exists IMAGE`,
- pulls the image only when that probe reports it absent,
- exports the image into a UUID-named root filesystem directory, and
- prints the generated UUID to stdout for later reuse, as the only line written
  there.

Podman's progress reporting, image IDs, and container IDs are kept off stdout,
so `polythene pull` can be captured with `$(...)` without filtering. It works
the same way with `--timeout` as without it. To see what Polythene and Podman
are doing, set `POLYTHENE_VERBOSE` (see
[Environment variables](#environment-variables)) or read stderr.

Because the probe reads local storage rather than a registry, an image you
built in the same job can be reused without publishing it. The probe and the
subsequent container creation resolve the same `podman` command and inherit the
same environment, so both see the same Podman store:

```shell
podman build --tag localhost/example:latest .
uv run polythene pull localhost/example:latest --store ./polythene-store
```

Without the probe, Podman would read the `localhost` component of that
reference as a registry host and try to reach `https://localhost/v2/`, which
fails when no registry is listening there.

An image is only reused when it is visible to the Podman user and storage
configuration Polythene inherits. Building it with a different
`--storage-driver`, a different `CONTAINERS_STORAGE_CONF`, or under another
user places it in a separate store, and the probe will report it absent so
Polythene falls back to pulling it. The same applies when a probe fails for an
unrelated reason such as unreadable local storage: Polythene reports that
status instead of silently treating the image as missing.

Podman must be installed and available on `PATH`. When the `POLYTHENE_VERBOSE`
variable is set, the command also prints progress messages to stderr.

### `polythene exec`

```shell
uv run polythene exec <uuid> -- uname -a
# or
python -m polythene exec <uuid> -- uname -a
```

Replace `<uuid>` with the value returned by a previous `polythene pull` call.
The exec command runs a user supplied program inside the exported root
filesystem. It picks the first available execution backend in the following
order:

1. [`bwrap`](https://github.com/containers/bubblewrap)
2. [`proot`](https://proot-me.github.io/)
3. A privileged `chroot`

Each backend receives the prepared filesystem as its root and blocks network
access. If none of the backends is available, the command fails with an error
message detailing the missing tooling.

When a specific backend is preferable, pass `--isolation <backend>` (or the
equivalent `--isolation=<backend>` form) to reorder the probing sequence.
GitHub runners lack user namespace support for `bwrap`, and specifying
`--isolation proot` avoids the noisy permission errors emitted by bubblewrap
before `proot` succeeds.

Because the same UUID works across hosts, you can prepare an image on Codex and
reuse it on CI:

```shell
uv run polythene pull registry.example.invalid/tools:latest
uv run polythene exec <uuid> -- make -C /workspace/tests system
```

The `exec` invocation will select the available backend on each host while the
commands run unchanged.

## Output streams and exit status

Polythene keeps stdout for command results. `pull` writes only the generated
UUID; `exec` leaves stdout to the child command. Help output goes to stdout and
exits with status 0.

Parser errors, application errors, verbose logs, notices that a local image is
being reused, and the `$ cmd` launch echo go to stderr. This keeps diagnostics
available without adding them to captured command results.

The CLI uses these exit statuses:

| Situation                                                 | Status                          |
| --------------------------------------------------------- | ------------------------------: |
| Parser error                                              | Non-zero status set by Cyclopts |
| `exec` has no command                                     | 2                               |
| Requested UUID root filesystem is missing                 | 1                               |
| Unsupported isolation backend in a direct `cmd_exec` call | 2                               |
| All isolation backends are unavailable                    | 126                             |
| A child command ran                                       | The child's status              |

`polythene.main(argv)` raises `SystemExit` and does not return a status code.
`PolytheneSession.run` returns the subprocess status reported by its sandbox
runner.

## Environment variables

Polythene recognizes the following environment variables:

- `POLYTHENE_STORE` – Directory to hold exported root filesystems. Defaults to
  `/var/tmp/polythene`. Command line options take precedence over the variable.
- `POLYTHENE_VERBOSE` – Enable verbose logging when set to any value.
- `POLYTHENE_ISOLATION` – Preferred isolation backend used when no
  `--isolation` flag is provided. The CLI and `PolytheneSession` helper both
  honour the value and fall back to their built-in defaults when the variable
  is unset.

Podman calls inherit the caller's environment and configuration files.
Polythene sets no Podman storage or events configuration. The variables
`CONTAINERS_STORAGE_DRIVER` and `CONTAINERS_EVENTS_BACKEND` have no effect on
Podman. Callers can choose a storage driver with `STORAGE_DRIVER` or
`--storage-driver`, or select a `storage.conf` file with
`CONTAINERS_STORAGE_CONF`. They can choose the events logger with
`engine.events_logger` in `containers.conf`, selected with `CONTAINERS_CONF`.

Changing the storage driver or root selects a different Podman store. Images in
the default store, including locally built images, are invisible to the
local-image probe: it reports them absent, and Polythene pulls them. See
[`polythene pull`](#polythene-pull) for the caller-store contract.

## Cleaning up exported filesystems

Exported root filesystems accumulate in the store directory. Remove them when
no longer needed:

```shell
rm -rf /var/tmp/polythene/<uuid>
```

You can automate the cleanup by scripting over helper commands, for example:

```shell
find /var/tmp/polythene -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
```

Adjust the predicate to match your retention policy.

## Troubleshooting

- **Podman pull failures** – Ensure the host has network access and the target
  image reference is valid. Review Podman's stderr output for registry errors.
- **Missing execution backends** – Install `bubblewrap` or `proot` to avoid
  requiring root privileges for `chroot`. On Fedora, for example, run
  `dnf install bubblewrap proot`.
- **Permission errors** – Use a writable store directory. The defaults point to
  `/var/tmp`, which typically supports world-writable storage.

## Further reading

Refer to `polythene/__init__.py` for the Cyclopts application definition and to
`tests/test_polythene.py` for integration-style usage examples.
