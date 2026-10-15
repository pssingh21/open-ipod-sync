#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CI = (
    ROOT
    / ".github"
    / "workflows"
    / "ci.yml"
).read_text()

RELEASE = (
    ROOT
    / ".github"
    / "workflows"
    / "release.yml"
).read_text()

VERIFIER = (
    ROOT
    / "tools"
    / "verify-release.py"
).read_text()

README = (
    ROOT
    / "README.md"
).read_text()

RUNBOOK = (
    ROOT
    / "docs"
    / "RELEASE-RUNBOOK.md"
).read_text()


def require(
    text: str,
    token: str,
    label: str,
) -> None:
    if token not in text:
        raise SystemExit(
            f"ERROR: {label} missing required token: "
            f"{token}"
        )


# Canonical CI-originating verification evidence.
for token in (
    'source_name="open-ipod-sync-${git_commit}-source.tar"',
    "ci-artifact/BUILD-MATERIALS.json",
    "ci-artifact/TOOLCHAIN.json",
    "ci-artifact/open-ipod-sync-*-source.tar",
    "baseline/BUILD-MATERIALS.json",
    "baseline/TOOLCHAIN.json",
    "reproducibility-matrix/materials/builder-a.json",
    "reproducibility-matrix/materials/toolchain-a.json",
    "attested/open-ipod-sync-*-source.tar",
    "attested/BUILD-MATERIALS.json",
    "attested/TOOLCHAIN.json",
):
    require(
        CI,
        token,
        "CI workflow",
    )


# Consumer-visible release evidence.
for token in (
    'CI_SOURCE="ci-bundle/open-ipod-sync-${GITHUB_SHA}-source.tar"',
    "ci-bundle/BUILD-MATERIALS.json",
    "ci-bundle/TOOLCHAIN.json",
    'RELEASE_SOURCE="open-ipod-sync-${GITHUB_SHA}-source.tar"',
    "release/BUILD-MATERIALS.json",
    "release/TOOLCHAIN.json",
    '"release/open-ipod-sync-${GITHUB_SHA}-source.tar"',
    'f"open-ipod-sync-{commit}-source.tar"',
    'SOURCE="published/open-ipod-sync-${GITHUB_SHA}-source.tar"',
    'MATERIALS="published/BUILD-MATERIALS.json"',
    'TOOLCHAIN="published/TOOLCHAIN.json"',
):
    require(
        RELEASE,
        token,
        "release workflow",
    )


# The same externally usable verifier must be exercised by release CI.
for token in (
    "Run independent consumer release verifier",
    "python3 tools/verify-release.py",
    "--expected-commit",
    '"$GITHUB_SHA"',
    "--expected-repository",
    '"https://github.com/$GITHUB_REPOSITORY"',
    "--github",
    '--repo "$GITHUB_REPOSITORY"',
    '--tag "$TAG"',
    "independent consumer verification: PASS",
):
    require(
        RELEASE,
        token,
        "release consumer-verification step",
    )


# Consumer verifier schemas / trust layers.
for token in (
    "open-ipod-sync-build-materials-v1",
    "open-ipod-sync-toolchain-view-v1",
    "open-ipod-sync-provenance-v1",
    '"--github"',
    "verify_github_authenticity(",
    '"--signer-workflow"',
    '"--source-digest"',
    '"--source-ref"',
    '"refs/heads/main"',
    '"--deny-self-hosted-runners"',
):
    require(
        VERIFIER,
        token,
        "consumer verifier",
    )


# Internal A/B evidence is intentionally not part of release publication.
for forbidden in (
    "builder-a.json",
    "builder-b.json",
    "toolchain-a.json",
    "toolchain-b.json",
    "reproducibility-matrix",
):
    if forbidden in RELEASE:
        raise SystemExit(
            "ERROR: internal reproducibility evidence "
            f"leaked into release workflow: {forbidden}"
        )


# Keep the existing single audited artifact channels.
if CI.count(
    "uses: actions/upload-artifact@"
) != 1:
    raise SystemExit(
        "ERROR: expected exactly one CI upload-artifact action"
    )

if RELEASE.count(
    "uses: actions/upload-artifact@"
) != 1:
    raise SystemExit(
        "ERROR: expected exactly one release "
        "upload-artifact action"
    )


# The release workflow must still be fail-closed on an exact asset set.
for token in (
    '"CI-SHA256SUMS"',
    '"PROVENANCE.json"',
    '"SHA256SUMS"',
    '"BUILD-MATERIALS.json"',
    '"TOOLCHAIN.json"',
    'f"open-ipod-sync-{commit}-source.tar"',
    'f"ipod-sync_{public_version}_amd64.deb"',
    'f"ipod-sync_{public_version}_amd64.spdx.json"',
):
    require(
        RELEASE,
        token,
        "exact release asset contract",
    )


# Reproducibility checksum manifests intentionally have different scopes.
#
# The audited baseline SHA256SUMS covers six canonical CI payloads, while each
# isolated rebuild SHA256SUMS covers the three reproducible core payloads.
# CI must therefore derive a baseline core manifest rather than compare the
# full baseline checksum manifest byte-for-byte with a rebuild manifest.
for token in (
    "baseline reproducible core should contain exactly three payload files",
    "rebuilt core should contain exactly three payload files",
    "alternate core should contain exactly three payload files",
    "baseline-core-SHA256SUMS",
    "baseline-derived core SHA256SUMS vs builder A: PASS",
    "baseline-derived core SHA256SUMS vs builder B: PASS",
):
    require(
        CI,
        token,
        "reproducibility checksum-scope contract",
    )

if (
    "baseline reproducible core should contain exactly four files"
    in CI
):
    raise SystemExit(
        "ERROR: reproducibility core still treats the "
        "full-scope SHA256SUMS as a core payload"
    )

# Consumer-facing documentation is part of the release contract.
for token in (
    "## Independently verify a release",
    "Every new release publishes enough evidence",
    "exactly these eight assets",
    "BUILD-MATERIALS.json",
    "TOOLCHAIN.json",
    "open-ipod-sync-<40-character-commit>-source.tar",
    "python3 tools/verify-release.py",
    "--expected-commit",
    "--expected-repository",
    "--github",
    "--repo",
    "--tag",
    "offline operation",
    "never reads or modifies the music source directory",
):
    require(
        README,
        token,
        "README consumer verification documentation",
    )

for token in (
    "## Independent consumer verification contract",
    "exact eight-asset contract",
    "CI evidence entering the release workflow",
    "Post-publication verification",
    "independent consumer verifier",
    "Failure handling",
    "immutable release",
    "Trust-boundary statement",
    "NAS/source-library read-only invariant is unchanged",
):
    require(
        RUNBOOK,
        token,
        "release runbook consumer verification documentation",
    )

for forbidden in (
    "fully hermetic build",
    "fully-hermetic build",
):
    if forbidden in README or forbidden in RUNBOOK:
        raise SystemExit(
            "ERROR: documentation contains unsupported "
            f"hermeticity claim: {forbidden}"
        )

print("consumer verification documentation: PASS")

print("canonical consumer evidence in CI: PASS")
print("canonical consumer evidence in release: PASS")
print("internal A/B evidence remains unpublished: PASS")
print("single audited artifact channels: PASS")
print("exact eight-asset release contract: PASS")
print("release workflow dogfoods consumer verifier: PASS")
print("consumer release contract tests: PASS")
