#!/usr/bin/env python3

from contextlib import contextmanager, redirect_stdout
from pathlib import Path
import importlib.util
import io
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
        "require_stable_file_read":
            lambda path, attempts=3: "synthetic-stable",
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
        require_stable_file_read=lambda path, attempts=3:
            "synthetic-stable",
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



# ---------------------------------------------------------------------------
# 8. --doctor routes before the normal ifuse gate and remains read-only.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "source"
    mount = root / "device"

    source.mkdir()
    mount.mkdir()

    project = root / "project"
    (project / "ipodctl").mkdir(parents=True)

    cdb_py = project / "ipodctl/cdb.py"
    cdb_py.write_text("synthetic\n")

    sync_envelope = root / "sync-envelope"
    sign_cdb = root / "sign-cdb.c"
    rijndael = root / "rijndael.c"

    for path in (sync_envelope, sign_cdb, rijndael):
        path.write_text("synthetic\n")

    active = root / "active.json"
    run_root = root / "runs"

    source_before = sorted(
        str(path.relative_to(source))
        for path in source.rglob("*")
    )
    mount_before = sorted(
        str(path.relative_to(mount))
        for path in mount.rglob("*")
    )

    events = []

    guard = m.SourceGuard(
        source_root=source.resolve(),
        mountpoint=source.resolve(),
        device="//synthetic/music",
        fstype="cifs",
    )

    class ForbiddenEnvelope:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "doctor attempted to enter SyncEnvelope"
            )

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "doctor attempted a write-capable operation"
        )

    with patched(
        PROJECT=project,
        SYNC_ENVELOPE=sync_envelope,
        SIGN_CDB_SRC=sign_cdb,
        RIJNDAEL_SRC=rijndael,
        ACTIVE_TXN=active,
        RUN_ROOT=run_root,
        require_cmd=lambda name: f"/usr/bin/{name}",
        require_source_ro=lambda path:
            events.append("source-ro") or guard,
        assert_no_write_roots_on_source=lambda g, ipod:
            events.append("source-isolation"),
        mount_info=lambda path: (
            "/dev/synthetic",
            str(mount.resolve()),
            "fuse.ifuse",
            {"ro", "nosuid"},
        ),
        verify_device_connection=lambda:
            events.append("device-check") or "synthetic-device",
        find_libgpod_install=lambda:
            (root / "gpod-include", root / "gpod-lib"),
        require_ifuse_mount=forbidden,
        remount_ifuse=forbidden,
        apply_transaction=forbidden,
        recover_check=forbidden,
        recover_transaction=forbidden,
        SyncEnvelope=ForbiddenEnvelope,
    ):
        rc = m.main([
            "--doctor",
            "--source", str(source),
            "--mount", str(mount),
        ])

    assert rc == 0
    assert events == [
        "source-ro",
        "source-isolation",
        "device-check",
    ]

    assert not active.exists()
    assert not run_root.exists()

    source_after = sorted(
        str(path.relative_to(source))
        for path in source.rglob("*")
    )
    mount_after = sorted(
        str(path.relative_to(mount))
        for path in mount.rglob("*")
    )

    assert source_after == source_before
    assert mount_after == mount_before


# ---------------------------------------------------------------------------
# 9. --doctor must reject every write/recovery mode combination.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    with patched(
        doctor=lambda source, mount:
            (_ for _ in ()).throw(
                AssertionError(
                    "conflicting doctor mode reached doctor()"
                )
            ),
    ):
        for flag in ("--apply", "--recover", "--recover-check"):
            expect_sync_error(
                lambda flag=flag: m.main([
                    "--doctor",
                    flag,
                    "--source", str(root),
                    "--mount", str(root),
                ]),
                "--doctor cannot be combined",
            )


# ---------------------------------------------------------------------------
# 10. Doctor reports incomplete readiness without mounting/remounting.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "missing-source"
    mount = root / "missing-device"

    active = root / "active.json"

    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append((args, kwargs))
        raise AssertionError(
            "doctor attempted a mount/remount or transaction operation"
        )

    with patched(
        PROJECT=root / "missing-project",
        SYNC_ENVELOPE=root / "missing-sync-envelope",
        SIGN_CDB_SRC=root / "missing-sign-cdb.c",
        RIJNDAEL_SRC=root / "missing-rijndael.c",
        ACTIVE_TXN=active,
        require_cmd=lambda name:
            (_ for _ in ()).throw(
                m.SyncError(f"required command not found: {name}")
            ),
        mount_info=lambda path: None,
        verify_device_connection=lambda:
            (_ for _ in ()).throw(
                m.SyncError(
                    "expected exactly one connected iOS device; found 0"
                )
            ),
        find_libgpod_install=lambda:
            (_ for _ in ()).throw(
                m.SyncError("patched libgpod missing")
            ),
        require_ifuse_mount=forbidden,
        remount_ifuse=forbidden,
        apply_transaction=forbidden,
        recover_transaction=forbidden,
        SyncEnvelope=lambda *args, **kwargs: forbidden(),
    ):
        rc = m.main([
            "--doctor",
            "--source", str(source),
            "--mount", str(mount),
        ])

    assert rc == 1
    assert forbidden_calls == []



