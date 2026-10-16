# open-ipod-sync release runbook

This runbook describes the human procedure for publishing a future
`open-ipod-sync` alpha release using the automated Release workflow.

The release workflow is intentionally manual and fail-closed.

Normal pushes and pull requests cannot publish a release.

## Release model

The high-level process is:

```text
development on main
       |
       v
release-prep PR
       |
       v
merge to main
       |
       v
normal CI green for exact merge SHA
       |
       v
manual Release workflow dispatch
       |
       v
automated preflight
       |
       v
release Environment approval
       |
       v
annotated tag
       |
       v
immutable GitHub prerelease
       |
       v
fresh asset download + verification
```

## Important properties

The release system is designed to enforce the following:

- releases originate only from the current `main` HEAD;
- the application, Debian package, README, and changelog version must agree;
- the normal CI run for that exact commit must already be complete and green;
- all required CI jobs must have succeeded;
- release binaries are downloaded from normal CI rather than rebuilt;
- the CI bundle checksum manifest must verify before publication;
- existing SLSA/SPDX attestations must verify before publication;
- the repository must have immutable releases enabled;
- an existing release tag causes failure;
- an existing GitHub Release causes failure;
- release assets are never overwritten with `--clobber`;
- publication requires the protected `release` Environment;
- the release tag is annotated and targets the exact release commit;
- published assets are downloaded again and verified after publication.

## Before starting a release

Do not dispatch the Release workflow directly from an ordinary development
commit.

First prepare the release state through a normal pull request.

For a hypothetical release:

```text
0.2.0-alpha.8
```

the source tree should identify:

```text
application: 0.2.0-alpha.8
Debian:      0.2.0~alpha8
```

The README should identify `0.2.0-alpha.8` as the current release.

The changelog heading should be dated, for example:

```text
## 0.2.0-alpha.8 — 2026-10-16
```

It must no longer say `Unreleased`.

## Step 1: prepare the release PR

Create a release-prep branch from current `main`.

The release-prep PR should contain only the changes required to make the
repository release-ready, such as:

- final version identity;
- dated changelog entry;
- current-release README state;
- release-specific installation/verification examples.

Do not use the release-prep PR to introduce unrelated feature changes.

Allow the normal PR checks to complete.

All required checks must be green before merge.

## Step 2: merge the release-prep PR

Merge the release-prep PR to `main` using the normal repository merge policy.

Then update the local checkout:

```bash
git switch main
git pull --ff-only
```

Confirm the worktree is clean:

```bash
git status --short
```

There should be no output.

## Step 3: wait for exact main CI

The merge to `main` starts the normal CI workflow.

The Release workflow does not substitute for this CI run.

The exact release commit must first pass the normal gates:

```text
Public source sanity — Python 3.9

Debian 11 package build + audit
Debian 11 reproducibility gate
Debian 11 package lifecycle

Ubuntu host compatibility — ubuntu-24.04
Ubuntu host compatibility — ubuntu-26.04

GitHub artifact attestations
```

Do not dispatch the Release workflow until the exact release-prep merge commit
has a successful main CI run.

## Step 4: dispatch the Release workflow

For example:

```bash
gh workflow run Release \
  --repo pssingh21/open-ipod-sync \
  --ref main \
  -f version=0.2.0-alpha.8
```

The version input uses the application/release form:

```text
0.2.0-alpha.8
```

Do not pass the Debian form:

```text
0.2.0~alpha8
```

The workflow derives the Debian and public asset forms automatically.

## Step 5: monitor preflight

Find the workflow run:

```bash
gh run list \
  --repo pssingh21/open-ipod-sync \
  --workflow Release \
  --limit 5
```

Then monitor the selected run:

```bash
gh run watch <RUN_ID> \
  --repo pssingh21/open-ipod-sync
```

The first job is:

```text
Release preflight
```

Preflight checks include:

