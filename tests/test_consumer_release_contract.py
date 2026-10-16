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


# Consumer-visible release evidence and independent verifier.
for token in (
    'tools/prepare-dual-release-assets.py',
    'tools/verify-dual-release.py',
    'tools/verify-dual-release-github.py',
    'Release preflight 14-asset candidate: PASS',
    'Approved exact 14-asset publication boundary: PASS',
    'gh release create "$TAG" release/*',
    '--notes-file "$RUNNER_TEMP/RELEASE-NOTES.md"',
    'Run independent dual-platform consumer verifier',
    'independent dual-platform consumer verification: PASS',
):
    require(RELEASE, token, 'dual-platform release workflow')

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


# Permit exactly two audited CI artifact channels:
# the canonical Debian package and Ubuntu 26.04 package.
# The independently verified release artifact channel remains unchanged.
if CI.count(
    "uses: actions/upload-artifact@"
) != 2:
    raise SystemExit(
        "ERROR: expected exactly two CI upload-artifact actions"
    )


# Extract a top-level CI job by its exact YAML indentation.
def extract_ci_job(workflow, job_name):
    lines = workflow.splitlines(keepends=True)
    heading = "  " + job_name + ":"

    matches = [
        index
        for index, line in enumerate(lines)
        if line.rstrip() == heading
    ]

    if len(matches) != 1:
        raise SystemExit(
            f"ERROR: expected exactly one {job_name} job; "
            f"found {len(matches)}"
        )

    begin = matches[0]
    end = len(lines)

    for index in range(begin + 1, len(lines)):
        line = lines[index]

        # Other jobs have exactly two spaces of indentation.
        if (
            line.startswith("  ")
            and not line.startswith("   ")
            and line.strip().endswith(":")
        ):
            end = index
            break

    return "".join(lines[begin:end])


compat_job = extract_ci_job(
    CI, "ubuntu-host-compatibility"
)
ubuntu_job = extract_ci_job(
    CI, "ubuntu2604-reproducibility-check"
)

if "uses: actions/upload-artifact@" in compat_job:
    raise SystemExit(
        "ERROR: compatibility job must not upload Ubuntu package"
    )

if ubuntu_job.count("uses: actions/upload-artifact@") != 1:
    raise SystemExit(
        "ERROR: expected one verified Ubuntu artifact upload"
    )

for token in (
    "Run pinned Ubuntu 26.04 A/B matrix",
    "Prepare verified pinned Ubuntu candidate",
    "Verify pinned Ubuntu candidate for upload",
    "Upload verified pinned Ubuntu package",
    "name: ipod-sync-ubuntu2604-amd64-${{ github.sha }}",
    "path: ${{ runner.temp }}/ubuntu2604-pinned-candidate/",
    "if-no-files-found: error",
    "sha256sum -c SHA256SUMS",
    'python3 tools/privacy-scan.py "$candidate"',
    'test "${#names[@]}" -eq 7',
):
    require(ubuntu_job, token, "verified Ubuntu artifact contract")

if not (
    ubuntu_job.index("Run pinned Ubuntu 26.04 A/B matrix")
    < ubuntu_job.index("Prepare verified pinned Ubuntu candidate")
    < ubuntu_job.index("Verify pinned Ubuntu candidate for upload")
    < ubuntu_job.index("Upload verified pinned Ubuntu package")
):
    raise SystemExit(
        "ERROR: Ubuntu verification and upload order changed"
    )

if "Download independently built Ubuntu package" in ubuntu_job:
    raise SystemExit(
        "ERROR: obsolete Ubuntu baseline download remains"
    )

if RELEASE.count(
    "uses: actions/upload-artifact@"
) != 1:
    raise SystemExit(
        "ERROR: expected exactly one release "
        "upload-artifact action"
    )


# The release must reject missing, extra or duplicate remote assets.
for token in (
    '"CI-SHA256SUMS"',
    '"PROVENANCE.json"',
    '"SHA256SUMS"',
    '"BUILD-MATERIALS.json"',
    '"TOOLCHAIN.json"',
    '"UBUNTU2604-CI-SHA256SUMS"',
    '"UBUNTU2604-PROVENANCE.json"',
    '"UBUNTU2604-BUILD-MATERIALS.json"',
    '"UBUNTU2604-TOOLCHAIN.json"',
    'f"open-ipod-sync-{commit}-source.tar"',
    'f"ipod-sync_{public_version}_amd64.deb"',
    'f"ipod-sync_{public_version}_amd64.spdx.json"',
    'f"ipod-sync-ubuntu2604_{public_version}_amd64.deb"',
    'f"ipod-sync-ubuntu2604_{public_version}_amd64.spdx.json"',
    'len(remote_names) != 14',
):
    require(RELEASE, token, 'exact dual-platform asset set')

