# open-ipod-sync architecture

This document describes the current architecture and safety model of
`open-ipod-sync`.

The project is intentionally narrow in scope. The currently proven
synchronization model is generic incremental **ADD-only** synchronization for
legacy iPod touch devices. Rename synchronization, delete synchronization, and
metadata updates to existing tracks are not part of the current write path.

## Design goals

The implementation is built around five primary goals:

1. keep the music source read-only;
2. keep the iPod read-only except for the smallest explicitly requested
   synchronization window;
3. detect source/device drift before destructive state transitions;
4. make interrupted transactions recoverable or fail closed;
5. validate both media and database state before considering a transaction
   committed.

The default operational posture is therefore read-only.

## High-level architecture

```text
                    dedicated read-only music source
                               |
                               v
                       source scanner
                               |
                               v
                      content SHA-256
                    + metadata probing
                               |
                               v
                         planner
                     /           \
                    /             \
             human plan        plan --json
                    \             /
                     \           /
                      transaction plan
                            |
                      --apply only
                            |
                            v
                       preflight gates
                            |
                            v
                     recovery journal
                            |
                            v
                 temporary iPod RW window
                            |
             +--------------+--------------+
             |                             |
             v                             v
        media writer                 database builder
             |                             |
             +--------------+--------------+
                            |
                            v
                    readback validation
                            |
                            v
                     iPod restored RO
                            |
                            v
                       post-validation
                            |
                            v
                          commit
```

## Major components

### CLI and orchestration

The main Python application lives in:

```text
src/ipod_sync.py
```

The installed package exposes the `ipod-sync` command.

The CLI is responsible for:

- loading configuration;
- routing read-only versus write-capable commands;
- source and device safety checks;
- planning;
- transaction orchestration;
- recovery routing;
- diagnostics through `doctor`;
- human-readable and JSON output.

Write-capable synchronization is not the default execution path. An actual
synchronization transaction requires `sync --apply`.

### Music source

The configured source is expected to be a dedicated filesystem mount that is
kernel-mounted read-only.

The source barrier is important because a synchronization tool should never
modify, rename, chmod, transcode in place, or otherwise mutate the authoritative
music library.

When conversion is necessary, output is produced separately for the iPod
transaction. The source file remains untouched.

### Source scanner and planner

The planner compares source content with the device library before any write
transaction begins.

Content identity is based on SHA-256 rather than title matching.

The planner also accounts for duplicate-content multiplicity. Two source files
with identical bytes must not accidentally collapse into one logical track
when two copies are required.

Current plan outcomes include the ADD-only synchronization model plus explicit
non-write states such as already-present content, skips, or conflicts.

The planner can be consumed by humans or automation:

```bash
ipod-sync plan
ipod-sync plan --json
```

`plan --json` is read-only and provides a machine-readable representation of
the same safety decision.

### Read-only iPod mounting

The normal device state is a read-only `ifuse` mount.

A typical operator flow is:

```bash
ipod-sync mount-ro
ipod-sync doctor
ipod-sync plan
```

The device should return to read-only state after any synchronization attempt,
including failure and rollback paths.

### Native synchronization envelope

The package contains a native helper used for the iTunes-style synchronization
envelope required by the target device.

Installed layout includes:

```text
/usr/lib/ipod-sync/native/sync-envelope
```

The transaction enters the native synchronization envelope before committing
the media/database update and closes the envelope during transaction shutdown.

This native boundary is treated as part of the transaction, not as an
independent best-effort operation.

### Bundled libgpod

The project builds and packages a captured, patched libgpod source tree.

The runtime copy is isolated below:

```text
/usr/lib/ipod-sync/vendor/libgpod/
```

The bundled source preserves its upstream licensing notices.

The build contains compatibility handling for newer `libplist` pkg-config
module naming while leaving the captured upstream libgpod configure logic
unchanged.

Runtime ELF dependencies are generated from the actual packaged binaries using
`dpkg-shlibdeps`, allowing host builds to map SONAME requirements to the
appropriate distribution package names.

