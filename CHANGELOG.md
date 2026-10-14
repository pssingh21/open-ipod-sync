# Changelog

All notable public changes to `open-ipod-sync` will be documented here.

## 0.2.0-alpha.5 — 2026-10-14

Safety, reproducibility, CI, package-validation, and recovery-hardening update.

### Added

- GitHub Actions CI for public-source sanity validation.
- Automated Debian 11 package build and package-content auditing.
- Automated byte-for-byte Debian package reproducibility gate.
- Automated Debian package lifecycle testing for install, configuration
  preservation, reinstall/upgrade behavior, and package removal.
- Synthetic planner integration coverage for content matching, duplicate-content
  multiplicity, destination allocation, and fail-closed planner behavior.
- Transaction-safety regression coverage for source revalidation, destination
  collisions, media-copy verification, live-preimage drift, rollback snapshot
  integrity, and pre-write recovery invariants.
- Synthetic `apply_transaction()` orchestration coverage, including ordering of
  preflight barriers, writable remounts, source rechecks, media writes, database
  commit checks, rollback paths, and read-only restoration.
- Recovery-state-machine regression coverage.
- CLI safety-routing coverage for dry-run, `--apply`, `--recover`,
  `--recover-check`, conflicting flags, and active-journal blocking.

### Changed

- Pinned GitHub Actions runner selection to Ubuntu 24.04.
- Pinned GitHub Actions dependencies to immutable commit SHAs.
- Pinned the Debian 11 CI container to an immutable OCI digest.
- Pinned Bullseye CI package installation to the Debian snapshot from
  2026-08-30 and added retry handling for transient snapshot failures.
- Made Debian package timestamps deterministic using `SOURCE_DATE_EPOCH`.
- Made Git-derived reproducible-build epoch detection fail closed.
- Normalized package-tree timestamps before `dpkg-deb` assembly.
- Unknown or non-recoverable transaction journal phases now fail closed instead
  of being interpreted as an already-completed rollback state.

### Validated

- The Debian package is independently rebuilt twice in the pinned CI environment
  and required to be byte-for-byte identical.
- Package payload ownership, runtime linkage, versioning, privacy fingerprints,
  bytecode/cache absence, stripped ELF state, and configuration-management
  behavior are audited automatically.
- The safety-critical planner, transaction, recovery, and CLI routing paths are
  exercised using temporary synthetic source/device trees without requiring a
  real iPod.

### Release intent

Alpha.5 hardens the public release and synchronization safety infrastructure.
It does not expand synchronization beyond the existing generic incremental
ADD-only scope.

A fresh live ADD transaction has not yet been performed with the exact
`0.2.0-alpha.5` release artifact.

## 0.2.0-alpha.4 — 2026-10-14

Release-integrity and provenance update.

### Changed

- Bumped runtime version to `0.2.0-alpha.4`.
- Bumped Debian package version to `0.2.0~alpha4`.
- Align the explicit source release archive with the public Git repository.
- Align published checksum filenames with GitHub release-asset naming.
- Preserve the validated ADD-only synchronization behavior from alpha.3.

### Release intent

Alpha.4 is intended to establish a clean release baseline where the Git tag,
public source tree, explicit source archive, Debian package, and checksums all
correspond to the same public release.

No new device-write behavior is introduced in this release.

## 0.2.0-alpha.3 — 2026-10-14

First public experimental release candidate.

### Added

- Generic incremental ADD-only synchronization.
- Content-hash based matching of source tracks against the device library.
- Duplicate-content multiplicity handling.
- Streaming conversion of unsupported source formats such as WMA to MP3.
- Native iTunes-style synchronization envelope.
- Hash72-compatible CDB signing derived from the current device state.
- Full device media SHA-256 readback after synchronization.
- Fail-closed rollback and recovery handling.
- Kernel read-only source-filesystem barrier.
- Read-only iPod mounting outside explicitly authorized write transactions.
- `ipod-sync doctor`.
- `ipod-sync plan`.
- `ipod-sync mount-ro`.
- `ipod-sync recover-check`.
- Public source sanity/privacy checks.
- Modified libgpod 0.8.3 source plus a reviewable patch.
- Debian package build workflow.

### Validated

The generic incremental ADD path was live-tested during development on:

- Debian 11 amd64
- iPod touch 2nd generation
- iOS 4.2.1

The public `0.2.0-alpha.3` package was additionally validated for:

- privacy-clean package contents;
- root-owned package payload;
- clean libgpod rebuild;
- upgrade from the validated `0.1.6` package;
- configuration preservation;
- runtime dependency/component discovery;
- real-device read-only planning;
- idempotent no-op planning with all source tracks already present.

### Limitations

- Experimental alpha.
- ADD-only.
- No delete synchronization.
- No rename synchronization.
- No metadata updates for existing tracks.
- Artwork support disabled.
- Other devices and host distributions are not yet validated.
- The exact `0.2.0-alpha.3` artifact has not yet performed a fresh live ADD transaction.
