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

if CI.count("uses: actions/upload-artifact@") != 1:
    raise AssertionError(
        "expected exactly one upload-artifact use in CI"
    )

if RELEASE.count("uses: actions/upload-artifact@") != 1:
    raise AssertionError(
        "expected exactly one upload-artifact use in release workflow"
    )

print("privacy workflow boundary tests: PASS")
