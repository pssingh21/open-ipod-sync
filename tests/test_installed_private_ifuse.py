#!/usr/bin/env python3
"""Verify installed Ubuntu runtime ignores unsafe ambient ifuse."""

import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile

APP = Path("/usr/lib/ipod-sync/ipod_sync.py")
PRIVATE = Path("/usr/lib/ipod-sync/bin/ifuse")
MARKER = Path("/usr/lib/ipod-sync/ifuse-bundled-required")

assert APP.is_file()
assert PRIVATE.is_file() and os.access(PRIVATE, os.X_OK)
assert not PRIVATE.is_symlink()
assert MARKER.read_text().strip() == "1.2.1"

spec = importlib.util.spec_from_file_location(
    "installed_ipod_sync_test", APP
)
assert spec is not None and spec.loader is not None

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

assert module.BUNDLED_IFUSE_BUILD is True
assert module.require_cmd("ifuse") == str(PRIVATE)
assert module.require_safe_ifuse() == (1, 2, 1)

print("Installed private ifuse 1.2.1: PASS")

with tempfile.TemporaryDirectory() as temporary:
    fake = Path(temporary) / "ifuse"
    fake.write_text(
        "#!/bin/sh\n"
        "echo 'ifuse 1.2.0'\n"
    )
    fake.chmod(0o755)

    old_path = os.environ.get("PATH", "")

    try:
        os.environ["PATH"] = temporary + ":" + old_path

        assert shutil.which("ifuse") == str(fake)

        # Even when the unsafe executable wins PATH
        # resolution, the installed application must use
        # its own private binary.
        assert module.require_cmd("ifuse") == str(PRIVATE)
        assert module.require_safe_ifuse() == (1, 2, 1)

        print("Unsafe ambient ifuse 1.2.0: IGNORED")

        try:
            module.require_safe_ifuse(str(fake))
        except module.SyncError as exc:
            assert "refusing alternate executable" in str(exc)
        else:
            raise AssertionError(
                "Unsafe executable override was accepted"
            )

        print("Unsafe executable override: REFUSED")

    finally:
        os.environ["PATH"] = old_path

print("Installed Ubuntu bundled-ifuse runtime: PASS")
