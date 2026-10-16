#!/usr/bin/env python3

from pathlib import Path
import re


ROOT = Path(
    __file__
).resolve().parents[1]

README = (
    ROOT
    / "README.md"
).read_text()

SECURITY = (
    ROOT
    / "SECURITY.md"
).read_text()

POLICY = (
    ROOT
    / "docs"
    / "REPOSITORY-POLICY.md"
).read_text()

RUNBOOK = (
    ROOT
    / "docs"
    / "RELEASE-RUNBOOK.md"
).read_text()

PUBLIC_SANITY = (
    ROOT
    / "tools"
    / "public-sanity-check.sh"
).read_text()

AUDITOR = (
    ROOT
    / "tools"
    / "audit-repository-policy.py"
).read_text()

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


REQUIRED_CHECKS = {
    "Public source sanity — Python 3.9",
    "Debian 11 package build + audit",
    "Debian 11 reproducibility gate",
    "Debian 11 package lifecycle",
    "Ubuntu host compatibility — ubuntu-24.04",
    "Ubuntu host compatibility — ubuntu-26.04",
    "Workflow policy and actionlint",
    "zizmor GitHub Actions security",
    "CodeQL",
    "CodeQL — C/C++",
    "CodeQL — Python",
    "Dependency vulnerability review",
}


for token in (
    "<!-- REPOSITORY_POLICY_BEGIN -->",
    "<!-- REPOSITORY_POLICY_END -->",
    "docs/REPOSITORY-POLICY.md",
    "tools/audit-repository-policy.py",
):
    assert token in README, token


for token in (
    "GitHub private vulnerability reporting is enabled",
    "Do not place credentials",
):
    assert token in SECURITY, token


for token in (
    "# Repository policy",
    "`Protect main`",
    "`Protect release tags`",
    "refs/tags/v*",
    "merge commits only",
    "zero mandatory approving reviews",
    "private vulnerability reporting",
    "Repository-level immutable releases",
    "strictly read-only",
    "does not inspect or modify",
):
    assert token in POLICY, token


for check in REQUIRED_CHECKS:
    assert check in POLICY, check
    assert check in AUDITOR, check


assert (
    "GitHub artifact attestations"
    in POLICY
)

assert (
    "deliberately not a pull-request-required"
    in POLICY
)


for token in (
    "<!-- REPOSITORY_RELEASE_POLICY_BEGIN -->",
    "<!-- REPOSITORY_RELEASE_POLICY_END -->",
    "REPOSITORY-POLICY.md",
    "refs/tags/v*",
    "isImmutable=false",
):
    assert token in RUNBOOK, token


for token in (
    "private-vulnerability-reporting",
    "immutable-releases",
    "actions/permissions",
    "actions/permissions/workflow",
    "actions/permissions/selected-actions",
    "fork-pr-contributor-approval",
    "environments/release",
    "rulesets?includes_parents=true",
    "Protect main",
    "Protect release tags",
):
    assert token in AUDITOR, token


# Repository-root API calls must not append a trailing slash. GitHub's API
# treats the repository root and the trailing-slash variant differently.
assert 'f"repos/{repo}/{suffix}"' not in AUDITOR

for token in (
    'endpoint = f"repos/{repo}"',
    "if suffix:",
    'suffix.lstrip("/")',
):
    assert token in AUDITOR, token


# The operator audit must remain read-only. Do not add GitHub API mutation
# methods to this tool.
for forbidden in (
    "--method",
    '"POST"',
    '"PATCH"',
    '"PUT"',
    '"DELETE"',
    "-X POST",
    "-X PATCH",
    "-X PUT",
    "-X DELETE",
):
    assert forbidden not in AUDITOR, forbidden


# Historical release enumeration is not an ongoing enforcement control.
# Keep that remote-data path out of the live auditor entirely.
for forbidden in (
    "audit_historical_releases",
    "immutable historical release count:",
    "legacy pre-enforcement release count:",
):
    assert forbidden not in AUDITOR, forbidden


