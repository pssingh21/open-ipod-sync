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
    "ipod_sync_apply_transaction_test",
    APP,
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


ORIG_VALIDATE_TRACKS_SOURCE = m.validate_tracks_source
ORIG_VALIDATE_DESTINATIONS_ABSENT = m.validate_destinations_absent
ORIG_BACKUP_DATABASES = m.backup_databases
ORIG_VERIFY_LIVE_PREIMAGE_HASHES = m.verify_live_preimage_hashes
ORIG_CANDIDATE_HASHES = m.candidate_hashes
ORIG_WRITE_MEDIA = m.write_media
ORIG_SAFE_REPLACE_FILE = m.safe_replace_file
ORIG_ROLLBACK_UNDER_LOCK = m.rollback_under_lock


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


def expect_sync_error(fn, expected: str):
    try:
        fn()
    except m.SyncError as exc:
        message = str(exc)
        assert expected in message, (expected, message)
        return message

    raise AssertionError(f"expected SyncError containing: {expected!r}")


def make_fixture(root: Path, track_count: int = 1):
    source = root / "source"
    mount = root / "device"
    run_dir = root / "run"
    candidate_dir = root / "candidate"
    state_dir = root / "state"

    source.mkdir()
    mount.mkdir()
    run_dir.mkdir()
    candidate_dir.mkdir()
    state_dir.mkdir()

    live = m.live_paths(mount)

    for index, name in enumerate(m.SNAPSHOT_NAMES, 1):
        path = live[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            f"live-preimage-{index}-{name}\n".encode("utf-8")
        )

    candidate_files = {}

    for index, name in enumerate(m.REPLACED_DB_NAMES, 1):
        path = candidate_dir / name
        path.write_bytes(
            f"candidate-{index}-{name}\n".encode("utf-8")
        )
        candidate_files[name] = path

    tracks = []

    for index in range(track_count):
        payload = f"track-{index}-payload\n".encode("utf-8")
        src = source / f"track-{index}.mp3"
        src.write_bytes(payload)

        digest = m.sha256_file(src)

        tracks.append(
            m.Track(
                source=src,
                source_rel=src.relative_to(source).as_posix(),
                title=src.stem,
                sha256=digest,
                source_size=src.stat().st_size,
                duration_ms=180000,
                bitrate_kbps=256,
                sample_rate_hz=44100,
                direct_mp3=True,
                folder=f"F{index:02d}",
                basename=f"T{index:03d}.mp3",
                device_rel=(
                    f"iTunes_Control/Music/"
                    f"F{index:02d}/T{index:03d}.mp3"
                ),
                apple_path=(
                    f":iTunes_Control:Music:"
                    f"F{index:02d}:T{index:03d}.mp3"
                ),
                output_size=src.stat().st_size,
                output_sha256=digest,
            )
        )

    candidate = m.Candidate(
        workdir=candidate_dir,
        library=candidate_files["Library.itdb"],
        dynamic=candidate_files["Dynamic.itdb"],
        locations=candidate_files["Locations.itdb"],
        cbk=candidate_files["Locations.itdb.cbk"],
        cdb=candidate_files["iTunesCDB"],
        tracks=tracks,
        mode="generic-incremental-add",
    )

    return {
        "source": source,
        "mount": mount,
        "run_dir": run_dir,
        "state_dir": state_dir,
        "candidate": candidate,
        "live": live,
    }


def live_hashes_for(names, mount: Path):
    live = m.live_paths(mount)
    return {
        name: m.sha256_file(live[name])
        for name in names
    }


def verify_core_without_sqlite(mount: Path, expected: dict[str, str]):
    live = m.live_paths(mount)

    for name in m.REPLACED_DB_NAMES:
        actual = m.sha256_file(live[name])
        assert actual == expected[name], (name, actual, expected[name])

    assert (
        m.sha256_file(live["HashInfo"])
        == expected["HashInfo"]
    )


