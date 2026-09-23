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

After each merge, `coverage-main.yml` regenerates the same measurement,
advances the ratchet, and uploads the Cobertura report with
`upload-codescene-coverage` in explicit `mode: upload`. The upload step binds
the secret itself and runs only when `github.ref == 'refs/heads/main'` and the
token is non-empty, so a `workflow_dispatch` aimed at a branch cannot publish
that branch as `main`. Its concurrency group never cancels: a newer push
replaces an older pending run, and the newest baseline wins. The group is keyed
on `github.ref` and `github.event_name`, so no dispatch, from a branch or from
`main`, can displace a pending push to `main`; a dispatch does not advance the
ratchet baseline. With no `CS_ACCESS_TOKEN` repository secret the upload skips;
the ratchet baseline is still written.

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
`secrets` context or of a computed secret name. `codescene_publisher.py` and
`coverage_lanes.py` hold the publisher and the lanes to the rules above. Each
rule returns its findings as text, so the rule tests beside them can drive it
over a constructed tree; every refusal case changes one thing in the compliant
tree in `fixtures.py`. Keep a new rule to that pattern: a pure reading, a
repository assertion, and a refusal case that fails when the rule's clause is
deleted. `test_bounded_properties.py` checks the pure readings exhaustively
over small domains instead of sampling: the closure against Warshall
reachability for every call graph over three workflows, the condition reader
over every conjunction of up to three terms, and the document walk with a key
or value planted at every depth up to three.

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
