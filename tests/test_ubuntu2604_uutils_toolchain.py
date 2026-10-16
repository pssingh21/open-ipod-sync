#!/usr/bin/env python3
"""Ubuntu packaged uutils executable-path security tests."""

import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
script = root / "tools/create-toolchain-view.py"

spec = importlib.util.spec_from_file_location(
    "ipod_sync_toolchain_view", script
)
assert spec is not None
assert spec.loader is not None

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

lexical = Path("/usr/bin/basename")
target = Path("/usr/lib/cargo/bin/coreutils/basename")


def valid_owner(path):
    if path == lexical:
        return ("coreutils-from-uutils", "1.0")
    if path == target:
        return ("rust-coreutils", "1.0")
    raise AssertionError(f"unexpected path: {path}")


with patch.object(
    module, "package_owner", side_effect=valid_owner
):
    assert module.trusted_distribution_coreutils_target(
        "basename", lexical, target
    )

    assert not module.trusted_distribution_coreutils_target(
        "basename",
        Path("/usr/local/bin/basename"),
        target,
    )

    assert not module.trusted_distribution_coreutils_target(
        "basename",
        lexical,
        Path("/opt/untrusted/basename"),
    )

    assert not module.trusted_distribution_coreutils_target(
        "dirname", lexical, target
    )

print("exact packaged uutils path: PASS")


with patch.object(
    module,
    "package_owner",
    return_value=("unexpected-package", "1.0"),
):
    assert not module.trusted_distribution_coreutils_target(
        "basename", lexical, target
    )

print("unexpected package owner rejected: PASS")


with tempfile.TemporaryDirectory() as temporary:
    output = Path(temporary)

    debian_manifest = output / "debian.json"
    module.write_manifest(debian_manifest, [
        {
            "command": "basename",
            "package": "coreutils",
            "package_version": "1",
            "target": "/usr/bin/basename",
        },
    ])
    debian = json.loads(debian_manifest.read_text())

    assert (
        "distribution_coreutils_exception"
        not in debian["policy"]
    )

    ubuntu_manifest = output / "ubuntu.json"
    module.write_manifest(ubuntu_manifest, [
        {
            "command": "basename",
            "package": "rust-coreutils",
            "package_version": "1",
            "target": str(target),
        },
    ])
    ubuntu = json.loads(ubuntu_manifest.read_text())

    exception = ubuntu["policy"][
        "distribution_coreutils_exception"
    ]

    assert exception["binary_package"] == "rust-coreutils"
    assert exception["provider_package"] == "coreutils-from-uutils"
    assert exception["package_ownership_verified"] is True

print("manifest exception disclosure: PASS")
print("Ubuntu uutils toolchain security tests: PASS")
