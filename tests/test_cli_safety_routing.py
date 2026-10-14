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
    "ipod_sync_cli_safety_test",
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

    raise AssertionError(
        f"expected SyncError containing {expected!r}"
    )


def basic_candidate(source: Path, root: Path):
    src = source / "track.mp3"
    src.write_bytes(b"synthetic-cli-track\n")

    digest = m.sha256_file(src)

    track = m.Track(
        source=src,
        source_rel="track.mp3",
        title="track",
        sha256=digest,
        source_size=src.stat().st_size,
        duration_ms=180000,
        bitrate_kbps=256,
        sample_rate_hz=44100,
        direct_mp3=True,
        folder="F00",
        basename="TEST.mp3",
        device_rel="iTunes_Control/Music/F00/TEST.mp3",
        apple_path=":iTunes_Control:Music:F00:TEST.mp3",
        output_size=src.stat().st_size,
        output_sha256=digest,
    )

    candidate_dir = root / "candidate"
    candidate_dir.mkdir()

    files = {}

    for name in m.REPLACED_DB_NAMES:
        p = candidate_dir / name
        p.write_bytes(
            f"candidate-{name}\n".encode()
        )
        files[name] = p

    return m.Candidate(
        workdir=candidate_dir,
        library=files["Library.itdb"],
        dynamic=files["Dynamic.itdb"],
        locations=files["Locations.itdb"],
        cbk=files["Locations.itdb.cbk"],
        cdb=files["iTunesCDB"],
        tracks=[track],
        mode="generic-incremental-add",
    )


def common_normal_patches(root, source, mount, events, candidate):
    class Guard:
        fstype = "synthetic"
        mountpoint = source

    def require_ifuse_mount(path, writable=None):
        events.append(f"require-mount:{writable}")

    return {
        "RUN_ROOT": root / "runs",
        "ACTIVE_TXN": root / "active.json",
        "require_ifuse_mount": require_ifuse_mount,
        "require_source_ro":
            lambda path: events.append("require-source-ro") or Guard(),
        "assert_no_write_roots_on_source":
            lambda guard, ipod: events.append("source-isolation"),
        "recheck_source_guard":
            lambda guard: events.append("source-recheck"),
        "sqlite_integrity":
            lambda path: "ok",
        "build_candidate":
            lambda s, mnt, run: (
                events.append("build-candidate")
                or candidate
            ),
        "validate_tracks_source":
            lambda tracks, source_root, source_guard=None:
                events.append("validate-source"),
        "validate_candidate":
            lambda c, mnt, run:
                events.append("validate-candidate"),
        "validate_destinations_absent":
            lambda tracks, mnt:
                events.append("validate-destinations"),
        "write_run_manifest":
            lambda run, c, apply:
                events.append(f"manifest:{apply}"),
    }


# ---------------------------------------------------------------------------
# 1. --recover-check routes directly to recover_check.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    mount = root / "device"
    mount.mkdir()

    events = []

    with patched(
        require_ifuse_mount=lambda path, writable=None:
            events.append(f"require-mount:{writable}"),
        recover_check=lambda path:
            events.append("recover-check") or 17,
    ):
        rc = m.main([
            "--mount", str(mount),
            "--recover-check",
        ])

    assert rc == 17
    assert events == [
        "require-mount:False",
        "recover-check",
    ]


# ---------------------------------------------------------------------------
# 2. --recover routes directly to recover_transaction.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    mount = root / "device"
    mount.mkdir()

    events = []

    with patched(
        require_ifuse_mount=lambda path, writable=None:
            events.append(f"require-mount:{writable}"),
        recover_transaction=lambda path:
            events.append("recover") or 23,
    ):
        rc = m.main([
            "--mount", str(mount),
            "--recover",
        ])

    assert rc == 23
    assert events == [
        "require-mount:False",
        "recover",
    ]


