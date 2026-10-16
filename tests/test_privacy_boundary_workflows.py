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


def require_order(
    text: str,
    first: str,
    second: str,
) -> None:
    a = text.find(first)
    b = text.find(second)

    if a == -1:
        raise AssertionError(
            f"missing marker: {first!r}"
        )

    if b == -1:
        raise AssertionError(
            f"missing marker: {second!r}"
        )

    if a >= b:
        raise AssertionError(
            f"privacy boundary ordering violated: "
            f"{first!r} must precede {second!r}"
        )


require_order(
    CI,
    "Scan complete CI artifact privacy boundary",
    "Upload audited Debian package",
)

require_order(
    CI,
    "Scan downloaded and rebuilt artifact privacy boundaries",
    "Verify reproducible Debian package and supply-chain metadata",
)

require_order(
    CI,
    "Scan lifecycle artifact privacy boundary",
    "Run package lifecycle tests",
)

require_order(
    RELEASE,
    "Scan downloaded CI bundle privacy boundary",
    "Prepare immutable release bundle",
)

require_order(
    RELEASE,
    "Scan verified release bundle privacy boundary",
    "Upload verified release bundle",
)

require_order(
    RELEASE,
    "Scan publication privacy boundary",
    "Create and push annotated tag",
)

require_order(
    RELEASE,
    "Scan publication privacy boundary",
    "Publish prerelease",
)

require_order(
    RELEASE,
    "Scan published release privacy boundary",
    "Run independent dual-platform consumer verifier",
)

# The published assets must pass the privacy scanner
# before independent 14-asset authenticity verification.
scan_heading = (
    "      - name: Scan published release privacy boundary"
)
verify_heading = (
    "      - name: Run independent dual-platform consumer verifier"
)

assert RELEASE.splitlines().count(scan_heading) == 1
assert RELEASE.splitlines().count(verify_heading) == 1

scan_step = RELEASE.split(
    scan_heading, 1
)[1].split(
    verify_heading, 1
)[0]

verify_step = RELEASE.split(verify_heading, 1)[1]

assert "python3 tools/privacy-scan.py published" in scan_step

for required in (
    "tools/verify-dual-release-github.py",
    "published",
    '--expected-commit "$GITHUB_SHA"',
    '--repo "$GITHUB_REPOSITORY"',
    '--tag "$TAG"',
):
    assert required in verify_step, required

print("Published dual-platform privacy boundary: PASS")

# Preserve exactly two CI artifact channels.
assert CI.count("uses: actions/upload-artifact@") == 2

compat = CI.split(
    "  ubuntu-host-compatibility:", 1
)[1].split(
    "  ubuntu2604-reproducibility-check:", 1
)[0]

ubuntu = CI.split(
    "  ubuntu2604-reproducibility-check:", 1
)[1].split(
    "  attest-supply-chain:", 1
)[0]

# Compatibility testing must never publish the Ubuntu package.
assert "uses: actions/upload-artifact@" not in compat

assert ubuntu.count(
    "uses: actions/upload-artifact@"
) == 1

require_order(
    ubuntu,
    "Run pinned Ubuntu 26.04 A/B matrix",
    "Prepare verified pinned Ubuntu candidate",
)
require_order(
    ubuntu,
    "Prepare verified pinned Ubuntu candidate",
    "Verify pinned Ubuntu candidate for upload",
)
require_order(
    ubuntu,
    "Verify pinned Ubuntu candidate for upload",
    "Upload verified pinned Ubuntu package",
)

verify = ubuntu.split(
    "      - name: Verify pinned Ubuntu candidate for upload",
    1,
)[1].split(
    "      - name: Upload verified pinned Ubuntu package",
    1,
)[0]

assert "sha256sum -c SHA256SUMS" in verify
assert 'python3 tools/privacy-scan.py "$candidate"' in verify
assert 'test "${#names[@]}" -eq 7' in verify

upload = ubuntu.split(
    "      - name: Upload verified pinned Ubuntu package",
    1,
)[1]

assert "if-no-files-found: error" in upload
assert (
    "name: ipod-sync-ubuntu2604-amd64-${{ github.sha }}"
    in upload
)
assert (
    "path: ${{ runner.temp }}/ubuntu2604-pinned-candidate/"
    in upload
)

if RELEASE.count("uses: actions/upload-artifact@") != 1:
    raise AssertionError(
        "expected exactly one upload-artifact use in release workflow"
    )

print("privacy workflow boundary tests: PASS")
