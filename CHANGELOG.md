# Changelog

All notable public changes to `open-ipod-sync` will be documented here.

## 0.2.0-alpha.7 — Unreleased

Host compatibility and binary-packaging portability hardening.

### Added

- Ubuntu 24.04 amd64 and Ubuntu 26.04 amd64 CI compatibility jobs.
- Host-built Debian-package audit and install/reinstall/remove lifecycle
  validation on both supported Ubuntu CI hosts.
- Host-specific ELF shared-library dependency generation using
  `dpkg-shlibdeps`.

### Changed

- The build now supports modern `libplist-2.0` pkg-config naming through a
  build-local compatibility alias when the historical `libplist` module name
  is unavailable.
- ELF ABI dependencies are generated from the actual packaged native binaries
  instead of hard-coding Debian 11 runtime package names.
- Debian 11 remains the canonical reproducible release environment, while
  Ubuntu compatibility packages are built against their respective host ABI
  and package sets.

### Validated

- Public source sanity, native compilation, package audit, and package
  lifecycle all pass on Ubuntu 24.04 amd64 and Ubuntu 26.04 amd64.
- Debian 11 package build, audit, reproducibility, lifecycle, SBOM,
  provenance, and GitHub artifact-attestation gates continue to pass.
- Host dependency generation resolves the appropriate distribution package
  names while preserving the actual ELF SONAME requirements.

### Release intent

Alpha.7 currently contains packaging, CI, portability, and release-engineering
hardening only. It does not add new synchronization write behavior.

Real-device validation remains based on the existing Debian 11 development
environment. No real-device write transaction has yet been performed with an
alpha.7 artifact.

## 0.2.0-alpha.6 — 2026-10-14

Read-only automation, diagnostics, temporary-file safety, and supply-chain
hardening update.

### Added

- Machine-readable `ipod-sync plan --json` output with a versioned schema,
  synchronization safety flags, planned ADD tracks, media-byte totals,
  candidate hashes, and destination information.
- Read-only JSON planner regression coverage for both new-track and no-op plans.
- Deterministic SPDX 2.3 JSON SBOM generation for the audited Debian package.
- Deterministic `PROVENANCE.json` metadata binding the Debian artifact, source
  commit, `SOURCE_DATE_EPOCH`, generated SBOM, bundled libgpod patch, and
  selected packaged-component hashes.
- GitHub/Sigstore-backed SLSA build-provenance attestations for the Debian
  package, SPDX SBOM, `PROVENANCE.json`, and `SHA256SUMS`.
- SPDX 2.3 SBOM attestation bound directly to the Debian package.

### Changed

- `ipod-sync doctor` now uses the authoritative Python diagnostics path and
  reports dependencies, packaged components, source safety, iPod mount state,
  device connection state, recovery state, and overall readiness.
- Replaced the patched libgpod SQLite exporter's unsafe `tmpnam()` temporary
  path creation with GLib temporary-directory creation.
- Deduplicated the pinned Debian 11 CI setup while preserving the existing
  snapshot, build, reproducibility, and lifecycle gates.
- The Debian reproducibility gate now independently regenerates and
  byte-compares the package, SPDX SBOM, provenance metadata, and
  `SHA256SUMS`.
- GitHub attestation signing permissions are isolated to a post-gate,
  `main`-branch-only job.

### Validated

- Real-device `plan --json` completed successfully against the configured
  kernel-read-only NAS source and read-only `ifuse` iPod mount with an
  idempotent zero-ADD result.
- Real-device JSON planning produced valid JSON, emitted no stderr, armed no
  synchronization transaction journal, and left both mounts read-only.
- The real Debian package SBOM and provenance were generated twice and verified
  byte-for-byte identical.
- The post-merge GitHub Actions attestation path was verified with the GitHub
  CLI for SLSA provenance and the SPDX 2.3 SBOM predicate, including GitHub
  repository/workflow identity and GitHub-hosted runner policy.

### Release intent

Alpha.6 strengthens read-only inspection and automation and adds verifiable
release supply-chain metadata. It does not add any new synchronization
write behavior.

Synchronization remains generic incremental ADD-only. Delete synchronization,
rename synchronization, and metadata updates for existing tracks remain out of
scope.

A fresh live ADD transaction has not yet been performed with the exact
`0.2.0-alpha.6` release artifact.

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