# ---------------------------------------------------------------------------
# 11. --json emits exactly one parseable dry-run plan and never applies.
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

    active = root / "active.json"
    patches["ACTIVE_TXN"] = active

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "JSON plan reached a write-capable operation"
        )

    patches["apply_transaction"] = forbidden
    patches["remount_ifuse"] = forbidden
    patches["recover_transaction"] = forbidden
    patches["SyncEnvelope"] = forbidden

    source_before = {
        str(p.relative_to(source)): p.read_bytes()
        for p in source.rglob("*")
        if p.is_file()
    }

    mount_before = {
        str(p.relative_to(mount)): p.read_bytes()
        for p in mount.rglob("*")
        if p.is_file()
    }

    out = io.StringIO()

    with patched(**patches):
        with redirect_stdout(out):
            rc = m.main([
                "--json",
                "--source", str(source),
                "--mount", str(mount),
            ])

    assert rc == 0

    document = json.loads(out.getvalue())

    assert document["schema_version"] == 1
    assert document["app"] == m.APP
    assert document["version"] == m.VERSION
    assert document["mode"] == candidate.mode
    assert document["source"] == str(source.resolve())
    assert document["mount"] == str(mount.resolve())
    assert document["device_write_authorized"] is False
    assert document["source_writes"] is False
    assert document["device_writes"] is False
    assert document["add_tracks"] == 1
    assert document["media_bytes"] == candidate.tracks[0].source_size
    assert len(document["tracks"]) == 1

    row = document["tracks"][0]

    assert row["source_rel"] == "track.mp3"
    assert row["title"] == "track"
    assert row["source_sha256"] == candidate.tracks[0].sha256
    assert row["output_sha256"] == candidate.tracks[0].output_sha256
    assert row["device_rel"] == candidate.tracks[0].device_rel
    assert row["direct_mp3"] is True

    assert "build-candidate" in events
    assert "validate-source" in events
    assert "validate-candidate" in events
    assert "validate-destinations" in events
    assert "manifest:False" in events

    assert not active.exists()

    source_after = {
        str(p.relative_to(source)): p.read_bytes()
        for p in source.rglob("*")
        if p.is_file()
    }

    mount_after = {
        str(p.relative_to(mount)): p.read_bytes()
        for p in mount.rglob("*")
        if p.is_file()
    }

    assert source_after == source_before
    assert mount_after == mount_before


# ---------------------------------------------------------------------------
# 12. --json no-change planning still emits a valid empty plan.
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

    out = io.StringIO()

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
        require_stable_file_read=lambda path, attempts=3:
            "synthetic-stable",
        recheck_source_guard=lambda guard:
            events.append("source-recheck"),
        build_candidate=lambda s, mnt, run:
            events.append("build-none") or None,
        apply_transaction=lambda *args:
            (_ for _ in ()).throw(
                AssertionError("empty JSON plan called apply")
            ),
        remount_ifuse=lambda *args, **kwargs:
            (_ for _ in ()).throw(
                AssertionError("empty JSON plan remounted device")
            ),
    ):
        with redirect_stdout(out):
            rc = m.main([
                "--json",
                "--source", str(source),
                "--mount", str(mount),
            ])

    assert rc == 0

    document = json.loads(out.getvalue())

    assert document["schema_version"] == 1
    assert document["mode"] == "generic-incremental-add"
    assert document["add_tracks"] == 0
    assert document["media_bytes"] == 0
    assert document["candidate_sha256"] == {}
    assert document["tracks"] == []


# ---------------------------------------------------------------------------
# 13. --json cannot be combined with write/doctor/recovery modes.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    for flag in (
        "--apply",
        "--doctor",
        "--recover",
        "--recover-check",
    ):
        expect_sync_error(
            lambda flag=flag: m.main([
                "--json",
                flag,
                "--source", str(root),
                "--mount", str(root),
            ]),
            "--json is supported only for dry-run planning",
        )


print("CLI safety routing tests: PASS")
