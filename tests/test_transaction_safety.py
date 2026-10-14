#!/usr/bin/env python3

from pathlib import Path
import hashlib
import importlib.util
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/ipod_sync.py"

spec = importlib.util.spec_from_file_location(
    "ipod_sync_transaction_safety_test",
    APP,
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def snapshot(root: Path):
    result = {}

    if not root.exists():
        return result

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()

        if path.is_dir():
            result[rel] = ("dir",)
        elif path.is_file():
            result[rel] = (
                "file",
                path.stat().st_size,
                m.sha256_file(path),
            )
        else:
            result[rel] = ("other",)

    return result


def expect_sync_error(fn, expected: str):
    try:
        fn()
    except m.SyncError as exc:
        message = str(exc)
        assert expected in message, (expected, message)
        return message

    raise AssertionError(f"expected SyncError containing: {expected!r}")


def make_track(
    source: Path,
    *,
    source_root: Path,
    device_rel: str = "iTunes_Control/Music/F00/TEST.mp3",
):
    payload_hash = m.sha256_file(source)

    return m.Track(
        source=source,
        source_rel=source.relative_to(source_root).as_posix(),
        title=source.stem,
        sha256=payload_hash,
        source_size=source.stat().st_size,
        duration_ms=180000,
        bitrate_kbps=256,
        sample_rate_hz=44100,
        direct_mp3=True,
        device_rel=device_rel,
        output_size=source.stat().st_size,
        output_sha256=payload_hash,
    )


def create_live_snapshot_files(mount: Path):
    paths = m.live_paths(mount)

    for index, name in enumerate(m.SNAPSHOT_NAMES, 1):
        path = paths[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            f"synthetic-live-{index}-{name}\n".encode("utf-8")
        )

    return paths


# ---------------------------------------------------------------------------
# 1. Source bytes change after planning, without changing file size.
#
# This is stronger than only checking stat size: validate_tracks_source()
# must recompute SHA-256 and reject the changed source.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source_root = root / "source"
    source_root.mkdir()

    source = source_root / "track.mp3"
    source.write_bytes(b"planned-content-A\n")

    track = make_track(source, source_root=source_root)

    original_size = source.stat().st_size

    # Same byte length, different content.
    replacement = b"changed-content-B\n"
    assert len(replacement) == original_size
    source.write_bytes(replacement)

    before = snapshot(source_root)

    expect_sync_error(
        lambda: m.validate_tracks_source(
            [track],
            source_root,
            None,
        ),
        "source SHA256 changed",
    )

    assert snapshot(source_root) == before


# ---------------------------------------------------------------------------
# 2. Every transaction destination form must already be absent:
#      final
#      .ipodctl-part
#      .ipodctl-new
#
# Validation must reject each collision without modifying the synthetic device.
# ---------------------------------------------------------------------------

for collision_kind in ("final", "part", "new"):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source_root = root / "source"
        mount = root / "device"

        source_root.mkdir()
        mount.mkdir()

        source = source_root / "track.mp3"
        source.write_bytes(b"destination-collision-test\n")

        track = make_track(
            source,
            source_root=source_root,
            device_rel="iTunes_Control/Music/F07/COLL.mp3",
        )

        final = mount / track.device_rel
        final.parent.mkdir(parents=True, exist_ok=True)

        if collision_kind == "final":
            collision = final
        elif collision_kind == "part":
            collision = final.with_name(final.name + ".ipodctl-part")
        else:
            collision = final.with_name(final.name + ".ipodctl-new")

        collision.write_bytes(
            f"existing-{collision_kind}\n".encode("utf-8")
        )

        before = snapshot(mount)

        expect_sync_error(
            lambda: m.validate_destinations_absent([track], mount),
            "planned destination is not clean",
        )

        assert snapshot(mount) == before


# ---------------------------------------------------------------------------
# 3. Direct MP3 writing must preserve the exact planned bytes, SHA-256,
#    and size, and must leave no temporary partial behind.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source_root = root / "source"
    mount = root / "device"

    source_root.mkdir()
    mount.mkdir()

    source = source_root / "track.mp3"
    payload = b"exact-direct-mp3-test-payload\n"
    source.write_bytes(payload)

    track = make_track(
        source,
        source_root=source_root,
        device_rel="iTunes_Control/Music/F08/GOOD.mp3",
    )

    m.write_media(track, mount)

    final = mount / track.device_rel
    partial = final.with_name(final.name + ".ipodctl-part")

    assert final.is_file()
    assert final.read_bytes() == payload
    assert final.stat().st_size == len(payload)
    assert m.sha256_file(final) == hashlib.sha256(payload).hexdigest()
    assert not partial.exists()


# ---------------------------------------------------------------------------
# 4. Even if write_media() is reached with stale planned source metadata,
#    its streaming verification must fail, remove its partial file, and never
#    publish the final destination.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source_root = root / "source"
    mount = root / "device"

    source_root.mkdir()
    mount.mkdir()

    source = source_root / "track.mp3"
    source.write_bytes(b"stream-original-A\n")

    track = make_track(
        source,
        source_root=source_root,
        device_rel="iTunes_Control/Music/F09/FAIL.mp3",
    )

    replacement = b"stream-tampered-B\n"
    assert len(replacement) == track.source_size
    source.write_bytes(replacement)

    final = mount / track.device_rel
    final.parent.mkdir(parents=True, exist_ok=True)

    before = snapshot(mount)

    expect_sync_error(
        lambda: m.write_media(track, mount),
        "stream verification failed",
    )

    partial = final.with_name(final.name + ".ipodctl-part")

    assert not final.exists()
    assert not partial.exists()
    assert snapshot(mount) == before


# ---------------------------------------------------------------------------
# 5. Live database preimage drift must be detected before database commit.
#    Verification itself must make no further change to the device tree.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    mount = Path(td) / "device"
    mount.mkdir()

    paths = create_live_snapshot_files(mount)

    expected = {
        name: m.sha256_file(paths[name])
        for name in m.SNAPSHOT_NAMES
    }

    paths["Dynamic.itdb"].write_bytes(
        b"unexpected-live-preimage-drift\n"
    )

    before = snapshot(mount)

    expect_sync_error(
        lambda: m.verify_live_preimage_hashes(mount, expected),
        "live preimage mismatch for Dynamic.itdb",
    )

    assert snapshot(mount) == before


# ---------------------------------------------------------------------------
# 6. Rollback snapshots are themselves trusted recovery inputs.
#    If one changes after capture, validation must fail closed.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    rollback_root = Path(td) / "rollback"
    rollback_root.mkdir()

    rollback = {}

    for index, name in enumerate(m.SNAPSHOT_NAMES, 1):
        path = rollback_root / name
        path.write_bytes(
            f"rollback-{index}-{name}\n".encode("utf-8")
        )
        rollback[name] = path

    expected = {
        name: m.sha256_file(path)
        for name, path in rollback.items()
    }

    rollback["Library.itdb"].write_bytes(
        b"corrupted-rollback-library\n"
    )

    before = snapshot(rollback_root)

    expect_sync_error(
        lambda: m.validate_rollback_snapshots(
            rollback,
            expected,
        ),
        "rollback snapshot hash changed: Library.itdb",
    )

    assert snapshot(rollback_root) == before


# ---------------------------------------------------------------------------
# 7. Pre-write recovery is explicitly a no-write cleanup path.
#
# If transaction media already exists, it must refuse to "clean it up" or
# proceed to deeper recovery checks.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source_root = root / "source"
    mount = root / "device"

    source_root.mkdir()
    mount.mkdir()

    source = source_root / "track.mp3"
    source.write_bytes(b"prewrite-leftover-test\n")

    track = make_track(
        source,
        source_root=source_root,
        device_rel="iTunes_Control/Music/F10/LEFT.mp3",
    )

    final = mount / track.device_rel
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"unexpected-transaction-output\n")

    before = snapshot(mount)

    expect_sync_error(
        lambda: m.verify_prewrite_noop_state(
            {},
            mount,
            [track],
            {},
        ),
        "pre-write recovery found transaction output",
    )

    # Refusal really is no-write: it must not remove the suspicious media.
    assert snapshot(mount) == before


print("transaction safety tests: PASS")