## Planning versus applying

The planner and writer are deliberately separate stages.

A normal planning operation:

```text
scan source
    |
hash source content
    |
inspect device database/media
    |
match content
    |
calculate ADD set
    |
calculate required capacity
    |
emit plan
```

No writable iPod mount is required for this process.

An apply transaction begins only after the plan and preflight gates succeed.

## Apply transaction

The current transaction model follows this order at a high level:

```text
1. preflight
2. capture backup/preimage state
3. create recovery journal
4. remount device writable
5. verify live preimage
6. start native synchronization envelope
7. re-check each source immediately before use
8. write planned media
9. verify candidate media hashes/state
10. verify the database preimage has not drifted
11. replace/commit database artifacts
12. close native synchronization envelope
13. restore device read-only
14. perform post-commit validation
15. mark transaction committed
16. clear recoverable transaction state
```

Several of these stages intentionally repeat earlier checks. The repeated
checks protect against time-of-check/time-of-use changes between planning and
commit.

## Source revalidation

A source file that was valid during planning is not automatically trusted later
during the write transaction.

Before using a planned source object, the transaction revalidates the source
state. This prevents silently writing different content if the source changed
between plan generation and execution.

Although the configured source should already be kernel read-only, the
transaction does not rely on that assumption alone.

## Media writes

New media is allocated to the iPod music directory structure.

Where a source format cannot be stored directly in the required form, the
project can create an MP3 transaction output without modifying the original
source.

Written media is validated by readback/hash checks before the overall
transaction can be considered successful.

## Database commit

The project prepares candidate database state before replacing the live device
database artifacts.

The database preimage is verified again immediately before the replacement
boundary. If the live database changed unexpectedly, the transaction fails
closed rather than overwriting unknown state.

A transaction is not considered successful merely because files were copied.
Database validation is part of the commit criteria.

## Recovery journal

Write transactions use durable recovery state.

The journal records enough transaction phase/state for recovery logic to
distinguish known recoverable states from unknown states.

Unknown or non-recoverable journal phases fail closed.

Recovery has two intentionally different interfaces:

```bash
ipod-sync sync --recover-check
ipod-sync sync --recover
```

`--recover-check` is a read-only inspection path. It must not clear recovery
state or perform recovery writes.

`--recover` is the explicit recovery path used when durable cleanup or rollback
is required.

## Rollback

If the transaction fails after entering a writable phase, the recovery model
attempts to restore the validated pre-transaction state where appropriate.

Rollback is not allowed to silently assume success. Snapshot/preimage identity,
database state, media state, transaction phase, and final mount state are part
of the safety model.

The final goal after both successful transactions and handled failures is a
read-only device.

## Commit definition

A synchronization operation is considered committed only after the required
media/database state has been written and validated.

The project therefore distinguishes:

```text
files copied
```

from:

```text
transaction committed
```

A successful commit includes post-write validation and read-only restoration.

## Diagnostics

`doctor` is the main operational diagnostic command:

```bash
ipod-sync doctor
```

It checks relevant runtime dependencies and safety conditions, including the
configured source, device/mount state, packaged components, connection state,
and recovery state.

`doctor` is intended to identify unsafe or incomplete operating conditions
before a synchronization attempt.

## Package architecture

The Debian package contains the Python CLI, native synchronization helper,
bundled libgpod runtime, documentation, and package lifecycle scripts.

A simplified installed layout is:

```text
/usr/bin/ipod-sync
/usr/lib/ipod-sync/ipod_sync.py
/usr/lib/ipod-sync/native/sync-envelope
/usr/lib/ipod-sync/vendor/libgpod/
/usr/share/doc/ipod-sync/
```

The build process audits package contents, runtime linkage, version identity,
privacy-sensitive paths/fingerprints, bytecode/cache leakage, and other
release invariants.

## CI architecture

The canonical release environment remains Debian 11 amd64.

The main CI pipeline currently validates:

