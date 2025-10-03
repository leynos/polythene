# Polythene

Polythene packages the Linux packaging helper originally shipped with the
shared-actions repository. It bundles the Typer-based command line interface,
its plumbum process helpers, and uuid6 UUID generation so you can pull
container images and execute commands inside ephemeral root filesystems without
requiring a full container runtime on the target machine.

## Dependencies

Polythene targets Python 3.9 and newer. Runtime dependencies are bundled in the
package metadata and installed automatically when you run the Makefile targets
below:

- [Typer](https://typer.tiangolo.com/) for the command line interface.
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

Polythene exposes a Typer CLI entry point named `polythene`. Run it with
`uv run` during development:

```shell
uv run polythene pull docker.io/library/busybox:latest
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

## Development workflow

To contribute changes, format the code, run the tests, and type-check the
project via the Makefile targets. Helpful commands include:

- `make fmt` – Format Python and Markdown sources.
- `make lint` – Run Ruff static analysis.
- `make test` – Execute the pytest suite.
- `make typecheck` – Run static type checks with `ty`.

Refer to the users' guide in `docs/users-guide.md` for deeper operational
details and troubleshooting advice.