def make_common_patches(fx, events, envelope_cls=None):
    guard = object()

    class GoodEnvelope:
        def __init__(self, helper):
            self.helper = helper

        def __enter__(self):
            events.append("envelope-enter")
            return self

        def close(self):
            events.append("envelope-close")

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

    if envelope_cls is None:
        envelope_cls = GoodEnvelope

    def require_ifuse_mount(mount, writable=None):
        events.append(f"require-mount-{writable}")

    def remount_ifuse(mount, *, writable):
        events.append(f"remount-{writable}")

    def validate_tracks_source(tracks, source_root, source_guard=None):
        events.append("validate-source")
        # Keep real source size/hash/root validation. The kernel RO guard itself
        # is represented by the synthetic guard in this orchestration test.
        return ORIG_VALIDATE_TRACKS_SOURCE(
            tracks,
            source_root,
            None,
        )

    def validate_candidate(candidate, mount, run_dir):
        events.append("validate-candidate")

    def validate_destinations_absent(tracks, mount):
        events.append("validate-destinations")
        return ORIG_VALIDATE_DESTINATIONS_ABSENT(tracks, mount)

    def backup_databases(mount, run_dir):
        events.append("backup-databases")
        return ORIG_BACKUP_DATABASES(mount, run_dir)

    def verify_live_preimage_hashes(mount, expected):
        events.append("verify-live-preimage")
        return ORIG_VERIFY_LIVE_PREIMAGE_HASHES(mount, expected)

    def recheck_source_guard(source_guard):
        assert source_guard is guard
        events.append("recheck-source")

    def candidate_hashes(candidate):
        events.append("candidate-hashes")
        return ORIG_CANDIDATE_HASHES(candidate)

    def write_media(track, mount):
        events.append(f"write-media:{track.source_rel}")
        return ORIG_WRITE_MEDIA(track, mount)

    def safe_replace_file(src, dst):
        rollback_root = (fx["run_dir"] / "rollback").resolve()
        src_path = Path(src).resolve()

        try:
            src_path.relative_to(rollback_root)
            operation = "restore-db"
        except ValueError:
            operation = "replace-db"

        events.append(f"{operation}:{dst.name}")
        return ORIG_SAFE_REPLACE_FILE(src, dst)

    def post_validate(mount, tracks, candidate, extras_snapshot, run_dir):
        events.append("post-validate")

    def update_state(tracks, mode):
        events.append("update-state")

    return {
        "ACTIVE_TXN": fx["state_dir"] / "active.json",
        "SYNC_STATE": fx["state_dir"] / "sync-state.json",
        "verify_device_connection": lambda: events.append(
            "verify-device"
        ) or "synthetic-device",
        "require_source_ro": lambda source: (
            events.append("require-source-ro") or guard
        ),
        "assert_no_write_roots_on_source": lambda source_guard, mount: (
            events.append("assert-source-isolation")
        ),
        "require_ifuse_mount": require_ifuse_mount,
        "validate_tracks_source": validate_tracks_source,
        "validate_candidate": validate_candidate,
        "validate_destinations_absent": validate_destinations_absent,
        "free_bytes": lambda mount: 10**12,
        "backup_databases": backup_databases,
        "remount_ifuse": remount_ifuse,
        "verify_live_preimage_hashes": verify_live_preimage_hashes,
        "recheck_source_guard": recheck_source_guard,
        "candidate_hashes": candidate_hashes,
        "SyncEnvelope": envelope_cls,
        "write_media": write_media,
        "safe_replace_file": safe_replace_file,
        "post_validate": post_validate,
        "update_state": update_state,
    }


# ---------------------------------------------------------------------------
# 1. Pre-RW validation failure.
#
# Candidate validation must fail before:
#   - rollback snapshots,
#   - active journal creation,
#   - RW remount,
#   - media writing.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), track_count=1)
    events = []

    patches = make_common_patches(fx, events)

    def reject_candidate(candidate, mount, run_dir):
        events.append("validate-candidate")
        raise m.SyncError("injected candidate validation failure")

    patches["validate_candidate"] = reject_candidate

    with patched(**patches):
        expect_sync_error(
            lambda: m.apply_transaction(
                fx["source"],
                fx["mount"],
                fx["candidate"],
                fx["run_dir"],
            ),
            "injected candidate validation failure",
        )

        assert "validate-source" in events
        assert "validate-candidate" in events

        assert "backup-databases" not in events
        assert "remount-True" not in events
        assert not any(x.startswith("write-media:") for x in events)

        assert not m.ACTIVE_TXN.exists()
        assert not (fx["run_dir"] / "rollback").exists()


