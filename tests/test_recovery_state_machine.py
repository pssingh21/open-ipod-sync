#!/usr/bin/env python3

from contextlib import contextmanager
from pathlib import Path
import importlib.util
import json
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/ipod_sync.py"

spec = importlib.util.spec_from_file_location(
    "ipod_sync_recovery_state_test",
    APP,
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


@contextmanager
def patched(**replacements):
    originals = {}
    try:
        for name, value in replacements.items():
            originals[name] = getattr(m, name)
            setattr(m, name, value)
        yield
    finally:
        for name, value in reversed(list(originals.items())):
            setattr(m, name, value)


def expect_sync_error(fn, expected):
    try:
        fn()
    except m.SyncError as exc:
        message = str(exc)
        assert expected in message, (expected, message)
        return message
    raise AssertionError(f"expected SyncError containing {expected!r}")


def good_report():
    return {
        "library_cp_sequence_before": 10,
        "library_cp_sequence_after": 10,
        "library_only_cp_sequence_drift": False,
        "extras_semantically_equal": True,
        "exact_files": [
            "Dynamic.itdb",
            "Locations.itdb",
            "Locations.itdb.cbk",
            "iTunesCDB",
            "HashInfo",
        ],
        "transaction_media_absent": True,
    }


def make_fixture(root: Path, phase="prepared"):
    mount = root / "device"
    run_dir = root / "run"
    rollback_dir = run_dir / "rollback"
    state_dir = root / "state"

    mount.mkdir()
    rollback_dir.mkdir(parents=True)
    state_dir.mkdir()

    rollback = {}
    pre_hash = {}
    live = m.live_paths(mount)

    for i, name in enumerate(m.SNAPSHOT_NAMES, 1):
        payload = f"rollback-{i}-{name}\n".encode()

        rollback_path = rollback_dir / name
        rollback_path.write_bytes(payload)
        rollback[name] = rollback_path
        pre_hash[name] = m.sha256_file(rollback_path)

        live_path = live[name]
        live_path.parent.mkdir(parents=True, exist_ok=True)
        live_path.write_bytes(payload)

    track = m.Track(
        source=Path("/nonexistent-recovery-source"),
        source_rel="track.mp3",
        title="track",
        sha256="a" * 64,
        source_size=123,
        duration_ms=0,
        bitrate_kbps=0,
        sample_rate_hz=0,
        direct_mp3=True,
        dbid_u64=1234,
        pid=1234,
        folder="F00",
        basename="TEST.mp3",
        device_rel="iTunes_Control/Music/F00/TEST.mp3",
        apple_path=":iTunes_Control:Music:F00:TEST.mp3",
        output_size=123,
        output_sha256="a" * 64,
    )

    active = state_dir / "active.json"

    journal = {
        "app": m.APP,
        "version": m.VERSION,
        "run_dir": str(run_dir),
        "phase": phase,
        "preimage_sha256": pre_hash,
        "candidate_sha256": {},
        "candidate_mode": "generic-incremental-add",
        "tracks": m.tracks_to_journal([track]),
    }

    active.write_text(json.dumps(journal))

    return {
        "mount": mount,
        "run_dir": run_dir,
        "rollback": rollback,
        "pre_hash": pre_hash,
        "track": track,
        "active": active,
    }


def common_patches(fx, events):
    class Envelope:
        def __init__(self, helper):
            self.helper = helper

        def __enter__(self):
            events.append("envelope-enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append("envelope-exit")
            return False

    def require_ifuse_mount(mount, writable=None):
        events.append(f"require-mount-{writable}")

    def remount_ifuse(mount, *, writable):
        events.append(f"remount-{writable}")

    return {
        "ACTIVE_TXN": fx["active"],
        "verify_device_connection":
            lambda: events.append("verify-device") or "synthetic-device",
        "require_ifuse_mount": require_ifuse_mount,
        "remount_ifuse": remount_ifuse,
        "SyncEnvelope": Envelope,
    }


# ---------------------------------------------------------------------------
# 1. recover_check is genuinely read-only.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), "prepared")
    events = []
    before = fx["active"].read_bytes()

    patches = common_patches(fx, events)
    patches["verify_prewrite_noop_state"] = (
        lambda rollback, mount, tracks, pre_hash: good_report()
    )

    with patched(**patches):
        rc = m.recover_check(fx["mount"])

    assert rc == 0
    assert fx["active"].is_file()
    assert fx["active"].read_bytes() == before
    assert "remount-True" not in events
    assert "envelope-enter" not in events
    assert not (fx["run_dir"] / "RECOVERY.json").exists()


# ---------------------------------------------------------------------------
# 2. recover_check cannot prove safety: still no write and journal preserved.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), "media-copying")
    events = []
    before = fx["active"].read_bytes()

    def reject_noop(*args):
        raise m.SyncError("synthetic transaction media exists")

    patches = common_patches(fx, events)
    patches["verify_prewrite_noop_state"] = reject_noop

    with patched(**patches):
        rc = m.recover_check(fx["mount"])

    assert rc == 2
    assert fx["active"].read_bytes() == before
    assert "remount-True" not in events
    assert "envelope-enter" not in events


# ---------------------------------------------------------------------------
# 3. prepared interruption proven untouched: cleanup is read-only.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), "prepared")
    events = []

    patches = common_patches(fx, events)
    patches["verify_prewrite_noop_state"] = (
        lambda rollback, mount, tracks, pre_hash: good_report()
    )

    with patched(**patches):
        rc = m.recover_transaction(fx["mount"])

    assert rc == 0
    assert not fx["active"].exists()
    assert "remount-True" not in events
    assert "envelope-enter" not in events

    report = json.loads(
        (fx["run_dir"] / "RECOVERY.json").read_text()
    )
    assert report["status"] == "PASS"
    assert report["mode"] == "pre-write-interruption"
    assert report["interrupted_phase"] == "prepared"


# ---------------------------------------------------------------------------
# 4. Already-completed rollback also needs no device write.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(
        Path(td),
        "rollback-complete-after-close-failure",
    )
    events = []

    patches = common_patches(fx, events)
    patches["verify_prewrite_noop_state"] = (
        lambda rollback, mount, tracks, pre_hash: good_report()
    )

    with patched(**patches):
        rc = m.recover_transaction(fx["mount"])

    assert rc == 0
    assert not fx["active"].exists()
    assert "remount-True" not in events

    report = json.loads(
        (fx["run_dir"] / "RECOVERY.json").read_text()
    )
    assert report["mode"] == "rollback-already-complete"


# ---------------------------------------------------------------------------
# 5. Recovery requiring writes:
#    RW -> sync envelope -> rollback -> RO -> verify -> clear journal.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), "media-copying")
    events = []

    final = fx["mount"] / fx["track"].device_rel
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"partial transaction media\n")

    def reject_noop(*args):
        raise m.SyncError("device differs from preimage")

    def rollback_under_lock(rollback, mount, tracks, pre_hash):
        events.append("rollback-under-lock")
        for track in tracks:
            p = mount / track.device_rel
            p.unlink(missing_ok=True)

    def verify_core_rollback(mount, pre_hash):
        events.append("verify-core-rollback")

    patches = common_patches(fx, events)
    patches.update({
        "verify_prewrite_noop_state": reject_noop,
        "rollback_under_lock": rollback_under_lock,
        "verify_core_rollback": verify_core_rollback,
    })

    with patched(**patches):
        rc = m.recover_transaction(fx["mount"])

    assert rc == 0
    assert not fx["active"].exists()
    assert not final.exists()

    assert events.index("remount-True") < events.index("envelope-enter")
    assert events.index("envelope-enter") < events.index("rollback-under-lock")
    assert events.index("rollback-under-lock") < events.index("envelope-exit")
    assert events.index("envelope-exit") < events.index("remount-False")
    assert events.index("remount-False") < events.index("verify-core-rollback")

    report = json.loads(
        (fx["run_dir"] / "RECOVERY.json").read_text()
    )
    assert report["status"] == "PASS"