- workflow was dispatched from `main`;
- dispatch SHA still equals current `main`;
- release version format is valid;
- runtime version matches;
- Debian version matches;
- README current release matches;
- changelog contains exactly one dated release heading;
- changelog is no longer marked `Unreleased`;
- release tag does not already exist;
- GitHub Release does not already exist;
- immutable releases are enabled;
- exact normal-CI run exists for the release SHA;
- required normal-CI jobs succeeded;
- exact CI artifact bundle can be downloaded;
- CI `SHA256SUMS` verifies;
- expected Debian/SPDX/provenance assets exist;
- artifact version matches;
- provenance references the release SHA;
- SLSA/SPDX attestations verify.

If preflight fails, do not attempt to bypass it.

Fix the release-prep/source/workflow problem through the normal PR process and
dispatch a new release run.

## Step 6: approve the release Environment

After preflight succeeds, the publication job targets the protected GitHub
Environment:

```text
release
```

GitHub pauses the workflow for approval.

Review the pending deployment in the GitHub Actions UI and approve it only if:

- the requested version is correct;
- the release commit SHA is correct;
- preflight succeeded;
- the expected normal-CI run succeeded.

Approval is the human publication boundary.

## Step 7: publication

After approval, the workflow revalidates the boundary.

It checks again that:

- the workflow is still associated with `main`;
- `main` has not moved since dispatch;
- the tag has not appeared unexpectedly;
- the release has not appeared unexpectedly;
- the prepared release manifest still verifies.

Only then does it create the annotated tag.

For release `0.2.0-alpha.8` the tag is:

```text
v0.2.0-alpha.8
```

The tag must peel to the exact release commit.

The workflow then publishes the prerelease using the verified CI artifacts.

## Published assets

The public release contains exactly **14 assets**: six
distribution-specific files for Debian 11, six for Ubuntu 26.04,
one shared deterministic source archive, and one combined checksum manifest.

For `0.2.0-alpha.8`, the asset names are:

```text
ipod-sync_0.2.0.alpha8_amd64.deb
ipod-sync_0.2.0.alpha8_amd64.spdx.json
PROVENANCE.json
BUILD-MATERIALS.json
TOOLCHAIN.json
CI-SHA256SUMS
ipod-sync-ubuntu2604_0.2.0.alpha8_amd64.deb
ipod-sync-ubuntu2604_0.2.0.alpha8_amd64.spdx.json
UBUNTU2604-PROVENANCE.json
UBUNTU2604-BUILD-MATERIALS.json
UBUNTU2604-TOOLCHAIN.json
UBUNTU2604-CI-SHA256SUMS
open-ipod-sync-<release-commit>-source.tar
SHA256SUMS
```

The source archive name contains the exact 40-character release commit SHA.

Both distribution bundles originate from the same successful
`main` CI run. The Release workflow authenticates the CI artifacts
and reuses their bytes without rebuilding the packages.

The combined `SHA256SUMS` covers the other 13 public assets.
The two CI checksum manifests preserve the original CI artifact
names and hashes.

Release notes are transferred separately and are not a fifteenth
public release asset.

## Step 8: automatic post-publication verification

Publication is not considered complete when `gh release create` returns.

The final job is:

```text
Verify published release
```

It downloads all 14 published assets again from GitHub and verifies:

- the exact 14-file asset set, without duplicates or extra assets;
- the combined release checksums;
- the original Debian consumer-verification guarantees;
- Ubuntu provenance, SPDX, pinned build-material, and source identity;
- the immutable prerelease and annotated tag's source commit;
- GitHub CI attestations for the signed artifact bytes;
- separate Debian and Ubuntu SPDX package attestations;
- the expected `main` source digest and signing workflow.

The published directory is privacy-scanned before independent
GitHub authenticity verification.

A successful run ends with:

```text
AUTOMATED RELEASE: COMPLETE + VERIFIED
```

Only at this point should the release be treated as complete.

## Step 9: optional human confirmation

The automated workflow is authoritative, but a human can still confirm:

```bash
gh release view v0.2.0-alpha.8 \
  --repo pssingh21/open-ipod-sync
```

The expected state is:

```text
draft:      false
prerelease: true
immutable:  true
```

The tag should be annotated and point to the exact release-prep merge commit.

## Failure handling

### Failure before the tag is created

This is the simplest failure mode.

Do not modify GitHub state manually.

Correct the source/workflow/release-prep issue through a PR, obtain a new green
`main` commit, and dispatch the workflow again.

