# Polythene design

## Overview

Polythene delivers a consistent workflow for system-level testing when working
inside environments with differing levels of privilege and isolation. The
Cyclopts-based CLI coordinates root file system staging, command execution, and
log reporting so that the same test suite can be executed in restrictive
sandboxes such as the Codex cloud and in container-friendly continuous
integration (CI) runners. This document records the architectural structure
that enables that behaviour and captures the trade-offs behind the current
implementation.

## Execution flow

Polythene prepares the execution environment by locating a stored root file
system (rootfs) and probing each supported backend until it finds one capable
of running the requested command. The probing sequence reflects the preference
for stronger isolation (bubblewrap) while still allowing execution in
toolchains that lack user namespace support (proot) or container primitives
(chroot).

For screen readers: The following sequence diagram outlines how the CLI
resolves a rootfs, probes bubblewrap and proot, and falls back to chroot when
needed before returning the resulting exit code to the caller.

```mermaid
sequenceDiagram
  autonumber
  actor U as User
  participant CLI as polythene CLI (Typer)
  participant BW as bubblewrap
  participant PR as proot
  participant CH as chroot

  U->>CLI: polythene exec UUID -- CMD...
  CLI->>CLI: resolve rootfs path
  alt rootfs missing
    CLI-->>U: error (exit 1)
  else available
    CLI->>BW: probe userns/proc
    alt BW works
      CLI->>BW: exec CMD in rootfs
      BW-->>CLI: exit code
    else BW unavailable
      CLI->>PR: probe
      alt PR works
        CLI->>PR: exec CMD in rootfs
        PR-->>CLI: exit code
      else PR unavailable
        CLI->>CH: exec CMD in rootfs
        CH-->>CLI: exit code
      end
    end
    CLI-->>U: propagate exit code
  end
```

## Core components

- **Cyclopts CLI:** Parses user input, resolves configuration, and emits
  commands for the backends while ensuring consistent exit codes across
  platforms.
- **Backend registry:** Encapsulates the bubblewrap, proot, and chroot
  integrations with shared probing and directory preparation helpers to remove
  duplicated logic.
- **Process execution:** A curated cuprum catalogue names every executable the
  package may start, and one helper runs them. The decision and its
  consequences are recorded in
  [ADR 003](adr-003-adopt-cuprum-for-process-execution.md).
- **Script utilities:** Provide filesystem and command helpers that are safe to
  consume both from installed packages and from ad-hoc scripts shipped in the
  repository.

## Design considerations

- **Deterministic fallbacks:** The backend probe order is deterministic so test
  outcomes remain reproducible even when multiple tools are available on the
  same host.
- **Minimal dependencies:** The project leans on Cyclopts for the CLI and cuprum
  for process execution, keeping the interface expressive without introducing
  heavyweight orchestration layers.
- **Documentation-first:** Behavioural specifications (pytest-bdd scenarios)
  describe the expected workflows, ensuring documentation and implementation
  stay aligned.

## Packaging and release

The distribution published to PyPI is `polythene-isolate`, while the import
package and the console script are both `polythene`. The distinction keeps the
PyPI name available to this project without renaming either the module that
users import or the command they run.

Releases are built from the sdist: a plain `uv build` produces the sdist and
then the wheel from it, so a successful build also proves the sdist is
complete. The release pipeline attests both files, publishes them to PyPI, and
attaches the same bytes and the Sigstore bundle to the tag's GitHub Release.
Publication is reconciled per filename with a fixed precedence — PyPI, then the
GitHub Release, then the run's own bytes — so a repeated tag converges rather
than overwriting anything already published. The pipeline, the name, and the
reconciliation rule are recorded in
[ADR 002](adr-002-attested-reconciled-release-pipeline.md); the operational
steps are in the [developer guide](developers-guide.md#publishing-a-release).
