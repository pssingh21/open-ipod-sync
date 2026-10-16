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
    "Verify published checksums and release attestations",
)

# Only the Debian 11 and Ubuntu 26.04 CI artifact uploads
# are permitted. Both must have a privacy scan before upload.
if CI.count("uses: actions/upload-artifact@") != 2:
    raise AssertionError(
        "expected exactly two authorized upload-artifact uses in CI"
    )

ubuntu_start = "  ubuntu-host-compatibility:\n"
ubuntu_end = "  attest-supply-chain:\n"

assert CI.count(ubuntu_start) == 1
assert CI.count(ubuntu_end) == 1

ubuntu_job = CI.split(ubuntu_start, 1)[1].split(
    ubuntu_end, 1
)[0]

assert ubuntu_job.count(
    "      - name: Prepare Ubuntu 26.04 package artifact\n"
) == 1

assert ubuntu_job.count(
    "      - name: Upload Ubuntu 26.04 package artifact\n"
) == 1

assert ubuntu_job.count(
    "uses: actions/upload-artifact@"
) == 1

require_order(
    ubuntu_job,
    "Prepare Ubuntu 26.04 package artifact",
    "Upload Ubuntu 26.04 package artifact",
)

prepare_step = ubuntu_job.split(
    "      - name: Prepare Ubuntu 26.04 package artifact\n",
    1,
)[1].split(
    "      - name: Upload Ubuntu 26.04 package artifact\n",
    1,
)[0]

assert (
    "python3 tools/privacy-scan.py ubuntu2604-artifact"
    in prepare_step
), "Ubuntu package privacy scan missing before upload"

assert (
    "sha256sum -c SHA256SUMS"
    in prepare_step
), "Ubuntu package checksum verification missing"

assert (
    "if: matrix.os == 'ubuntu-26.04'"
    in prepare_step
), "Ubuntu preparation must run only on Ubuntu 26.04"

upload_step = ubuntu_job.split(
    "      - name: Upload Ubuntu 26.04 package artifact\n",
    1,
)[1].split(
    "      - name:",
    1,
)[0]

assert (
    "if: matrix.os == 'ubuntu-26.04'"
    in upload_step
), "Ubuntu upload must run only on Ubuntu 26.04"

assert (
    "if-no-files-found: error"
    in upload_step
), "Ubuntu artifact upload must fail if files are missing"

assert (
    "name: ipod-sync-ubuntu2604-amd64-${{ github.sha }}"
    in upload_step
), "Ubuntu artifact must be commit-specific"

if RELEASE.count("uses: actions/upload-artifact@") != 1:
    raise AssertionError(
        "expected exactly one upload-artifact use in release workflow"
    )

print("privacy workflow boundary tests: PASS")
