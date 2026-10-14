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
## 0.2.0-alpha.8 — 2026-10-20
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

The public release bundle contains five assets.

For `0.2.0-alpha.8`, these would be:

```text
ipod-sync_0.2.0.alpha8_amd64.deb
ipod-sync_0.2.0.alpha8_amd64.spdx.json
PROVENANCE.json
CI-SHA256SUMS
SHA256SUMS
```

`CI-SHA256SUMS` is the exact manifest produced by normal CI.

`SHA256SUMS` is the release-specific manifest using the public release asset
names.

The `.deb`, SPDX document, provenance file, and CI manifest are copied from the
exact normal-CI artifact bundle.

They are not rebuilt by the Release workflow.

## Step 8: automatic post-publication verification

Publication is not considered complete when `gh release create` returns.

The final job is:

```text
Verify published release
```

It downloads all published assets again from GitHub and verifies:

- release-specific `SHA256SUMS`;
- GitHub signed release attestation;
- release attestation for every individual asset;
- SLSA provenance for the Debian artifact;
- SPDX attestation bound to the Debian artifact;
- SLSA provenance for the SPDX document;
- SLSA provenance for `PROVENANCE.json`;
- SLSA provenance for `CI-SHA256SUMS`.

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
