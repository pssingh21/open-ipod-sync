#!/usr/bin/env python3

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

README = ROOT / "README.md"
ARCH = ROOT / "docs" / "ARCHITECTURE.md"
RUNBOOK = ROOT / "docs" / "RELEASE-RUNBOOK.md"
BUILD = ROOT / "build-deb.sh"
MATRIX = ROOT / "tools" / "run-reproducibility-matrix.sh"
NETWORK = ROOT / "tools" / "network-deny-exec.c"
TOOLCHAIN = ROOT / "tools" / "create-toolchain-view.py"
MATERIALS = ROOT / "tools" / "generate-build-materials.py"


def require(
    text: str,
    token: str,
    label: str,
) -> None:
    if token not in text:
        raise SystemExit(
            f"ERROR: {label} missing required claim/evidence: {token}"
        )


def main() -> int:
    readme = README.read_text()
    arch = ARCH.read_text()
    runbook = RUNBOOK.read_text()
    build = BUILD.read_text()
    matrix = MATRIX.read_text()
    network = NETWORK.read_text()
    toolchain = TOOLCHAIN.read_text()
    materials = MATERIALS.read_text()

    combined_docs = "\n".join(
        (
            readme,
            arch,
            runbook,
        )
    )

    if re.search(
        r"\bfully[\s-]+hermetic\b",
        combined_docs,
        flags=re.IGNORECASE,
    ):
        raise SystemExit(
            "ERROR: documentation claims unsupported full hermeticity"
        )

    require(
        readme,
        "reproducible, network-isolated,",
        "README",
    )

    require(
        readme,
        "tool-resolution-confined build",
        "README",
    )

    require(
        readme,
        "complete filesystem sandbox",
        "README",
    )

    require(
        arch,
        "Reproducibility isolation model",
        "architecture",
    )

    require(
        arch,
        "not a general filesystem-read sandbox",
        "architecture",
    )

    require(
        runbook,
        "Interpreting the reproducibility gate",
        "release runbook",
    )

    require(
        runbook,
        "does **not** assert a filesystem-read sandbox",
        "release runbook",
    )

    require(
        matrix,
        'PATH="$fake_bin:$toolchain_view"',
        "matrix",
    )

    require(
        matrix,
        "KERNEL-DENIED BY SECCOMP",
        "matrix",
    )

    require(
        network,
        "PR_SET_SECCOMP",
        "network policy",
    )

    require(
        toolchain,
        "open-ipod-sync-toolchain-view-v1",
        "toolchain policy",
    )

    require(
        materials,
        "open-ipod-sync-build-materials-v1",
        "materials policy",
    )

    if "/tmp/ipod-sync-zlib-check" in build:
        raise SystemExit(
            "ERROR: build-deb.sh still uses the predictable "
            "/tmp zlib probe path"
        )

    require(
        build,
        'mktemp "${TMPDIR:-/tmp}/ipod-sync-zlib-check.XXXXXX"',
        "build-deb zlib probe",
    )

    print("reproducibility claim scope: PASS")
    print("unsupported full-hermetic claim: ABSENT")
    print("filesystem boundary disclosure: PASS")
    print("network/tool/material evidence linkage: PASS")
    print("TMPDIR-safe zlib probe: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