# ---------------------------------------------------------------------------
# 2. Fully successful synthetic transaction.
#
# This exercises the real:
#   - rollback snapshot copying,
#   - active journal files,
#   - direct MP3 media writer,
#   - candidate hash checks,
#   - database replacement,
#   - COMMIT.json creation,
# while mocking only hardware-facing/device-protocol boundaries.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), track_count=2)
    events = []

    patches = make_common_patches(fx, events)

    with patched(**patches):
        m.apply_transaction(
            fx["source"],
            fx["mount"],
            fx["candidate"],
            fx["run_dir"],
        )

        assert not m.ACTIVE_TXN.exists()

    # Preflight ordering.
    assert events.index("validate-source") < events.index("validate-candidate")
    assert events.index("validate-candidate") < events.index("backup-databases")
    assert events.index("backup-databases") < events.index("remount-True")

    # RW preimage validation happens before the sync envelope.
    first_preimage = events.index("verify-live-preimage")
    assert events.index("remount-True") < first_preimage
    assert first_preimage < events.index("envelope-enter")

    # One RO-source recheck before opening the envelope plus one before every
    # source/media read.
    assert events.count("recheck-source") == len(fx["candidate"].tracks) + 1

    write_events = [
        x for x in events
        if x.startswith("write-media:")
    ]
    assert len(write_events) == 2

    # There must be a second live-preimage verification immediately before DB
    # replacement.
    preimage_positions = [
        i for i, event in enumerate(events)
        if event == "verify-live-preimage"
    ]
    assert len(preimage_positions) == 2

    replacement_positions = [
        i for i, event in enumerate(events)
        if event.startswith("replace-db:")
    ]
    assert len(replacement_positions) == 5
    assert preimage_positions[1] < replacement_positions[0]

    # RW -> RO lifecycle.
    remounts = [
        event for event in events
        if event.startswith("remount-")
    ]
    assert remounts == ["remount-True", "remount-False"]

    assert "envelope-close" in events
    assert "post-validate" in events
    assert "update-state" in events

    for track in fx["candidate"].tracks:
        final = fx["mount"] / track.device_rel
        assert final.is_file()
        assert m.sha256_file(final) == track.output_sha256

    live = m.live_paths(fx["mount"])

    assert live["Library.itdb"].read_bytes() == fx["candidate"].library.read_bytes()
    assert live["Dynamic.itdb"].read_bytes() == fx["candidate"].dynamic.read_bytes()
    assert live["Locations.itdb"].read_bytes() == fx["candidate"].locations.read_bytes()
    assert live["Locations.itdb.cbk"].read_bytes() == fx["candidate"].cbk.read_bytes()
    assert live["iTunesCDB"].read_bytes() == fx["candidate"].cdb.read_bytes()

    commit_path = fx["run_dir"] / "COMMIT.json"
    assert commit_path.is_file()

    commit = json.loads(commit_path.read_text())
    assert commit["status"] == "PASS"
    assert commit["tracks_added"] == 2
    assert commit["device_read_only"] is True


# ---------------------------------------------------------------------------
# 3. Media failure after one successful media copy.
#
# The first transaction media file must be removed and database preimage
# restored. Since the envelope closes successfully, the active recovery journal
# should be cleared and ROLLBACK.json should record PASS.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), track_count=2)
    events = []

    original_live = live_hashes_for(
        m.SNAPSHOT_NAMES,
        fx["mount"],
    )

    patches = make_common_patches(fx, events)

    def injected_write_media(track, mount):
        nonlocal_holder[0] += 1
        events.append(f"write-media:{track.source_rel}")

        if nonlocal_holder[0] == 1:
            return ORIG_WRITE_MEDIA(track, mount)

        raise m.SyncError("injected second media failure")

    # Python module-level test code cannot use nonlocal, so use a mutable cell.
    nonlocal_holder = [0]

    patches["write_media"] = injected_write_media
    patches["verify_core_rollback"] = verify_core_without_sqlite

    with patched(**patches):
        message = expect_sync_error(
            lambda: m.apply_transaction(
                fx["source"],
                fx["mount"],
                fx["candidate"],
                fx["run_dir"],
            ),
            "transaction aborted and rolled back safely",
        )

        assert "injected second media failure" in message
        assert not m.ACTIVE_TXN.exists()

    for track in fx["candidate"].tracks:
        assert not (fx["mount"] / track.device_rel).exists()

    restored = live_hashes_for(
        m.SNAPSHOT_NAMES,
        fx["mount"],
    )

    for name in m.REPLACED_DB_NAMES:
        assert restored[name] == original_live[name]

    assert restored["HashInfo"] == original_live["HashInfo"]

    rollback_result = json.loads(
        (fx["run_dir"] / "ROLLBACK.json").read_text()
    )
    assert rollback_result["status"] == "PASS"

    assert "envelope-close" in events
    assert "remount-False" in events


