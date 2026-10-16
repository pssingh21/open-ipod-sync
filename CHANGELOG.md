# Changelog

All notable public changes to `open-ipod-sync` will be documented here.

## Unreleased

## 0.2.0-alpha.9 — 2026-10-16

Ubuntu 26.04 bundled-ifuse safety and installation update.

### Packaging
- Bundle pinned upstream `ifuse` 1.2.1 privately in the Ubuntu
  26.04 amd64 package, built from corresponding upstream source.
- Select the private executable automatically; users installing
  the Ubuntu release `.deb` no longer need manual `ifuse`
  remediation through `prepare-host.sh`.
- Replace the Ubuntu package's system-`ifuse` dependency with
  `fuse3` and generated ELF runtime dependencies.
- Preserve Debian 11 system-ifuse packaging behavior.

### Security
- Embed mandatory bundled-ifuse policy independently in the
  Bash launcher and Python runtime.
- Refuse missing, invalid, or unexpected private executable
  and policy-marker states rather than falling back to
  system `ifuse`.
- Audit private executable version, permissions, ELF hardening,
  dynamic linkage, licensing notice, and package policy.
- Add regression tests for unsafe executable overrides,
  missing policy markers, and tampered package policy.

### Verification
- Extend Ubuntu package lifecycle tests to validate private
  `ifuse` selection without host preparation.
- Retain independent Debian and Ubuntu reproducibility,
  supply-chain attestation, privacy, and release-verification gates.
- Preserve the strict read-only music-source boundary,
  ADD-only synchronization semantics, and explicit `--apply`
  authorization for device writes.
- No live device-write validation is claimed for the
  alpha.9 release artifact itself.

## 0.2.0-alpha.8 — 2026-10-16

First dual-platform Debian 11 and Ubuntu 26.04 amd64 package release.

### Release engineering

- Publish separate Debian 11 and Ubuntu 26.04 packages from the same verified source commit.
- Publish the exact 14-asset release contract with platform-specific packages, SPDX documents, provenance, build materials, toolchain evidence, a shared source archive, and checksums.
- Require pinned reproducibility checks, privacy validation, signed GitHub attestations, and independent offline and online consumer verification.
- Preserve immutable-release publication, protected environment approval, and fail-closed release checks.
- Preserve the strictly read-only NAS source invariant and existing ADD-only device-write behavior.

### Security

- Reject upstream `ifuse` 1.2.0 before trusting an existing iPod mount or
  creating/remounting an `ifuse` filesystem. Upstream identifies 1.2.0 as
  having a serious data-corruption bug fixed in 1.2.1.
- Require repeated byte-stable reads of live Apple SQLite databases before
  accepting database-integrity results.
- Report an unsafe `ifuse` runtime as `UNSAFE` / `NOT READY` from
  `ipod-sync doctor`.

### Compatibility

- Add `tools/prepare-host.sh` so Debian/Ubuntu source-build users can prepare the complete host runtime from the repository. The helper automatically replaces the known-unsafe Ubuntu 26.04 `ifuse` 1.2.0 runtime with pinned upstream 1.2.1 under `/usr/local`, while keeping networked host preparation outside the reproducible package-build boundary.

- Add an explicit Ubuntu 26.04 CI contract for the distro-provided
  `ifuse` 1.2.0-2 hazard: prove that it is rejected, install upstream
  1.2.1 under `/usr/local`, prove that the safe runtime is selected, and
  then run package lifecycle validation.
- Preserve Ubuntu 24.04 compatibility with its older 1.1.4 `ifuse` line.
- Keep the Debian package dependency as plain `ifuse`; runtime safety is
  enforced by `open-ipod-sync` rather than an unsatisfiable
  `ifuse (>= 1.2.1)` package dependency on Ubuntu 26.04.

### Fixed

- Corrected the bundled libgpod 0.8.3 `PlayCounts.plist` parser to address inline `GValue` elements correctly, preventing a `libgpod-add` segmentation fault during candidate parsing.

## 0.2.0-alpha.7 — 2026-10-14

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

Alpha.7 contains packaging, CI, portability, and release-engineering
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