# ---------------------------------------------------------------------------
# 6. Failed automatic recovery preserves a recovery-failed journal.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), "db-commit-started")
    events = []

    def reject_noop(*args):
        raise m.SyncError("requires real rollback")

    def fail_rollback(*args):
        events.append("rollback-under-lock-fail")
        raise m.SyncError("synthetic rollback failure")

    patches = common_patches(fx, events)
    patches.update({
        "verify_prewrite_noop_state": reject_noop,
        "rollback_under_lock": fail_rollback,
    })

    with patched(**patches):
        expect_sync_error(
            lambda: m.recover_transaction(fx["mount"]),
            "automatic recovery did not complete",
        )

        assert fx["active"].exists()
        journal = json.loads(fx["active"].read_text())
        assert journal["phase"] == "recovery-failed"
        assert "synthetic rollback failure" in journal["error"]

    assert "remount-True" in events
    assert "remount-False" in events


# ---------------------------------------------------------------------------
# 7. Corrupted rollback input fails before any writable remount.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), "media-complete")
    events = []

    fx["rollback"]["Library.itdb"].write_bytes(
        b"corrupted rollback snapshot\n"
    )

    patches = common_patches(fx, events)

    with patched(**patches):
        expect_sync_error(
            lambda: m.recover_transaction(fx["mount"]),
            "rollback snapshot hash changed: Library.itdb",
        )

    assert fx["active"].exists()
    assert "remount-True" not in events
    assert "envelope-enter" not in events


# ---------------------------------------------------------------------------
# 8. Unknown journal phases fail closed.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), "totally-unknown-phase")
    events = []

    patches = common_patches(fx, events)

    with patched(**patches):
        expect_sync_error(
            lambda: m.recover_transaction(fx["mount"]),
            "unknown or non-recoverable transaction journal phase",
        )

    assert fx["active"].exists()
    assert "verify-device" not in events
    assert "remount-True" not in events


# ---------------------------------------------------------------------------
# 9. A durable COMMIT record is authoritative for stale-journal cleanup.
#    No device connection/remount is needed.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), "committed")
    events = []

    (fx["run_dir"] / "COMMIT.json").write_text(
        json.dumps({"status": "PASS"})
    )

    patches = common_patches(fx, events)

    with patched(**patches):
        rc = m.recover_transaction(fx["mount"])

    assert rc == 0
    assert not fx["active"].exists()
    assert "verify-device" not in events
    assert "remount-True" not in events
    assert "envelope-enter" not in events


print("recovery state machine tests: PASS")
