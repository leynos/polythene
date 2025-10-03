# Polythene users' guide

This guide explains how to install, configure, and operate Polythene. The
project wraps a pair of command line tools that automate the workflow of
exporting Podman images into disposable root filesystems and running commands
inside those filesystems without a dedicated container runtime.

## Installation workflow

Polythene uses [uv](https://github.com/astral-sh/uv) to manage Python
dependencies. Run the bundled Makefile targets from the repository root:

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

Polythene exposes two Typer commands. Both commands accept the optional
`--store` argument to override the root filesystem directory (defaults to
`/var/tmp/polythene`).

### `polythene pull`

```shell
uv run polythene pull docker.io/library/busybox:latest
```

The pull command:

- ensures the store directory exists,
- calls `podman` to pull the requested container image,
- exports the image into a UUID-named root filesystem directory, and
- prints the generated UUID to stdout for later reuse.

Podman must be installed and available on `PATH`. When the `POLYTHENE_VERBOSE`
variable is set, the command also prints progress messages to stderr.

### `polythene exec`

```shell
uv run polythene exec <uuid> -- uname -a
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

## Environment variables

Polythene recognises the following environment variables:

- `POLYTHENE_STORE` – Directory to hold exported root filesystems. Defaults to
  `/var/tmp/polythene`. Command line options take precedence over the variable.
- `POLYTHENE_VERBOSE` – Enable verbose logging when set to any value.

The CLI also sets two Podman hardening variables if they are not already set:
`CONTAINERS_STORAGE_DRIVER=vfs` and `CONTAINERS_EVENTS_BACKEND=file`.

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

Refer to `src/polythene/__init__.py` for the Typer application definition and to
`tests/test_polythene.py` for integration-style usage examples.