### Tag exists but release publication failed

Do not immediately delete, force-update, or recreate the tag.

First establish:

```text
tag object
tag peeled commit
expected release commit
normal CI run
workflow failure point
```

The release workflow deliberately refuses ambiguous existing state.

Investigate the failure before deciding on remediation.

Never force-push an existing release tag.

### Immutable release already published

An immutable published release is final.

Do not attempt to replace assets or move its tag.

If a defect is discovered after publication, fix the defect in a new commit
and publish a new version.

For example:

```text
bad/obsolete: 0.2.0-alpha.8
fixed:        0.2.0-alpha.9
```

Preserving the historical release is preferable to mutating published bytes.

### Version mismatch

If the Release workflow reports a version mismatch, inspect all four identities:

```text
src/ipod_sync.py
build-deb.sh
README.md
CHANGELOG.md
```

Do not weaken the workflow to accept inconsistent versions.

Fix the release-prep state instead.

### Main moved after dispatch

The workflow intentionally fails if `main` changes between dispatch and the
publication boundary.

This prevents a release approval from silently publishing a different
repository state than the one originally reviewed.

Prepare/verify the new `main` state and dispatch another Release run.

## Things not to do

Do not:

- publish on every push to `main`;
- automatically publish every merged PR;
- rebuild a different binary during release publication;
- use `--clobber` for release assets;
- force-update a release tag;
- bypass failed preflight checks;
- bypass normal main CI;
- publish from a feature branch;
- publish from a stale `main` commit;
- treat an immutable published release as editable.

## Relationship to normal CI

Normal CI answers:

> Is this exact source commit buildable, safe according to the test suite,
> reproducible, package-valid, and attested?

The Release workflow answers:

> Is this exact already-green commit in a valid release state, and can the exact
> CI-tested bytes be safely published and independently verified?

Keeping these responsibilities separate reduces the amount of privileged code
in the release path.

## Current release baseline

`v0.2.0-alpha.7` was published and verified before the automated Release
workflow was installed.

Do not dispatch the automated workflow for alpha.7.

The workflow is intended for subsequent releases.

## Minimal operator checklist

For future releases, the human checklist is intentionally short:

```text
[ ] release-prep PR contains the intended release state
[ ] PR checks green
[ ] release-prep PR merged to main
[ ] exact main CI green
[ ] dispatch Release workflow with correct version
[ ] preflight green
[ ] approve release Environment
[ ] wait for AUTOMATED RELEASE: COMPLETE + VERIFIED
```

If all eight items are satisfied, release publication is complete.

<!-- PR4_REPRO_GATE_INTERPRETATION_BEGIN -->
## Interpreting the reproducibility gate

A green **Debian 11 reproducibility gate** means that the audited release
package has been independently reconstructed from a deterministic committed
source archive and has survived all of the following checks:

- no `.git` metadata is present in the rebuild source;
- Git execution is disabled during the extracted-source rebuild;
- two deliberately different build environments produce identical output;
- socket/network syscalls are kernel-denied during the comparison builds;
- the ambient environment and developer-local executable lookup paths are
  excluded;
- the declared toolchain consists of Debian-package-owned executables;
- recorded build-material and toolchain manifests agree between builders; and
- the `.deb`, SPDX SBOM, provenance, and checksum manifest are byte-identical.

For release review, this demonstrates strong reproducibility and build-input
control. It does **not** assert a filesystem-read sandbox: comparison-build
processes can still read operating-system files supplied by the pinned Debian
environment and can execute explicitly named absolute system paths.

If the reproducibility gate fails, do not publish a release until the differing
source identity, material identity, toolchain identity, metadata, or package
bytes have been explained and the gate is green again.
<!-- PR4_REPRO_GATE_INTERPRETATION_END -->

<!-- CONSUMER_RELEASE_RUNBOOK_BEGIN -->
## Independent consumer verification contract

The new release workflow has an **exact fourteen-asset contract**: two `.deb`
packages, two SPDX SBOMs, four Debian evidence files, four Ubuntu evidence
files, a byte-identical deterministic source archive and `SHA256SUMS`.
See the README's complete filenames. The existing alpha.7 release remains an
historical eight-asset release and is not modified.