# ---------------------------------------------------------------------------
# 3. Recovery flag combinations must fail closed.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    mount = Path(td)

    base = {
        "require_ifuse_mount":
            lambda path, writable=None: None,
    }

    with patched(**base):
        expect_sync_error(
            lambda: m.main([
                "--mount", str(mount),
                "--recover",
                "--recover-check",
            ]),
            "mutually exclusive",
        )

        expect_sync_error(
            lambda: m.main([
                "--mount", str(mount),
                "--recover",
                "--apply",
            ]),
            "--recover and --apply are mutually exclusive",
        )

        expect_sync_error(
            lambda: m.main([
                "--mount", str(mount),
                "--recover-check",
                "--apply",
            ]),
            "--recover-check and --apply are mutually exclusive",
        )


# ---------------------------------------------------------------------------
# 4. Active transaction journal blocks normal sync before source planning.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    mount = root / "device"
    source = root / "source"

    mount.mkdir()
    source.mkdir()

    active = root / "active.json"
    active.write_text(json.dumps({
        "phase": "media-copying",
        "run_dir": "/synthetic/run",
    }))

    events = []

    with patched(
        ACTIVE_TXN=active,
        require_ifuse_mount=lambda path, writable=None:
            events.append("mount-check"),
        require_source_ro=lambda path:
            events.append("BAD-source-access"),
    ):
        expect_sync_error(
            lambda: m.main([
                "--source", str(source),
                "--mount", str(mount),
            ]),
            "incomplete transaction journal exists",
        )

    assert events == ["mount-check"]


# ---------------------------------------------------------------------------
# 5. Dry run validates/plans but must never apply.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"

    source.mkdir()
    mount.mkdir()

    candidate = basic_candidate(source, root)
    events = []

    patches = common_normal_patches(
        root, source, mount, events, candidate
    )

    patches["apply_transaction"] = (
        lambda *args:
        (_ for _ in ()).throw(
            AssertionError(
                "dry run called apply_transaction"
            )
        )
    )

    with patched(**patches):
        rc = m.main([
            "--source", str(source),
            "--mount", str(mount),
        ])

    assert rc == 0

    assert "build-candidate" in events
    assert "validate-source" in events
    assert "validate-candidate" in events
    assert "validate-destinations" in events
    assert "manifest:False" in events

    assert not any(
        event.startswith("remount")
        for event in events
    )


# ---------------------------------------------------------------------------
# 6. No-new-track path exits without apply or candidate post-validation.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"

    source.mkdir()
    mount.mkdir()

    events = []

    class Guard:
        fstype = "synthetic"
        mountpoint = source

    with patched(
        RUN_ROOT=root / "runs",
        ACTIVE_TXN=root / "active.json",
        require_ifuse_mount=lambda path, writable=None:
            events.append("mount-check"),
        require_source_ro=lambda path:
            events.append("source-ro") or Guard(),
        assert_no_write_roots_on_source=lambda g, mnt:
            events.append("source-isolation"),
        sqlite_integrity=lambda path: "ok",
        recheck_source_guard=lambda guard:
            events.append("source-recheck"),
        build_candidate=lambda s, mnt, run:
            events.append("build-none") or None,
        apply_transaction=lambda *args:
            (_ for _ in ()).throw(
                AssertionError(
                    "no-new-track path called apply"
                )
            ),
    ):
        rc = m.main([
            "--source", str(source),
            "--mount", str(mount),
        ])

    assert rc == 0
    assert "build-none" in events


# ---------------------------------------------------------------------------
# 7. --apply is the only normal route into apply_transaction().
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"

    source.mkdir()
    mount.mkdir()

    candidate = basic_candidate(source, root)
    events = []

    patches = common_normal_patches(
        root, source, mount, events, candidate
    )

    apply_calls = []

    def apply_transaction(s, mnt, c, run):
        apply_calls.append((s, mnt, c, run))
        events.append("apply")

    patches["apply_transaction"] = apply_transaction

    with patched(**patches):
        rc = m.main([
            "--source", str(source),
            "--mount", str(mount),
            "--apply",
        ])

    assert rc == 0
    assert len(apply_calls) == 1
    assert events.count("apply") == 1
    assert "manifest:True" in events

    called_source, called_mount, called_candidate, _ = (
        apply_calls[0]
    )

    assert called_source == source.resolve()
    assert called_mount == mount.resolve()
    assert called_candidate is candidate


print("CLI safety routing tests: PASS")