```text
Public source sanity — Python 3.9

Debian 11 package build + audit
Debian 11 reproducibility gate
Debian 11 package lifecycle

Ubuntu host compatibility — ubuntu-24.04
Ubuntu host compatibility — ubuntu-26.04

GitHub artifact attestations
```

Debian 11 provides the reproducible release artifact baseline.

Ubuntu 24.04 and Ubuntu 26.04 validate source compilation, host-specific
shared-library dependency generation, package auditing, and install/reinstall/
remove lifecycle for packages built on those hosts.

Those Ubuntu jobs do not represent real-device validation.

## Reproducible release artifacts

The Debian release build is designed to be deterministic.

The CI release bundle contains:

```text
ipod-sync_<debian-version>_amd64.deb
ipod-sync_<debian-version>_amd64.spdx.json
PROVENANCE.json
SHA256SUMS
```

The reproducibility gate independently rebuilds and byte-compares the release
outputs.

The GitHub attestation job creates provenance for the audited artifacts and an
SPDX attestation bound to the Debian package.

## Automated release boundary

Release publication is separate from normal CI.

The manual `Release` workflow:

```text
.github/workflows/release.yml
```

does not rebuild release binaries.

Instead, it locates the exact successful normal-CI run for the current `main`
commit and downloads the already-tested CI artifacts.

This preserves the important invariant:

> The bytes published in a release are the bytes that passed release CI.

Publication then passes through the protected `release` GitHub Environment.

The release workflow creates an annotated tag, publishes an immutable
prerelease, downloads the published assets again, and verifies checksums and
attestations.

See [RELEASE-RUNBOOK.md](RELEASE-RUNBOOK.md) for the operator procedure.

## Real-device validation boundary

The proven real-device baseline is:

```text
iPod touch 2nd generation
iOS 4.2.1
Debian 11 host environment
```

The generic incremental ADD path has been exercised end-to-end on that device,
including a non-MP3 source requiring conversion.

Host/package CI on other distributions must not be interpreted as equivalent
to real-device testing.

## Current non-goals

The current architecture does not claim support for:

- delete synchronization;
- generic rename synchronization;
- modification of existing-track metadata;
- playlist management;
- arbitrary Apple device generations;
- cross-distribution reuse of one binary package.

These can be added in the future, but they are intentionally outside the
current proven write surface.

## Safety summary

The key invariants are:

```text
source stays read-only
device normally stays read-only
planning is read-only
writes require the apply path
content matching uses SHA-256
source is revalidated before use
database preimage is checked before replacement
transactions have durable recovery state
unknown recovery state fails closed
media/database results are validated
device returns to read-only state
release artifacts are reproducible and attested
published release bytes come from exact green CI
```

These constraints are more important than expanding synchronization features.

## Artifact privacy boundary

Public-source validation, package auditing, CI artifact publication, and release
publication share one canonical privacy policy implemented by
`tools/privacy-scan.py`.

The release path is intentionally ordered as:

```text
source validation
    ↓
build
    ↓
package audit
    ↓
SBOM / provenance / checksum generation
    ↓
complete artifact privacy scan
    ↓
CI artifact upload
    ↓
reproducibility and lifecycle verification
    ↓
release-bundle construction
    ↓
release-bundle privacy scan
    ↓
publication
    ↓
fresh download
    ↓
published-artifact privacy scan and integrity verification
```

The privacy boundary scans both container bytes and relevant expanded content.
For Debian packages this includes the raw `.deb`, package payload, and control
metadata. Supported tar and ZIP archives are inspected member-by-member without
extracting them into the source tree.

Filesystem symlinks are not followed. Link names and link targets are scanned as
data instead. This prevents the privacy scanner from crossing the source
boundary through a symlink.

The scanner reports rule names and logical artifact locations without printing
the matched secret or private value itself.

A privacy scan failure prevents subsequent artifact upload or release
publication. The configured source music filesystem is never used for staging
or scanner state and remains subject to the kernel read-only source invariant.