assert RELEASE.count('gh release create "$TAG"') == 1
assert RELEASE.count('uses: actions/upload-artifact@') == 1
assert 'gh release upload' not in RELEASE
assert RELEASE.index('Verify exact dual-platform release candidate') < RELEASE.index('Publish prerelease')
assert RELEASE.index('Revalidate publication boundary') < RELEASE.index('Publish prerelease')
assert RELEASE.index('Download published assets fresh') < RELEASE.index('Run independent dual-platform consumer verifier')

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

# Consumer-facing documentation remains part of the contract.
for token in (
    '## Independently verify a release',
    'exactly fourteen assets',
    'UBUNTU2604-PROVENANCE.json',
    'UBUNTU2604-BUILD-MATERIALS.json',
    'ipod-sync-ubuntu2604_<public-version>_amd64.deb',
    'tools/verify-dual-release.py',
    'tools/verify-dual-release-github.py',
    'eight-asset',
    'read-only source invariant',
):
    require(README, token, 'consumer README')
for token in (
    '## Independent consumer verification contract',
    'exact fourteen-asset contract',
    'CI evidence entering the release workflow',
    'Post-publication verification',
    'Failure handling',
    'immutable release',
    'Trust-boundary statement',
    'NAS/source-library read-only invariant is unchanged',
):
    require(RUNBOOK, token, 'release runbook')
for forbidden in ('fully hermetic build', 'fully-hermetic build'):
    assert forbidden not in README and forbidden not in RUNBOOK

import re

# PROTECTED_IMMUTABLE_POLICY_CONTRACT
preflight_job = RELEASE.split(
    "  preflight:", 1
)[1].split("  publish:", 1)[0]

publish_job = RELEASE.split(
    "  publish:", 1
)[1].split("  verify:", 1)[0]

assert "immutable-releases" not in preflight_job

# Enforce the exact protected environment declaration.
# Split into lines to avoid escaped-newline mismatches.
publish_lines = publish_job.splitlines()

environment_heading = "    environment:"
environment_name = "      name: release"

assert publish_lines.count(environment_heading) == 1, (
    "Protected release environment declaration missing or duplicated"
)

environment_index = publish_lines.index(environment_heading)

assert (
    environment_index + 1 < len(publish_lines)
    and publish_lines[environment_index + 1] == environment_name
), "Publication job must use the protected release environment"


policy_heading = (
    "      - name: Verify protected immutable release policy"
)
next_heading = (
    "      - name: Revalidate publication boundary"
)

assert publish_job.count(policy_heading) == 1
assert publish_job.count(next_heading) == 1

policy = publish_job.split(
    policy_heading, 1
)[1].split(next_heading, 1)[0]

for token in (
    "GH_TOKEN: ${{ secrets.RELEASE_POLICY_READ_TOKEN }}",
    '[[ -z "${GH_TOKEN:-}" ]]',
    'set -euo pipefail',
    'gh api',
    'repos/$GITHUB_REPOSITORY/immutable-releases',
    "--jq '.enabled'",
    '[[ "$IMMUTABLE" == "true" ]]',
    "Protected immutable release policy: PASS",
):
    assert token in policy, token

assert (
    publish_job.index(policy_heading)
    < publish_job.index(next_heading)
    < publish_job.index("Create and push annotated tag")
    < publish_job.index("Publish prerelease")
)

assert RELEASE.count(
    "repos/$GITHUB_REPOSITORY/immutable-releases"
) == 1

print("Protected immutable release policy contract: PASS")

# EXECUTABLE_RELEASE_IDENTITY_CONTRACT
import subprocess
import sys
import tempfile
import textwrap

identity_start = "      - name: Validate release identity"
identity_end = "      - name: Locate exact successful main CI run"

assert RELEASE.count(identity_start) == 1
assert RELEASE.count(identity_end) == 1

identity_section = RELEASE.split(
    identity_start, 1
)[1].split(identity_end, 1)[0]

lines = identity_section.splitlines()

python_heading = '          python3 - "$RELEASE_VERSION" <<\'PY\''
python_footer = "          PY"

starts = [
    i for i, line in enumerate(lines)
    if line == python_heading
]

assert len(starts) == 1

ends = [
    i for i in range(starts[0] + 1, len(lines))
    if lines[i] == python_footer
]

assert len(ends) == 1

embedded_python = textwrap.dedent(
    "\n".join(lines[starts[0] + 1:ends[0]]) + "\n"
)

compile(embedded_python, "<release-identity>", "exec")

versions = re.findall(
    r'^VERSION = "([^"]+)"$',
    (ROOT / "src/ipod_sync.py").read_text(),
    re.MULTILINE,
)
assert len(versions) == 1

version = versions[0]
readme = (ROOT / "README.md").read_text()
changelog = (ROOT / "CHANGELOG.md").read_text()

