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

print("Ubuntu reproducibility workflow contract: PASS")
