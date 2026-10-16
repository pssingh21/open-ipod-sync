#!/usr/bin/env python3
"""Bundled Ubuntu ifuse policy must survive missing files."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "bundled_ifuse_negative_test",
    ROOT / "src/ipod_sync.py",
)

app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


def refused(fn, expected):
    try:
        fn()
    except app.SyncError as exc:
        assert expected in str(exc), str(exc)
        return
    raise AssertionError("Expected fail-closed refusal")


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    marker = root / "ifuse-bundled-required"
    binary = root / "bin" / "ifuse"
    binary.parent.mkdir()

    app.PROJECT = root
    app.BUNDLED_IFUSE_BUILD = True

    # The system runtime is deliberately available.
    app.shutil.which = lambda name: "/usr/bin/ifuse"

    refused(
        lambda: app.require_cmd("ifuse"),
        "policy marker",
    )
    print("Python missing marker: REFUSED")

    # A missing marker must still be refused even when
    # a private executable exists.
    binary.write_text("#!/bin/sh\necho 'ifuse 1.2.1'\n")
    binary.chmod(0o755)

    refused(
        lambda: app.require_safe_ifuse(),
        "policy marker",
    )
    print("Python missing marker with binary: REFUSED")

    # Reject an incorrectly versioned marker.
    marker.write_text("1.2.0\n")
    refused(
        lambda: app.require_cmd("ifuse"),
        "policy marker",
    )
    print("Python incorrect marker: REFUSED")

    # Reject a missing private binary with a valid marker.
    marker.write_text("1.2.1\n")
    binary.unlink()

    refused(
        lambda: app.require_cmd("ifuse"),
        "bundled ifuse 1.2.1 is missing",
    )
    print("Python missing private binary: REFUSED")

    # Check the generated Bash launcher with an embedded
    # Ubuntu build policy, using only temporary paths.
    builder = (ROOT / "build-deb.sh").read_text()
    start = """cat > "$BUILD/usr/bin/ipod-sync" <<'WRAP'\n"""
    end = "\nWRAP\n"

    assert builder.count(start) == 1
    launcher = builder.split(start, 1)[1].split(end, 1)[0]

    assert launcher.count("IFUSE_BUNDLED_BUILD=0") == 1

    launcher = launcher.replace(
        "IFUSE_BUNDLED_BUILD=0",
        "IFUSE_BUNDLED_BUILD=1",
        1,
    )
    launcher = launcher.replace(
        "IFUSE_POLICY_MARKER=/usr/lib/ipod-sync/ifuse-bundled-required",
        f"IFUSE_POLICY_MARKER={marker}",
        1,
    )
    launcher = launcher.replace(
        "PRIVATE_IFUSE=/usr/lib/ipod-sync/bin/ifuse",
        f"PRIVATE_IFUSE={binary}",
        1,
    )

    script = root / "ipod-sync-test"
    script.write_text(launcher)
    script.chmod(0o755)

    marker.unlink()

    result = subprocess.run(
        ["bash", str(script), "mount-ro"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "policy marker missing or invalid" in result.stderr

    print("Bash launcher missing marker: REFUSED")
    print("Unsafe system fallback: BLOCKED")
    print("Bundled ifuse negative tests: PASS")