block = (
    "## Current release\n\n"
    "```text\n"
    f"{version}\n"
    "```"
)
assert readme.count(block) == 1

with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)

    def run_identity(readme_content, changelog_content):
        (directory / "README.md").write_text(
            readme_content
        )
        (directory / "CHANGELOG.md").write_text(
            changelog_content
        )
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                embedded_python,
                version,
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )

    valid = run_identity(readme, changelog)
    assert valid.returncode == 0, (
        valid.stdout + valid.stderr
    )
    assert "release documentation identity: PASS" in valid.stdout

    print("Actual alpha release identity: PASS")

    wrong_version = readme.replace(
        block,
        block.replace(version, "9.9.9-alpha.999"),
        1,
    )

    missing_heading = readme.replace(
        "## Current release\n",
        "## Latest version\n",
        1,
    )

    duplicated_heading = readme + "\n" + block + "\n"

    changelog_heading = f"## {version} — "
    assert changelog.count(changelog_heading) == 1

    invalid_changelog = changelog.replace(
        changelog_heading,
        "## 9.9.9-alpha.999 — ",
        1,
    )

    for label, candidate_readme, candidate_changelog in (
        ("incorrect version", wrong_version, changelog),
        ("missing heading", missing_heading, changelog),
        ("duplicate heading", duplicated_heading, changelog),
        ("incorrect changelog", readme, invalid_changelog),
    ):
        result = run_identity(
            candidate_readme,
            candidate_changelog,
        )
        assert result.returncode != 0, (
            f"Release preflight accepted {label}"
        )
        print(f"Release identity rejects {label}: PASS")

print("Executable release identity contract: PASS")

# Dual-platform release gate contract.
# Identify the required CI job set without depending
# on YAML or embedded Python indentation.
import re

matches = re.findall(
    r"required\s*=\s*\{([^{}]*)\}\s*"
    r"missing\s*=\s*required\s*-\s*set\(jobs\)",
    RELEASE,
    flags=re.DOTALL,
)

assert len(matches) == 1, (
    "Expected exactly one release CI required-job set"
)

actual = re.findall(r'"([^"\n]+)"', matches[0])

expected = {
    "Public source sanity — Python 3.9",
    "Debian 11 package build + audit",
    "Debian 11 reproducibility gate",
    "Debian 11 package lifecycle",
    "Ubuntu host compatibility — ubuntu-24.04",
    "Ubuntu host compatibility — ubuntu-26.04",
    "Ubuntu 26.04 independent reproducibility gate",
    "Dual-platform release candidate smoke test",
    "GitHub artifact attestations",
    "GitHub Ubuntu 26.04 pinned artifact attestation",
}

assert len(actual) == len(expected)
assert set(actual) == expected, (
    f"Release CI gate mismatch: {actual}"
)

for check in (
    'if run["headSha"] != expected:',
    'if run["conclusion"] != "success":',
    'if jobs[name] != "success"',
):
    assert check in RELEASE, (
        f"Missing fail-closed release check: {check}"
    )

# UBUNTU_SPDX_ATTESTATION_CONTRACT
ubuntu_attestation_job = CI.split(
    "  attest-ubuntu2604:", 1
)[1]

for token in (
    "id: bundle",
    "Attest Ubuntu package with SPDX SBOM",
    "subject-path: ${{ steps.bundle.outputs.deb }}",
    "sbom-path: ${{ steps.bundle.outputs.sbom }}",
    "Ubuntu SPDX SBOM attestation: PASS",
    "--predicate-type https://spdx.dev/Document/v2.3",
):
    assert token in ubuntu_attestation_job, token

ubuntu_release_step = RELEASE.split(
    "      - name: Verify Ubuntu 26.04 CI bundle and attestations",
    1,
)[1].split(
    "      - name: Prepare immutable release bundle",
    1,
)[0]

for token in (
    "Signed Ubuntu SPDX evidence: PASS",
    "--predicate-type https://spdx.dev/Document/v2.3",
    '--source-digest "$GITHUB_SHA"',
    "--signer-workflow",
    "--deny-self-hosted-runners",
):
    assert token in ubuntu_release_step, token

print("Ubuntu SPDX attestation parity contract: PASS")

# DUAL_PLATFORM_RELEASE_PREFLIGHT_CONTRACT
dual_preflight_heading = (
    "      - name: Verify exact dual-platform release candidate"
)
legacy_preparation_heading = (
    "      - name: Prepare immutable release bundle"
)
ubuntu_verification_heading = (
    "      - name: Verify Ubuntu 26.04 CI bundle and attestations"
)

for heading in (
    ubuntu_verification_heading,
    dual_preflight_heading,
    legacy_preparation_heading,
):
    assert RELEASE.splitlines().count(heading) == 1, heading

