#!/usr/bin/env python3

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ci = (
    ROOT / ".github/workflows/ci.yml"
).read_text()

matrix = (
    ROOT / "tools/run-reproducibility-matrix.sh"
).read_text()


def require(text, marker):
    if marker not in text:
        raise AssertionError(f"missing marker: {marker}")


def job_section(text, name):
    lines = text.splitlines(keepends=True)
    heading = f"  {name}:"

    positions = [
        i for i, line in enumerate(lines)
        if line.rstrip() == heading
    ]

    assert len(positions) == 1, (
        f"expected one CI job named {name}"
    )

    start = positions[0]
    end = len(lines)

    for i in range(start + 1, len(lines)):
        line = lines[i]
        if (
            line.startswith("  ")
            and not line.startswith("   ")
            and line.strip().endswith(":")
        ):
            end = i
            break

    return "".join(lines[start:end])


ubuntu = job_section(
    ci, "ubuntu2604-reproducibility-check"
)

debian = job_section(
    ci, "reproducibility-check"
)

require(
    ubuntu,
    "needs: ubuntu-host-compatibility",
)
require(
    ubuntu,
    "runs-on: ubuntu-26.04",
)
require(
    ubuntu,
    "Ubuntu independent A/B rebuild: PASS"
)

require(
    ubuntu,
    "run-reproducibility-matrix.sh",
)
require(
    ubuntu,
    "ubuntu-26.04-amd64",
)
require(
    ubuntu,
    "sha256sum -c SHA256SUMS",
)
require(
    ubuntu,
    "python3 tools/privacy-scan.py",
)
require(
    ubuntu,
    "cmp",
)
require(
    ubuntu,
    "BYTE-IDENTICAL",
)

assert (
    ubuntu.index("sha256sum -c SHA256SUMS")
    < ubuntu.index(
        "Rebuild Ubuntu package under isolated profiles"
    )
)

assert (
    ubuntu.index("python3 tools/privacy-scan.py")
    < ubuntu.index("Ubuntu baseline/A/B comparison: PASS")
)

# Existing Debian reproducibility gate must remain.
require(
    debian,
    "debian:11@sha256:",
)

# Existing Debian CLI invocation remains supported.
require(
    matrix,
    'BUILD_ENVIRONMENT="${7:-debian-11-amd64-'
)

require(
    matrix,
    'ubuntu-26.04-amd64)',
)

require(
    matrix,
    '"$BUILD_ENVIRONMENT"',
)

# No new CI artifact upload channel is authorized.
assert ci.count(
    "uses: actions/upload-artifact@"
) == 2

pinned_script = (
    ROOT / "tools/verify-ubuntu2604-pinned-inputs.sh"
).read_text()

assert (
    "Verify pinned Ubuntu 26.04 image and APT snapshot"
    in ubuntu
)
assert (
    "bash tools/verify-ubuntu2604-pinned-inputs.sh"
    in ubuntu
)
assert ubuntu.index(
    "Verify pinned Ubuntu 26.04 image and APT snapshot"
) < ubuntu.index(
    "Install Ubuntu build dependencies"
)

assert (
    "88a381d5b5eeb2b35d3ad70925a362c37ce569daf43ede89ff818ec20e4d3794"
    in pinned_script
)
assert "20261015T000000Z" in pinned_script

assert "resolute-security" in pinned_script
assert "snapshot[.]ubuntu[.]com" in pinned_script


# Snapshot verification must not silently fall back to
# current Ubuntu repositories or ignore failed indexes.
pinned_script = (
    ROOT / "tools/verify-ubuntu2604-pinned-inputs.sh"
).read_text()

for required in (
    "docker.io/library/ubuntu@sha256:",
    "20261015T000000Z",
    "URIs: https://snapshot.ubuntu.com/ubuntu/${snapshot}",
    "Acquire::https::CaInfo=",
    "APT::Update::Error-Mode=any",
    "ubuntu-archive-keyring.gpg",
    "resolute-security",
    "InRelease",
    "apt-cache policy",
    "sha256sum",
):
    require(pinned_script, required)

assert "Acquire::https::Verify-Peer=false" not in pinned_script
assert "Acquire::https::Verify-Host=false" not in pinned_script
assert "trusted=yes" not in pinned_script
assert "allow-unauthenticated" not in pinned_script
assert "Snapshot: ${snapshot}" not in pinned_script

# PINNED_MATRIX_SECURITY_CONTRACT
pinned_matrix = (
    ROOT / "tools/test-ubuntu2604-pinned-matrix.sh"
).read_text()

require(
    ubuntu,
    "Run pinned Ubuntu 26.04 A/B matrix",
)

require(
    ubuntu,
    "bash tools/test-ubuntu2604-pinned-matrix.sh",
)

assert ubuntu.index(
    "Verify pinned Ubuntu 26.04 image and APT snapshot"
) < ubuntu.index(
    "Run pinned Ubuntu 26.04 A/B matrix"
)

for token in (
    "docker.io/library/ubuntu@sha256:",
    "20261015T000000Z",
    "APT::Update::Error-Mode=any",
    "ubuntu-archive-keyring.gpg",
    "run-reproducibility-matrix.sh",
    "source=${GITHUB_WORKSPACE},target=/repo,readonly",
    "source=${CA},target=/tmp/bootstrap-ca.crt,readonly",
    "python3 tools/privacy-scan.py",
    "PINNED A/B REPRODUCIBILITY: PASS",
):
    require(pinned_matrix, token)

for forbidden in (
    "Verify-Peer=false",
    "Verify-Host=false",
    "allow-unauthenticated",
    "trusted=yes",
):
    assert forbidden not in pinned_matrix

# PINNED_CANDIDATE_CONTRACT
candidate = (
    ROOT / "tools/prepare-ubuntu2604-pinned-candidate.sh"
).read_text()

require(
    ubuntu,
    "Prepare verified pinned Ubuntu candidate",
)
require(
    ubuntu,
    "bash tools/prepare-ubuntu2604-pinned-candidate.sh",
)

assert ubuntu.index(
    "Run pinned Ubuntu 26.04 A/B matrix"
) < ubuntu.index(
    "Prepare verified pinned Ubuntu candidate"
)

for token in (
    "sha256sum -c SHA256SUMS",
    "cmp -s",
    "builder-a.json",
    "builder-b.json",
    "toolchain-a.json",
    "toolchain-b.json",
    "BUILD-MATERIALS.json",
    "TOOLCHAIN.json",
    "source_date_epoch",
    "python3 tools/privacy-scan.py",
    "VERIFIED PINNED CANDIDATE",
):
    require(candidate, token)

print("Ubuntu reproducibility workflow contract: PASS")