# ---------------------------------------------------------------------------
# 4. Candidate database mutation during media transfer.
#
# Candidate hashes are frozen in the journal before RW. Mutating one candidate
# DB after media copying must be caught before the first live DB replacement.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), track_count=1)
    events = []

    original_live = live_hashes_for(
        m.SNAPSHOT_NAMES,
        fx["mount"],
    )

    patches = make_common_patches(fx, events)

    def mutate_candidate_after_media(track, mount):
        events.append(f"write-media:{track.source_rel}")
        ORIG_WRITE_MEDIA(track, mount)

        fx["candidate"].dynamic.write_bytes(
            b"candidate-mutated-after-media\n"
        )

    patches["write_media"] = mutate_candidate_after_media
    patches["verify_core_rollback"] = verify_core_without_sqlite

    with patched(**patches):
        message = expect_sync_error(
            lambda: m.apply_transaction(
                fx["source"],
                fx["mount"],
                fx["candidate"],
                fx["run_dir"],
            ),
            "transaction aborted and rolled back safely",
        )

        assert (
            "candidate database files changed during media transfer"
            in message
        )

        assert not m.ACTIVE_TXN.exists()

    assert not any(
        event.startswith("replace-db:")
        for event in events
    )

    for track in fx["candidate"].tracks:
        assert not (fx["mount"] / track.device_rel).exists()

    restored = live_hashes_for(
        m.SNAPSHOT_NAMES,
        fx["mount"],
    )

    for name in m.REPLACED_DB_NAMES:
        assert restored[name] == original_live[name]


# ---------------------------------------------------------------------------
# 5. Live preimage changes immediately after RW remount.
#
# This simulates external/device-side drift in the RO->RW transition window.
# It must be detected before:
#   - sync envelope acquisition,
#   - media copying,
#   - database replacement.
#
# Since the app has not written anything yet, no rollback operation should be
# attempted. The prepared recovery journal remains for explicit inspection.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), track_count=1)
    events = []

    patches = make_common_patches(fx, events)

    def drifting_remount(mount, *, writable):
        events.append(f"remount-{writable}")

        if writable:
            m.live_paths(mount)["Dynamic.itdb"].write_bytes(
                b"externally-drifted-after-rw-remount\n"
            )

    patches["remount_ifuse"] = drifting_remount

    with patched(**patches):
        expect_sync_error(
            lambda: m.apply_transaction(
                fx["source"],
                fx["mount"],
                fx["candidate"],
                fx["run_dir"],
            ),
            "live preimage mismatch for Dynamic.itdb",
        )

        assert m.ACTIVE_TXN.exists()

        journal = json.loads(m.ACTIVE_TXN.read_text())
        assert journal["phase"] == "prepared"

    assert "envelope-enter" not in events
    assert not any(x.startswith("write-media:") for x in events)
    assert not any(x.startswith("replace-db:") for x in events)

    for track in fx["candidate"].tracks:
        assert not (fx["mount"] / track.device_rel).exists()

    assert events[-1] == "remount-False"


# ---------------------------------------------------------------------------
# 6. Sync-envelope close failure after DB commit.
#
# The transaction has already written media and databases at this point.
# A close/notification failure must therefore trigger the fresh rollback path.
#
# Because the original envelope did not close successfully, the persistent
# recovery journal intentionally remains rather than falsely claiming a fully
# clean transaction completion.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    fx = make_fixture(Path(td), track_count=1)
    events = []

    original_live = live_hashes_for(
        m.SNAPSHOT_NAMES,
        fx["mount"],
    )

    class CloseFailEnvelope:
        def __init__(self, helper):
            self.helper = helper

        def __enter__(self):
            events.append("envelope-enter")
            return self

        def close(self):
            events.append("envelope-close-fail")
            raise m.SyncError("injected envelope close failure")

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

    patches = make_common_patches(
        fx,
        events,
        envelope_cls=CloseFailEnvelope,
    )

    patches["verify_core_rollback"] = verify_core_without_sqlite

    def fresh_rollback(rollback, mount, tracks, pre_hash):
        events.append("fresh-envelope-rollback")
        ORIG_ROLLBACK_UNDER_LOCK(
            rollback,
            mount,
            tracks,
            pre_hash,
        )

    patches["fresh_envelope_rollback"] = fresh_rollback

    with patched(**patches):
        message = expect_sync_error(
            lambda: m.apply_transaction(
                fx["source"],
                fx["mount"],
                fx["candidate"],
                fx["run_dir"],
            ),
            "transaction incomplete; persistent recovery journal preserved",
        )

        assert "transaction incomplete" in message
        assert m.ACTIVE_TXN.exists()

        journal = json.loads(m.ACTIVE_TXN.read_text())
        assert journal["phase"] == "rollback-complete-after-close-failure"

    assert "fresh-envelope-rollback" in events
    assert "remount-False" in events

    for track in fx["candidate"].tracks:
        assert not (fx["mount"] / track.device_rel).exists()

    restored = live_hashes_for(
        m.SNAPSHOT_NAMES,
        fx["mount"],
    )

    for name in m.REPLACED_DB_NAMES:
        assert restored[name] == original_live[name]

    assert restored["HashInfo"] == original_live["HashInfo"]


print("apply transaction orchestration tests: PASS")