assert (
    RELEASE.index(ubuntu_verification_heading)
    < RELEASE.index(dual_preflight_heading)
    < RELEASE.index(legacy_preparation_heading)
)

dual_release_preflight = RELEASE.split(
    dual_preflight_heading, 1
)[1].split(
    legacy_preparation_heading, 1
)[0]

for token in (
    "set -euo pipefail",
    "tools/prepare-dual-release-assets.py",
    "--debian-ci ci-bundle",
    "--ubuntu-ci ci-ubuntu2604",
    '--output "$candidate"',
    '--deb-version "$DEB_VERSION"',
    '--public-version "$PUBLIC_VERSION"',
    '--commit "$GITHUB_SHA"',
    "tools/verify-dual-release.py",
    '--expected-commit "$GITHUB_SHA"',
    "sha256sum -c SHA256SUMS",
    'test "${#candidate_files[@]}" -eq 14',
    'python3 tools/privacy-scan.py "$candidate"',
    "Release preflight 14-asset candidate: PASS",
):
    assert token in dual_release_preflight, token

assert (
    dual_release_preflight.index("tools/prepare-dual-release-assets.py")
    < dual_release_preflight.index("tools/verify-dual-release.py")
    < dual_release_preflight.index("sha256sum -c SHA256SUMS")
    < dual_release_preflight.index("python3 tools/privacy-scan.py")
)

# No publication, tag creation, or artifact-upload action
# may be introduced into the candidate-validation step.
for forbidden in (
    "gh release create",
    "git push",
    "actions/upload-artifact@",
    "gh release upload",
):
    assert forbidden not in dual_release_preflight, forbidden

print("Dual-platform release preflight contract: PASS")

# UBUNTU_RELEASE_INPUT_CONTRACT

# Match complete YAML step-heading lines rather than relying
# on embedded newline escape sequences.
release_lines = RELEASE.splitlines()

ubuntu_steps = (
    "Download exact Ubuntu 26.04 CI bundle",
    "Verify Ubuntu 26.04 CI bundle and attestations",
    "Prepare immutable release bundle",
)

positions = []

for name in ubuntu_steps:
    heading = f"      - name: {name}"

    matches = [
        index
        for index, line in enumerate(release_lines)
        if line == heading
    ]

    assert len(matches) == 1, (
        f"Expected exactly one release step: {name}; "
        f"found {len(matches)}"
    )

    positions.append(matches[0])

assert positions == sorted(positions)
assert len(set(positions)) == len(positions)

download = "\n".join(
    release_lines[positions[0]:positions[1]]
)

verify = "\n".join(
    release_lines[positions[1]:positions[2]]
)

# Download must refer to the exact selected main CI run.
for token in (
    'RUN_ID: ${{ steps.ci.outputs.run_id }}',
    'gh run download "$RUN_ID"',
    '--name "ipod-sync-ubuntu2604-amd64-$GITHUB_SHA"',
    '--dir ci-ubuntu2604',
):
    assert token in download, (
        f"Ubuntu artifact download contract missing: {token}"
    )

# Verify both metadata linkage and security checks
# before preparing any public release assets.
for token in (
    'bundle="ci-ubuntu2604"',
    'root = Path("ci-ubuntu2604")',
    '"PROVENANCE.json"',
    '"BUILD-MATERIALS.json"',
    '"TOOLCHAIN.json"',
    'sha256sum -c SHA256SUMS',
    'git get-tar-commit-id',
    'ci-bundle/$source',
    'open-ipod-sync-build-materials-v1',
    'open-ipod-sync-provenance-v1',
    'ubuntu-26.04-snapshot-20261015T000000Z',
    'python3 tools/privacy-scan.py "$bundle"',
    'gh attestation verify "$subject"',
    '--source-ref',
    '--source-digest',
    '--signer-workflow',
    '--deny-self-hosted-runners',
    'Ubuntu signed CI bundle verification: PASS',
):
    assert token in verify, (
        f"Ubuntu artifact verification missing: {token}"
    )

assert verify.index(
    'sha256sum -c SHA256SUMS'
) < verify.index(
    'gh attestation verify "$subject"'
)

assert verify.index(
    'python3 tools/privacy-scan.py "$bundle"'
) < verify.index(
    'gh attestation verify "$subject"'
)

print("Ubuntu release input verification contract: PASS")

print("dual-platform release CI gate contract: PASS")

print("consumer verification documentation: PASS")

print("canonical consumer evidence in CI: PASS")
print("canonical consumer evidence in release: PASS")
print("internal A/B evidence remains unpublished: PASS")
print("audited CI and release artifact channels: PASS")
print("exact fourteen-asset release contract: PASS")
print("release workflow dogfoods consumer verifier: PASS")
print("consumer release contract tests: PASS")
