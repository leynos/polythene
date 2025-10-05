# Polythene

Polythene packages the Linux packaging helper originally shipped with the
shared-actions repository. It bundles the Cyclopts-based command line
interface, its plumbum process helpers, and uuid6 UUID generation so you can
pull container images and execute commands inside ephemeral root filesystems
without requiring a full container runtime on the target machine.

## Motivation

System-level tests—package installation, filesystem mutations, and other tasks
that normally demand containers—are difficult to run in sandboxes that disable
container engines. Polythene provides a consistent abstraction over those
workflows so the same test suite can run inside OpenAI's Codex cloud
environment (root user, no containers) and on GitHub runners (unprivileged
user, containers available). The CLI pulls the desired base image, exports it
to a disposable root filesystem, and then selects the safest available
execution backend for the host.

The result is portable automation: you can iterate on package verification in a
Codex workspace and ship the same tests to CI without changing commands or
rewriting scripts.

## Dependencies

Polythene targets Python 3.12 and newer. Runtime dependencies are bundled in
the package metadata and installed automatically when you run the Makefile
targets below:

- [Cyclopts](https://pypi.org/project/cyclopts/) for the command line interface.
- [plumbum](https://plumbum.readthedocs.io/) for running external commands such
  as `podman`, `bwrap`, and `proot`.
- [uuid6](https://pypi.org/project/uuid6/) for generating collision-resistant
  identifiers for exported filesystems.

At runtime Polythene expects `podman` to be available for image pulls. The
`polythene exec` command can fall back to either `bwrap`, `proot`, or a
privileged `chroot` if they are present.

## Installation

The repository ships with a Makefile that builds a virtual environment via
[uv](https://github.com/astral-sh/uv). Install the tooling and project
dependencies with:

```shell
make build
```

The default target installs dependencies, checks formatting, runs tests, and
performs a type check:

```shell
make all
```

## Usage

Polythene exposes a Cyclopts CLI entry point named `polythene`. Run it with
`uv run` during development, or call the installed script directly after
`pip`/`uv` installation. The module shim also supports `python -m polythene`
for environments that prefer explicit interpreter invocation:

```shell
uv run polythene pull docker.io/library/busybox:latest
# or
python -m polythene pull docker.io/library/busybox:latest
```

The `pull` command downloads the image, exports it to a UUID-named directory in
`/var/tmp/polythene` (or the location provided with `--store`), and prints that
UUID to stdout. Use the UUID with `exec`:

```shell
uv run polythene exec 018f6a4c-2f25-7642-bb1d-d523b6b0e05d -- uname -a
```

The execution command runs the provided program inside the root filesystem. It
tries `bwrap` first, then `proot`, and finally `chroot`. You can override the
store location per command with `--store`.

Specify `--isolation=<backend>` to prefer a particular sandbox when the host
has known restrictions. For example, GitHub runners benefit from
`--isolation=proot` because bubblewrap cannot map user namespaces.

For example, you can install and test a package using the same commands in
Codex and CI:

```shell
uv run polythene exec <uuid> -- dnf install -y ripgrep
uv run polythene exec <uuid> -- rg --version
```

When a container runtime is unavailable, Polythene falls back to sandboxing via
`bwrap` or `proot`. On hosts with a container engine, the same commands reuse
the exported filesystem to provide identical isolation boundaries.

## Development workflow

To contribute changes, format the code, run the tests, and type-check the
project via the Makefile targets. Helpful commands include:

- `make fmt` – Format Python and Markdown sources.
- `make lint` – Run Ruff static analysis.
- `make test` – Execute the pytest suite.
- `make typecheck` – Run static type checks with `ty`.

Refer to the users' guide in `docs/users-guide.md` for deeper operational
details and troubleshooting advice.