# Advanced Secret Protection capability state is not an enforcement
# requirement. Do not echo GitHub-returned capability values into logs.
for forbidden in (
    'f"{non_provider} (capability state)"',
    'f"{validity} (capability state)"',
    "non_provider = (",
    "validity = (",
):
    assert forbidden not in AUDITOR, forbidden

for required in (
    "generic/non-provider secret patterns: ",
    "secret validity checks: ",
    "NOT POLICY-REQUIRED",
):
    assert required in AUDITOR, required


# The live policy audit must not depend on user synchronization data.
for forbidden in (
    "/mnt/music",
    "source_root",
    "source-root",
    "ipod_mount",
    "ipod-mount",
    "/iPod_Control",
):
    assert forbidden not in AUDITOR, forbidden


assert (
    'test_repository_policy_contract.py'
    in PUBLIC_SANITY
)


for token in (
    "public-source-sanity:",
    "package-build-audit:",
    "reproducibility-check:",
    "package-lifecycle:",
    "ubuntu-host-compatibility:",
    "ubuntu2604-reproducibility-check:",
    "dual-platform-release-candidate-check:",
    "attest-supply-chain:",
    "attest-ubuntu2604:",
):
    assert token in CI, token


for token in (
    "preflight:",
    "publish:",
    "verify:",
    "workflow_dispatch:",
    "name: release",
    'git tag -a "$TAG"',
    'gh release create "$TAG"',
    "--verify-tag",
    'if not doc["isImmutable"]',
):
    assert token in RELEASE, token


# Preserve the exact nine-job top-level CI contract.
# The Ubuntu reproducibility gate is a distinct mandatory CI job.
ci_jobs = re.findall(
    r"(?m)^  ([A-Za-z0-9_-]+):\s*$",
    CI.split(
        "\njobs:\n",
        1,
    )[1],
)

assert ci_jobs == [
    "public-source-sanity",
    "package-build-audit",
    "reproducibility-check",
    "package-lifecycle",
    "ubuntu-host-compatibility",
    "ubuntu2604-reproducibility-check",
    "dual-platform-release-candidate-check",
    "attest-supply-chain",
    "attest-ubuntu2604",
], ci_jobs


# Real multi-platform CI candidate must be independently
# assembled and checked without adding a publish channel.
# Extract the CI job using exact YAML indentation.
# This avoids fragile escaped-newline string matching.
def extract_ci_job(workflow, job_name):
    lines = workflow.splitlines(keepends=True)
    heading = f"  {job_name}:"

    matches = [
        i for i, line in enumerate(lines)
        if line.rstrip() == heading
    ]

    assert len(matches) == 1, (
        f"Expected exactly one CI job: {job_name}; "
        f"found {len(matches)}"
    )

    begin = matches[0]
    end = len(lines)

    for i in range(begin + 1, len(lines)):
        line = lines[i]

        # Top-level jobs use exactly two spaces.
        if (
            line.startswith("  ")
            and not line.startswith("   ")
            and line.strip().endswith(":")
        ):
            end = i
            break

    return "".join(lines[begin:end])


candidate_ci = extract_ci_job(
    CI, "dual-platform-release-candidate-check"
)

assert candidate_ci.count(
    "uses: actions/download-artifact@"
) == 2
assert "uses: actions/upload-artifact@" not in candidate_ci

for required in (
    "- package-build-audit",
    "- reproducibility-check",
    "- ubuntu2604-reproducibility-check",
    "persist-credentials: false",
    "tools/prepare-dual-release-assets.py",
    "--debian-ci ci-debian",
    "--ubuntu-ci ci-ubuntu",
    "--commit",
    "sha256sum -c SHA256SUMS",
    "python3 tools/privacy-scan.py",
    "Exact 14-file release candidate: PASS",
):
    assert required in candidate_ci, required

release_jobs = re.findall(
    r"(?m)^  ([A-Za-z0-9_-]+):\s*$",
    RELEASE.split(
        "\njobs:\n",
        1,
    )[1],
)

assert release_jobs == [
    "preflight",
    "publish",
    "verify",
], release_jobs


print(
    "repository policy contract tests: PASS"
)
