# Developer guide

This guide records maintainer workflows and internal quality contracts for
Polythene. For the command-line interface and user-facing behaviour, see the
[users' guide](./users-guide.md).

## Coverage ownership

Main owns CodeScene. Pull-request CI measures `polythene` serially with the
shared `generate-coverage` action, compares the result with the ratchet
baseline that `coverage-main.yml` wrote on `main` (`with-ratchet: 'true'`), and
uploads no artefact (`publish-artefact: 'false'`). It does not fetch full Git
history, invoke CodeScene, or receive `CS_ACCESS_TOKEN`. The step is guarded to
the `pull_request` event, because `generate-coverage` saves its baseline on a
push to `main` and `coverage-main.yml` must be the only workflow writing it.
Both `generate-coverage` steps set `UV_PYTHON: '3.13'`, the interpreter
`setup-python` installs. The action builds its coverage environment with
whatever interpreter uv finds first, and in the pull-request lane an earlier
step leaves a managed Python 3.14 for it to find, so without the pin the lane
and the publisher measured the same selection on different interpreters (80.82%
against 81.27%). The contract requires every generator to carry the publisher's
step `env`.

After each merge, `coverage-main.yml` regenerates the same measurement,
advances the ratchet, and uploads the Cobertura report with
`upload-codescene-coverage` in explicit `mode: upload`. A check step learns
whether the token exists with the one command
`echo "available=${{ secrets.CS_ACCESS_TOKEN != '' }}" >> "$GITHUB_OUTPUT"`,
which binds nothing, and the upload step runs only when that output is `true`
and `github.ref == 'refs/heads/main'`. The token reaches the uploader only as
its `access-token` input, because the uploader is a composite action and a step
`env` would reach every action nested in it. The ref guard means that a
`workflow_dispatch` aimed at a branch cannot publish that branch as `main`. Its
concurrency group never cancels, so no upload or baseline write is abandoned.
The group is keyed on `github.ref` alone, so runs on `main` never overlap, a
newer trigger replaces an older pending run rather than queueing behind it, and
a branch dispatch cannot displace a pending push to `main`. GitHub does not
promise to start runs in trigger order, so this is not a guarantee of commit
order: an older run can still publish last, and its coverage and baseline then
stand until a later successful run supersedes them; that is accepted. A
dispatch on `main` that replaces a pending push leaves the ratchet baseline one
commit behind until the next push, because the baseline is saved only on a
push. A manual re-run of an older run keeps its SHA and its run id: it
republishes that commit's coverage to CodeScene, but its baseline cache key
already exists, so it replaces no baseline unless the original run saved none.
Merges made by the Dependabot automerge workflow's `GITHUB_TOKEN` fire no push,
so they are published only by a manual dispatch; this is a known exception
until the shared automerge workflow dispatches the publisher itself. With no
`CS_ACCESS_TOKEN` repository secret the upload skips; the ratchet baseline is
still written.

Keep CodeScene credentials and upload actions in `coverage-main.yml`. The
retired `installer-checksum` input, the `CODESCENE_CLI_SHA256` variable, and the
`get-codescene-sha.yml` refresher are gone; the shared uploader verifies the
`cs-coverage` archive from its own manifest.

`tests/workflow_contracts/` holds this shape. `loading.py` parses workflows
through a loader that refuses duplicate keys, and `reading.py` reads the `on:`
triggers in scalar, sequence, and mapping form under either key.
`codescene_reach.py` follows local reusable-workflow calls (`./` and `$/`) from
every workflow a pull request can start (its own events, reviews, comments, the
merge queue, `workflow_run` chains, and pushes not confined to `main` or to
tags) and refuses any key or value in that closure naming the CodeScene host,
the credential, the client, or the uploader, and any read of the whole
`secrets` context or of a computed secret name. `codescene_publisher.py`,
`codescene_token.py`, and `coverage_lanes.py` hold the publisher and the lanes
to the rules above. Each rule returns its findings as text, so the rule tests
beside them can drive it over a constructed tree; every refusal case changes
one thing in the compliant tree in `fixtures.py`. Keep a new rule to that
pattern: a pure reading, a repository assertion, and a refusal case that fails
when the rule's clause is deleted. `test_bounded_properties.py` checks the pure
readings exhaustively over small domains instead of sampling: the closure
against Warshall reachability for every call graph over three workflows, the
condition reader over every conjunction of up to three terms, and the document
walk with a key or value planted at every depth up to three.

## Development checks

Run the standard local checks through the Makefile:

```shell
make check-fmt
make lint
make test
make typecheck
make markdownlint
make nixie
```

The workflow contract tests in `tests/workflow_contracts/` protect the
separation between pull-request ratcheting and main-branch CodeScene
publication.
