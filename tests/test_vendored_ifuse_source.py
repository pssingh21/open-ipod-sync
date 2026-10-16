#!/usr/bin/env python3
"""Ensure the bundled upstream ifuse source is pinned and complete."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "third_party/ifuse-1.2.1-source"
PROVENANCE = ROOT / "third_party/ifuse-1.2.1-UPSTREAM.txt"

COMMIT = "f7eac74184ff240c8ba9cf9b413eed75968a462a"

assert SOURCE.is_dir()
assert not (SOURCE / ".git").exists()
assert (SOURCE / ".tarball-version").read_text().strip() == "1.2.1"

for name in (
    "src/ifuse.c",
    "src/Makefile.am",
    "Makefile.am",
    "configure.ac",
    "autogen.sh",
    "git-version-gen",
    "COPYING",
):
    path = SOURCE / name
    assert path.is_file() and not path.is_symlink(), name

provenance = PROVENANCE.read_text()
assert f"Git commit: {COMMIT}" in provenance
assert "Release tag: 1.2.1" in provenance
assert "https://github.com/libimobiledevice/ifuse.git" in provenance

configure = (SOURCE / "configure.ac").read_text()
assert "libfuse, fuse3" in configure
assert "libimobiledevice-1.0" in configure
assert "libplist-2.0" in configure

assert "GNU LESSER GENERAL PUBLIC LICENSE" in (
    SOURCE / "COPYING"
).read_text()

print("Pinned ifuse source and license: PASS")
print("FUSE3 build requirements: PASS")
