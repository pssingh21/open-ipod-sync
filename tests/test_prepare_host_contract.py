#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

prepare = (
    ROOT
    / "tools"
    / "prepare-host.sh"
).read_text()

ci = (
    ROOT
    / ".github"
    / "workflows"
    / "ci.yml"
).read_text()

readme = (
    ROOT
    / "README.md"
).read_text()

build = (
    ROOT
    / "build-deb.sh"
).read_text()


required_prepare = (
    'IFUSE_TAG="1.2.1"',
    'IFUSE_RELEASE_COMMIT_SHORT="f7eac74"',
    "https://github.com/libimobiledevice/ifuse.git",
    "libfuse3-dev",
    "findmnt -rn -t fuse.ifuse",
    'SELF_VERSION" == "1.2.0"',
    "1.2.0|1.2.0-*|1.2.0+*|1.2.0~*",
    "--branch \"$IFUSE_TAG\"",
    "rev-parse",
    "--short=7",
    "./autogen.sh",
    "--prefix=/usr/local",
    "make install",
    "/usr/local/bin/ifuse",
    "distro ifuse package retained",
)

for token in required_prepare:
    assert token in prepare, token


assert "sudo ./tools/prepare-host.sh" in ci
assert "sudo ./tools/prepare-host.sh" in readme


# CI must use the repository bootstrap instead of carrying its own second
# implementation of the upstream ifuse build.
assert (
    "https://github.com/libimobiledevice/ifuse.git"
    not in ci
)


# Networked host preparation and deterministic package construction are
# deliberately separate phases.
assert "prepare-host.sh" not in build
assert "git clone" not in build
assert "curl " not in build
assert "wget " not in build


assert (ROOT / "tools/prepare-host.sh").stat().st_mode & 0o111


print("host preparation contract tests: PASS")
