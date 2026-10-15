#!/usr/bin/env python3

import contextlib
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SPEC = importlib.util.spec_from_file_location(
    "ipod_sync_ifuse_safety_test",
    ROOT / "src/ipod_sync.py",
)

assert SPEC is not None
assert SPEC.loader is not None

m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


@contextlib.contextmanager
def patched(**replacements):
    originals = {}

    try:
        for name, value in replacements.items():
            originals[name] = getattr(m, name)
            setattr(m, name, value)

        yield

    finally:
        for name, value in reversed(
            list(originals.items())
        ):
            setattr(m, name, value)


def expect_sync_error(fn, expected):
    try:
        fn()
    except m.SyncError as exc:
        message = str(exc)

        assert expected in message, (
            expected,
            message,
        )

        return message

    raise AssertionError(
        f"expected SyncError containing {expected!r}"
    )


# ---------------------------------------------------------------------------
# Version parser accepts common upstream / distro representations.
# ---------------------------------------------------------------------------

cases = {
    "ifuse 1.1.4": (1, 1, 4),
    "ifuse 1.2.0": (1, 2, 0),
    "ifuse 1.2.0-2": (1, 2, 0),
    "ifuse version 1.2.1": (1, 2, 1),
    "ifuse 1.3.0+git20261001": (1, 3, 0),
}

for text, expected in cases.items():
    actual = m.parse_ifuse_version(text)
    assert actual == expected, (
        text,
        expected,
        actual,
    )


expect_sync_error(
    lambda: m.parse_ifuse_version(
        "ifuse version unavailable"
    ),
    "unable to determine ifuse version",
)


# ---------------------------------------------------------------------------
# Only the known-corrupt upstream release is rejected.
#
# In particular, do not accidentally reject older known-working distro
# versions such as 1.1.4.
# ---------------------------------------------------------------------------

def fake_version_runner(output):
    def fake_run(cmd, **kwargs):
        assert cmd[-1] == "--version"

        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=output,
        )

    return fake_run


for output, expected in (
    ("ifuse 1.1.4\n", (1, 1, 4)),
    ("ifuse 1.2.1\n", (1, 2, 1)),
    ("ifuse 1.3.0\n", (1, 3, 0)),
):
    with patched(
        run=fake_version_runner(output),
    ):
        actual = m.require_safe_ifuse(
            "/synthetic/ifuse"
        )

    assert actual == expected, (
        output,
        actual,
        expected,
    )


with patched(
    run=fake_version_runner(
        "ifuse 1.2.0-2\n"
    ),
):
    message = expect_sync_error(
        lambda: m.require_safe_ifuse(
            "/synthetic/ifuse"
        ),
        "unsafe ifuse version detected: 1.2.0",
    )

assert "data corruption" in message
assert "1.2.1 or later" in message


# ---------------------------------------------------------------------------
# Version command failure is fail-closed.
# ---------------------------------------------------------------------------

def failed_version_run(cmd, **kwargs):
    return subprocess.CompletedProcess(
        cmd,
        2,
        stdout="",
    )


with patched(
    run=failed_version_run,
):
    expect_sync_error(
        lambda: m.require_safe_ifuse(
            "/synthetic/ifuse"
        ),
        "unable to determine ifuse version",
    )


# ---------------------------------------------------------------------------
# Existing mounted-device validation must run the version gate before
# trusting mount metadata.
# ---------------------------------------------------------------------------

events = []


with patched(
    require_safe_ifuse=lambda binary=None:
        events.append("safe-ifuse") or (1, 2, 1),
    mount_info=lambda path:
        events.append("mount-info")
        or (
            "ifuse",
            str(path),
            "fuse.ifuse",
            {"ro"},
        ),
):
    m.require_ifuse_mount(
        Path("/synthetic/ipod"),
        writable=False,
    )


assert events == [
    "safe-ifuse",
    "mount-info",
], events


# ---------------------------------------------------------------------------
# Stable live-file reads succeed without modifying the source file.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "Library.itdb"

    original = (
        b"SQLite format 3\x00"
        + b"\x00" * 8192
    )

    path.write_bytes(original)

    expected_digest = hashlib.sha256(
        original
    ).hexdigest()

    actual_digest = m.require_stable_file_read(
        path,
        attempts=3,
    )

    assert actual_digest == expected_digest
    assert path.read_bytes() == original


# ---------------------------------------------------------------------------
# Differing byte streams fail closed even when file metadata remains stable.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "Library.itdb"
    original = b"stable-source-bytes\n"

    path.write_bytes(original)

    digests = iter(
        (
            "a" * 64,
            "b" * 64,
            "a" * 64,
        )
    )

    with patched(
        sha256_file=lambda candidate:
            next(digests),
    ):
        expect_sync_error(
            lambda: m.require_stable_file_read(
                path,
                attempts=3,
            ),
            "repeated reads returned different bytes",
        )

    assert path.read_bytes() == original


# ---------------------------------------------------------------------------
# Invalid stable-read configuration is rejected.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "x"
    path.write_bytes(b"x")

    try:
        m.require_stable_file_read(
            path,
            attempts=1,
        )
    except ValueError as exc:
        assert (
            "at least two attempts"
            in str(exc)
        )
    else:
        raise AssertionError(
            "single-attempt stability check was accepted"
        )



# ---------------------------------------------------------------------------
# Doctor must use the same ifuse safety gate.
# ---------------------------------------------------------------------------

doctor_source = (
    ROOT / "src/ipod_sync.py"
).read_text()

assert 'if name == "ifuse":' in doctor_source
assert "require_safe_ifuse(path)" in doctor_source
assert '"UNSAFE"' in doctor_source



# ---------------------------------------------------------------------------
# Repository-level Ubuntu 26.04 compatibility contract.
# ---------------------------------------------------------------------------

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

architecture = (
    ROOT
    / "docs"
    / "ARCHITECTURE.md"
).read_text()

third_party = (
    ROOT
    / "THIRD_PARTY.md"
).read_text()

changelog = (
    ROOT
    / "CHANGELOG.md"
).read_text()


for token in (
    "Verify distro ifuse safety contract",
    "Install upstream ifuse 1.2.1 on Ubuntu 26.04",
    'if: matrix.os == \'ubuntu-26.04\'',
    "unsafe ifuse version detected: 1.2.0",
    "f7eac74",
    "/usr/local/bin/ifuse",
    "Ubuntu 26.04 distro ifuse 1.2.0 ",
    "rejection: PASS",
    "Ubuntu 26.04 upstream ifuse 1.2.1 ",
    "acceptance: PASS",
):
    assert token in ci, token


for token in (
    "### ifuse 1.2.0 safety requirement",
    "Ubuntu 26.04 (Resolute)",
    "`1.2.0-2`",
    "`/usr/local/bin/ifuse`",
    "https://github.com/libimobiledevice/ifuse",
    "https://packages.ubuntu.com/resolute/amd64/utils/ifuse",
):
    assert token in readme, token


for token in (
    "device trust boundary",
    "Upstream `ifuse` 1.2.0",
    "repeated reads",
    "SHA-256",
):
    assert token in architecture, token


assert (
    "`ifuse` 1.2.0 is explicitly unsupported"
    in third_party
)

assert "## Unreleased" in changelog
assert "ifuse` 1.2.0-2 hazard" in changelog


print("ifuse safety tests: PASS")
