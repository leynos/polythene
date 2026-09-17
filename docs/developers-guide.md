# Developer guide

This guide records maintainer workflows and internal quality contracts for
Polythene. For the command-line interface and user-facing behaviour, see the
[users' guide](./users-guide.md).

## Coverage ownership

Pull-request CI generates coverage with the local ratchet baseline written by
`coverage-main.yml`. It does not fetch full Git history, invoke CodeScene, or
receive `CS_ACCESS_TOKEN`. The main-only workflow runs on pushes to `main`,
writes the updated ratchet baseline, and uploads the Cobertura report to
CodeScene with `mode: upload` after a merge.

Keep CodeScene credentials, project URLs, and upload actions in
`coverage-main.yml`. Pull-request coverage should use the shared
`generate-coverage` action with serial pytest and `with-ratchet: 'true'`, so
the pull-request result is measured against the last published main baseline.

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

The workflow contract tests in `tests/test_coverage_workflow_contract.py`
protect the separation between pull-request ratcheting and main-branch
CodeScene publication.
