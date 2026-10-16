#!/usr/bin/env python3
"""Private ifuse routing and fail-closed safety contract."""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/ipod_sync.py"
BUILD = ROOT / "build-deb.sh"

spec = importlib.util.spec_from_file_location(
    "ipod_sync_private_ifuse_test", APP
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def expect_refusal(fn, message):
    try:
        fn()
    except m.SyncError as exc:
        assert message in str(exc), str(exc)
        return
    raise AssertionError(
        f"expected refusal containing {message!r}"
    )


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    private = root / "bin" / "ifuse"
    marker = root / "ifuse-bundled-required"
    private.parent.mkdir()

    old_project = m.PROJECT
    old_which = m.shutil.which

    try:
        m.PROJECT = root

        # Simulate a host where the system ifuse is unsafe.
        m.shutil.which = lambda name: (
            "/usr/bin/ifuse"
            if name == "ifuse"
            else old_which(name)
        )

        # Before the Ubuntu marker is installed, the
        # existing Debian host-resolution contract remains.
        assert m.require_cmd("ifuse") == "/usr/bin/ifuse"
        print("Legacy Debian ifuse routing: PASS")

        marker.write_text("bundled ifuse required\n")

        # Never fall back to system ifuse if bundled
        # binary is absent.
        expect_refusal(
            lambda: m.require_cmd("ifuse"),
            "bundled ifuse 1.2.1 is missing",
        )
        print("Missing private binary rejected: PASS")

        def write_version(version):
            private.write_text(
                "#!/bin/sh\n"
                f"printf 'ifuse {version}\\n'\n"
            )
            private.chmod(0o755)

        write_version("1.2.1")

        assert m.require_cmd("ifuse") == str(private)
        assert m.require_safe_ifuse() == (1, 2, 1)

        print("Private ifuse 1.2.1 selected: PASS")

        # Explicit attempts to replace the private binary
        # with an ambient binary are refused.
        expect_refusal(
            lambda: m.require_safe_ifuse("/usr/bin/ifuse"),
            "refusing alternate executable",
        )
        print("System binary override rejected: PASS")

        write_version("1.2.0")
        expect_refusal(
            lambda: m.require_safe_ifuse(),
            "must report exactly version 1.2.1",
        )
        print("Unsafe bundled version rejected: PASS")

        write_version("1.2.2")
        expect_refusal(
            lambda: m.require_safe_ifuse(),
            "must report exactly version 1.2.1",
        )
        print("Unexpected bundled version rejected: PASS")

        private.unlink()
        private.symlink_to("/usr/bin/true")

        expect_refusal(
            lambda: m.require_cmd("ifuse"),
            "not a regular executable file",
        )
        print("Symlinked bundled binary rejected: PASS")

    finally:
        m.PROJECT = old_project
        m.shutil.which = old_which

# The generated launcher must use its selected binary,
# not rediscover the system ifuse at mount time.
builder = BUILD.read_text()

start = "cat > \"$BUILD/usr/bin/ipod-sync\" <<'WRAP'\n"
end = "\nWRAP\n"

assert builder.count(start) == 1
launcher = builder.split(start, 1)[1].split(end, 1)[0]

for required in (
    "IFUSE_POLICY_MARKER=/usr/lib/ipod-sync/ifuse-bundled-required",
    "PRIVATE_IFUSE=/usr/lib/ipod-sync/bin/ifuse",
    'IFUSE_BIN="$PRIVATE_IFUSE"',
    '"$IFUSE_BIN" "$IPOD_SYNC_MOUNT" -o ro',
    "REFUSED: bundled ifuse 1.2.1 is missing or invalid",
):
    assert required in launcher, required

assert '  ifuse "$IPOD_SYNC_MOUNT" -o ro' not in launcher

print("Launcher private routing contract: PASS")
print("private ifuse routing tests: PASS")
