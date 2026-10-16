#!/usr/bin/env python3
"""Verify the package audit enforces embedded ifuse policy."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]

audit = (root / "tools/audit-deb.sh").read_text()
builder = (root / "build-deb.sh").read_text()
runtime = (root / "src/ipod_sync.py").read_text()

required_audit = (
    "===== EMBEDDED IFUSE POLICY =====",
    "IFUSE_BUNDLED_BUILD=1",
    "IFUSE_BUNDLED_BUILD=0",
    "BUNDLED_IFUSE_BUILD = True",
    "BUNDLED_IFUSE_BUILD = False",
    "embedded ifuse launcher policy mismatch",
    "embedded ifuse Python policy mismatch",
    "mandatory launcher policy guard missing",
    "mandatory Python policy guard missing",
)

for marker in required_audit:
    assert marker in audit, marker

assert "STAMP_IFUSE_POLICY" in builder
assert "IFUSE_BUNDLED_BUILD=0" in builder
assert "BUNDLED_IFUSE_BUILD = False" in runtime
assert "if BUNDLED_IFUSE_BUILD:" in runtime

print("Embedded Bash/Python policy contract: PASS")
print("Package audit policy consistency: PASS")
