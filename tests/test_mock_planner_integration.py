#!/usr/bin/env python3

from pathlib import Path
import contextlib
import hashlib
import importlib.util
import io
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/ipod_sync.py"

spec = importlib.util.spec_from_file_location(
    "ipod_sync_mock_planner_test",
    APP,
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

# Fixture files intentionally contain deterministic test bytes rather than
# encoded audio. Keep all planner/hash/filesystem behavior real and replace
# only the unrelated audio-metadata probe.
m.probe_audio = lambda _path: (180000, 256, 44100)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_file(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def tree_snapshot(root: Path):
    """
    Capture both directory structure and file content.

    This lets the test prove that planning did not create, delete,
    or modify anything in the synthetic source/device trees.
    """
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


def build_device(
    mount: Path,
    media_rows: list[tuple[int, str, bytes]],
):
    """
    Build the minimum real SQLite/device structure required by
    library_rows() and _device_media_hash_counts().

    media_rows:
        (pid, Locations.itdb location, media bytes)
    """
    live = m.live_paths(mount)

    library = live["Library.itdb"]
    locations = live["Locations.itdb"]

    library.parent.mkdir(parents=True, exist_ok=True)
    locations.parent.mkdir(parents=True, exist_ok=True)

    for pid, location, payload in media_rows:
        rel = m._location_to_device_rel(location)
        write_file(mount / rel, payload)

    con = sqlite3.connect(library)
    try:
        con.execute(
            """
            CREATE TABLE item (
                pid INTEGER PRIMARY KEY,
                title TEXT,
                artist TEXT,
                album TEXT,
                album_artist TEXT,
                is_song INTEGER,
                media_kind INTEGER,
                sort_title TEXT
            )
            """
        )

        for pid, _location, _payload in media_rows:
            con.execute(
                """
                INSERT INTO item (
                    pid,
                    title,
                    artist,
                    album,
                    album_artist,
                    is_song,
                    media_kind,
                    sort_title
                )
                VALUES (?, ?, '', '', '', 1, 1, ?)
                """,
                (
                    pid,
                    f"device-title-{pid}",
                    f"device-sort-{pid}",
                ),
            )

        con.commit()
    finally:
        con.close()

    con = sqlite3.connect(locations)
    try:
        con.execute(
            """
            CREATE TABLE location (
                item_pid INTEGER,
                location TEXT
            )
            """
        )

        for pid, location, _payload in media_rows:
            con.execute(
                """
                INSERT INTO location (item_pid, location)
                VALUES (?, ?)
                """,
                (pid, location),
            )

        con.commit()
    finally:
        con.close()


def run_plan(source: Path, mount: Path, run_dir: Path):
    stdout = io.StringIO()

    with contextlib.redirect_stdout(stdout):
        adds = m.plan_generic(source, mount, run_dir)

    return adds, stdout.getvalue()


PAYLOAD_A = b"mock-track-A-content\n"
PAYLOAD_B = b"mock-track-B-content\n"
PAYLOAD_C = b"mock-track-C-content\n"


# ---------------------------------------------------------------------------
# Case 1:
#
# Device:
#   A x1
#   B x2
#
# Source:
#   A x1, under a completely different filename
#   B x2
#   C x1
#
# Expected:
#   three content matches
#   exactly C is new
#
# This proves matching is content-based rather than title/filename-based and
# that equal-content multiplicity is consumed correctly.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"
    run_dir = root / "run"

    source.mkdir()
    mount.mkdir()
    run_dir.mkdir()

    build_device(
        mount,
        [
            (101, "F00/A001.mp3", PAYLOAD_A),
            (102, "F01/B001.mp3", PAYLOAD_B),
            (103, "F02/B002.mp3", PAYLOAD_B),
        ],
    )

    write_file(source / "renamed-A.mp3", PAYLOAD_A)
    write_file(source / "copy-B-1.mp3", PAYLOAD_B)
    write_file(source / "copy-B-2.mp3", PAYLOAD_B)
    write_file(source / "new-C.mp3", PAYLOAD_C)

    source_before = tree_snapshot(source)
    device_before = tree_snapshot(mount)

    adds, output = run_plan(source, mount, run_dir)

    source_after = tree_snapshot(source)
    device_after = tree_snapshot(mount)

    assert source_after == source_before, "planner modified synthetic source tree"
    assert device_after == device_before, "planner modified synthetic device tree"

    assert "content-matched existing source tracks: 3/4" in output, output
    assert "new source tracks by content:          1" in output, output

    assert len(adds) == 1, adds

    track = adds[0]

    assert track.source_rel == "new-C.mp3", track
    assert track.title == "new-C", track
    assert track.sha256 == sha256_bytes(PAYLOAD_C), track
    assert track.output_sha256 == sha256_bytes(PAYLOAD_C), track
    assert track.output_size == len(PAYLOAD_C), track
    assert track.direct_mp3 is True, track

    # Destination allocation is planning metadata only. Nothing must have
    # appeared on the synthetic device.
    assert track.device_rel.startswith("iTunes_Control/Music/F"), track
    assert track.device_rel.endswith(".mp3"), track
    assert not (mount / track.device_rel).exists(), track.device_rel


# ---------------------------------------------------------------------------
# Case 2:
#
# Device:
#   B x2
#
# Source:
#   B x3
#
# Expected:
#   first two consume the two device occurrences;
#   third occurrence becomes exactly one ADD.
#
# This specifically guards against collapsing equal-content files into a set
# instead of retaining multiplicity.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"
    run_dir = root / "run"

    source.mkdir()
    mount.mkdir()
    run_dir.mkdir()

    build_device(
        mount,
        [
            (201, ":iTunes_Control:Music:F10:B101.mp3", PAYLOAD_B),
            (202, "iTunes_Control/Music/F11/B102.mp3", PAYLOAD_B),
        ],
    )

    write_file(source / "copy-B-1.mp3", PAYLOAD_B)
    write_file(source / "copy-B-2.mp3", PAYLOAD_B)
    write_file(source / "copy-B-3.mp3", PAYLOAD_B)

    source_before = tree_snapshot(source)
    device_before = tree_snapshot(mount)

    adds, output = run_plan(source, mount, run_dir)

    assert tree_snapshot(source) == source_before
    assert tree_snapshot(mount) == device_before

    assert "content-matched existing source tracks: 2/3" in output, output
    assert "new source tracks by content:          1" in output, output

    assert len(adds) == 1, adds
    assert adds[0].source_rel == "copy-B-3.mp3", adds[0]
    assert adds[0].output_sha256 == sha256_bytes(PAYLOAD_B)

    assert not (mount / adds[0].device_rel).exists()


# ---------------------------------------------------------------------------
# Case 3:
#
# Everything in the source already exists on-device by content, despite
# unrelated filenames/titles.
#
# Expected:
#   zero ADDs and zero filesystem changes.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"
    run_dir = root / "run"

    source.mkdir()
    mount.mkdir()
    run_dir.mkdir()

    build_device(
        mount,
        [
            (301, "Music/F20/X001.mp3", PAYLOAD_A),
            (302, "F21/X002.mp3", PAYLOAD_B),
        ],
    )

    write_file(source / "totally-renamed-one.mp3", PAYLOAD_A)
    write_file(source / "totally-renamed-two.mp3", PAYLOAD_B)

    source_before = tree_snapshot(source)
    device_before = tree_snapshot(mount)

    adds, output = run_plan(source, mount, run_dir)

    assert adds == [], adds
    assert "content-matched existing source tracks: 2/2" in output, output
    assert "new source tracks by content:          0" in output, output

    assert tree_snapshot(source) == source_before
    assert tree_snapshot(mount) == device_before



def expect_sync_error(source: Path, mount: Path, run_dir: Path, expected: str):
    try:
        run_plan(source, mount, run_dir)
    except m.SyncError as exc:
        message = str(exc)
        assert expected in message, (expected, message)
        return message

    raise AssertionError(f"expected SyncError containing: {expected!r}")


# ---------------------------------------------------------------------------
# Failure case 1:
#
# Library/Locations reference a song whose media file is missing.
#
# The planner must fail closed and must not modify either tree.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"
    run_dir = root / "run"

    source.mkdir()
    mount.mkdir()
    run_dir.mkdir()

    location = "F30/MISS.mp3"

    build_device(
        mount,
        [
            (401, location, PAYLOAD_A),
        ],
    )

    (mount / m._location_to_device_rel(location)).unlink()

    write_file(source / "new-C.mp3", PAYLOAD_C)

    source_before = tree_snapshot(source)
    device_before = tree_snapshot(mount)

    expect_sync_error(
        source,
        mount,
        run_dir,
        "iPod database references missing media",
    )

    assert tree_snapshot(source) == source_before
    assert tree_snapshot(mount) == device_before


# ---------------------------------------------------------------------------
# Failure case 2:
#
# Locations.itdb contains path traversal.
#
# Normalization must reject it before source scanning or destination
# allocation can proceed.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"
    run_dir = root / "run"

    source.mkdir()
    mount.mkdir()
    run_dir.mkdir()

    build_device(
        mount,
        [
            (501, "F31/SAFE.mp3", PAYLOAD_A),
        ],
    )

    locations_db = m.live_paths(mount)["Locations.itdb"]

    con = sqlite3.connect(locations_db)
    try:
        con.execute(
            "UPDATE location SET location = ? WHERE item_pid = ?",
            ("../evil.mp3", 501),
        )
        con.commit()
    finally:
        con.close()

    write_file(source / "renamed-A.mp3", PAYLOAD_A)

    source_before = tree_snapshot(source)
    device_before = tree_snapshot(mount)

    expect_sync_error(
        source,
        mount,
        run_dir,
        "unsafe iPod media location",
    )

    assert tree_snapshot(source) == source_before
    assert tree_snapshot(mount) == device_before


# ---------------------------------------------------------------------------
# Failure case 3:
#
# Library.itdb contains a song but Locations.itdb has no corresponding row.
#
# The device content index must refuse to guess where that song lives.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"
    run_dir = root / "run"

    source.mkdir()
    mount.mkdir()
    run_dir.mkdir()

    build_device(
        mount,
        [
            (601, "F32/NOLOC.mp3", PAYLOAD_B),
        ],
    )

    locations_db = m.live_paths(mount)["Locations.itdb"]

    con = sqlite3.connect(locations_db)
    try:
        con.execute(
            "DELETE FROM location WHERE item_pid = ?",
            (601,),
        )
        con.commit()
    finally:
        con.close()

    write_file(source / "new-C.mp3", PAYLOAD_C)

    source_before = tree_snapshot(source)
    device_before = tree_snapshot(mount)

    expect_sync_error(
        source,
        mount,
        run_dir,
        "has no Locations.itdb media row",
    )

    assert tree_snapshot(source) == source_before
    assert tree_snapshot(mount) == device_before


# ---------------------------------------------------------------------------
# Failure case 4:
#
# Two NEW source files have the same filename stem.
#
# Even though their contents differ, assigning identical blank-metadata titles
# would be ambiguous. The planner must refuse rather than guess.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"
    run_dir = root / "run"

    source.mkdir()
    mount.mkdir()
    run_dir.mkdir()

    build_device(mount, [])

    payload_d = b"mock-track-D-content\n"

    write_file(source / "disc1/song.mp3", PAYLOAD_C)
    write_file(source / "disc2/song.mp3", payload_d)

    source_before = tree_snapshot(source)
    device_before = tree_snapshot(mount)

    expect_sync_error(
        source,
        mount,
        run_dir,
        "duplicate NEW filename stems are ambiguous",
    )

    assert tree_snapshot(source) == source_before
    assert tree_snapshot(mount) == device_before


print("mock planner integration tests: PASS")