### CI evidence entering the release workflow

Both CI bundles contain exactly seven files: one package, one SPDX, source
archive, provenance, build materials, toolchain and `SHA256SUMS`. Both must be
sourced from the same successful `main` CI run and every original CI subject
must have a valid GitHub artifact attestation. Each package additionally
requires its own SPDX attestation. The Ubuntu bundle must match the pinned
Ubuntu build identity and snapshot. Public filenames are normalized while
the original bytes and evidence identities are preserved.

### Release preflight requirements

The workflow requires its exact main CI SHA and all required jobs to succeed,
checks tag and release absence, source identity, immutable-release settings,
CI checksums, provenance, package metadata, privacy and signed attestations.
It assembles and offline-verifies an exact fourteen-asset candidate. No tag or
public release is created during preflight.

### Building the immutable public bundle

The protected publish job retrieves the already-verified preflight candidate,
extracts `RELEASE-NOTES.md` outside the fourteen-asset release directory,
rechecks current `main`, tag absence, all fourteen assets, checksums and privacy,
then creates the annotated tag and publishes the exact assets through the
existing Release workflow. The public `SHA256SUMS` covers exactly thirteen
payload files and is not itself CI-attested.

### Post-publication verification

A separate read-only job downloads all public assets afresh and runs the
independent consumer verifier (not preflight workspace copies):

```bash
python3 tools/verify-dual-release-github.py \
  published \
  --expected-commit "$GITHUB_SHA" \
  --repo "$GITHUB_REPOSITORY" \
  --tag "$TAG"
```

This verifies the exact fourteen-file set, SHA256SUMS, both platforms' identity
and build evidence, immutable release status, tag-to-commit binding, each GitHub
release asset digest, 13 CI subject attestations and both SPDX attestations.
The historical eight-asset consumer verifier is `tools/verify-release.py`.

### Consumer verification procedure

Consumers can download a *published* dual-platform release with `gh release
download` and independently run `tools/verify-dual-release.py` offline with a
known expected commit, or `tools/verify-dual-release-github.py` online with the
repository and tag. Both tools are provided by the release's matching checkout.
Do not use the new contract to retrospectively judge historical alpha.7.

### Failure handling

Missing, extra, unsigned or digest-mismatched assets; provenance/SPDX or build
material identity mismatches; mutable releases; and unexpected tags are hard
failures. Do not bypass verification or mutate an existing immutable release.
Publish a corrected new version/tag through normal review if necessary.

### Trust-boundary statement

Reproducibility evidence is not a claim of a complete filesystem-read sandbox.
All release verification is independent of the original CI workspace and does
not read or modify an iPod, NAS or source-library music. The NAS/source-library read-only invariant is unchanged: no operation may
write, modify, rename or delete source data on the NAS.
<!-- CONSUMER_RELEASE_RUNBOOK_END -->

<!-- REPOSITORY_RELEASE_POLICY_BEGIN -->
## GitHub repository controls around publication

Release publication depends on GitHub controls outside the workflow file itself.

The expected repository policy is documented in
[`REPOSITORY-POLICY.md`](REPOSITORY-POLICY.md).

Before a security-sensitive release, a maintainer can verify those controls
read-only with:

```bash
python3 tools/audit-repository-policy.py
```

The publication boundary expects:

- the `release` environment to require reviewer approval;
- the `release` environment to accept deployments from `main` only;
- repository-level immutable releases to be enabled;
- `refs/tags/v*` creation to remain allowed so the workflow can create the new
  annotated release tag;
- existing `refs/tags/v*` references to reject update/retarget operations;
- existing `refs/tags/v*` references to reject deletion; and
- the release-tag ruleset to have no bypass actors.

Repository-level immutable releases apply to releases created after the
repository setting was enabled. Older releases may therefore legitimately
report `isImmutable=false`. Their historical release metadata is not rewritten.

The `Protect release tags` ruleset still protects those historical `v*` tag
references from future retargeting or deletion.

After a release is published, the workflow independently verifies the release
immutability flag, exact release asset contract, checksums, attestations, and
consumer-verification evidence.
<!-- REPOSITORY_RELEASE_POLICY_END -->
