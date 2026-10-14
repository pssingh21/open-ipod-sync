#!/usr/bin/env python3
"""ipod-sync 0.2.0-alpha.5

Experimental ADD-only music synchronization for legacy iPod touch devices.

Safety model
------------
* The music source must be a dedicated filesystem mount that is kernel-mounted
  read-only. The program refuses a writable source mount.
* The iPod is normally mounted read-only. Live device writes require --apply.
* Existing tracks are never deleted, renamed, replaced, or metadata-rewritten.
* MP3 is copied directly. Supported non-MP3 audio is converted to MP3 by ffmpeg
  one track at a time, with no transformed library written back to the source.
* A persistent recovery journal and database/media validation gate every live
  transaction.

Metadata policy for newly added tracks
--------------------------------------
  title        = source filename stem
  artist       = ""
  album_artist = ""
  album        = ""

This alpha intentionally requires an existing song with blank artist, album,
and album_artist metadata to use as a conservative Apple sort-map template.
There is no device-specific fallback PID.

Validated configuration
-----------------------
The generic incremental path has been live-tested on an iPod touch 2nd gen
running iOS 4.2.1. Other legacy devices are experimental and should begin with
read-only `plan` runs.
"""

from __future__ import annotations

import argparse
from collections import Counter
import contextlib
import dataclasses
import hashlib
import json
import os
import shutil
import selectors
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

APP = "ipod-sync"
VERSION = "0.2.0-alpha.5"

HOME = Path.home()
PROJECT = Path("/usr/lib/ipod-sync")
STATE_ROOT = Path(os.environ.get("IPOD_SYNC_STATE_DIR", str(HOME / ".local/share/ipod-sync")))
RUN_ROOT = STATE_ROOT / "stream-sync-runs"
SYNC_STATE = STATE_ROOT / "stream-sync-state.json"
ACTIVE_TXN = STATE_ROOT / "stream-sync-active.json"

DEFAULT_SOURCE = Path(os.environ.get("IPOD_SYNC_SOURCE", "/mnt/music"))
DEFAULT_MOUNT = Path(os.environ.get("IPOD_SYNC_MOUNT", str(HOME / "ipod")))

GPOD_INSTALL = Path("/usr/lib/ipod-sync/vendor/libgpod")
RIJNDAEL_SRC = Path("/usr/lib/ipod-sync/native/rijndael.c")
SYNC_ENVELOPE = Path("/usr/lib/ipod-sync/native/sync-envelope")
SIGN_CDB_SRC = Path("/usr/lib/ipod-sync/native/sign-cdb.c")


SUPPORTED_DIRECT = {".mp3"}
TRANSCODE_EXTS = {
    ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"
}

DB_REL = {
    "Library.itdb": Path("iTunes_Control/iTunes/iTunes Library.itlp/Library.itdb"),
    "Dynamic.itdb": Path("iTunes_Control/iTunes/iTunes Library.itlp/Dynamic.itdb"),
    "Locations.itdb": Path("iTunes_Control/iTunes/iTunes Library.itlp/Locations.itdb"),
    "Locations.itdb.cbk": Path("iTunes_Control/iTunes/iTunes Library.itlp/Locations.itdb.cbk"),
    "iTunesCDB": Path("iTunes_Control/iTunes/iTunesCDB"),
    "Extras.itdb": Path("iTunes_Control/iTunes/iTunes Library.itlp/Extras.itdb"),
    "HashInfo": Path("iTunes_Control/Device/HashInfo"),
}


REPLACED_DB_NAMES = (
    "Library.itdb", "Dynamic.itdb", "Locations.itdb",
    "Locations.itdb.cbk", "iTunesCDB",
)
SNAPSHOT_NAMES = REPLACED_DB_NAMES + ("Extras.itdb", "HashInfo")
IPOD_RESERVE_BYTES = 256 * 1024 * 1024

HASH72_OFF = 0x72
HASH72_LEN = 46


class SyncError(RuntimeError):
    pass


@dataclasses.dataclass
class Track:
    source: Path
    source_rel: str
    title: str
    sha256: str
    source_size: int
    duration_ms: int
    bitrate_kbps: int
    sample_rate_hz: int
    direct_mp3: bool
    dbid_u64: int = 0
    pid: int = 0
    folder: str = ""
    basename: str = ""
    device_rel: str = ""
    apple_path: str = ""
    output_size: int | None = None
    output_sha256: str = ""


@dataclasses.dataclass
class Candidate:
    workdir: Path
    library: Path
    dynamic: Path
    locations: Path
    cbk: Path
    cdb: Path
    tracks: list[Track]
    mode: str


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {
        "text": True,
        "check": check,
        "env": env,
        "cwd": str(cwd) if cwd else None,
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.CalledProcessError as exc:
        output = exc.stdout or ""
        rendered = " ".join(str(x) for x in cmd)
        detail = f"\n{output.rstrip()}" if output.strip() else ""
        raise SyncError(
            f"command failed with exit {exc.returncode}: {rendered}{detail}"
        ) from exc


def require_cmd(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise SyncError(f"required command not found: {name}")
    return p


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def sha256_stream_copy(src: Path, dst: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    with src.open("rb") as fi, dst.open("wb") as fo:
        while True:
            b = fi.read(4 * 1024 * 1024)
            if not b:
                break
            fo.write(b)
            h.update(b)
            total += len(b)
        fo.flush()
        with contextlib.suppress(OSError):
            os.fsync(fo.fileno())
    return h.hexdigest(), total


def read_mounts() -> list[tuple[str, str, str, set[str]]]:
    rows = []
    with open("/proc/mounts", "r", encoding="utf-8") as f:
        for line in f:
            p = line.split()
            if len(p) >= 4:
                rows.append((p[0], p[1], p[2], set(p[3].split(","))))
    return rows


def mount_info(path: Path):
    target = str(path.resolve())
    for row in read_mounts():
        if row[1] == target:
            return row
    return None


@dataclasses.dataclass(frozen=True)
class SourceGuard:
    source_root: Path
    mountpoint: Path
    device: str
    fstype: str


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def require_source_ro(source: Path) -> SourceGuard:
    """Require the source itself to be a dedicated kernel read-only mount."""
    source = source.resolve()
    best = None
    for row in read_mounts():
        _, mp, _, _ = row
        try:
            source.relative_to(Path(mp).resolve())
        except ValueError:
            continue
        if best is None or len(mp) > len(best[1]):
            best = row
    if not best:
        raise SyncError(f"cannot determine source mount: {source}")

    device, mp, fstype, opts = best
    mountpoint = Path(mp).resolve()
    if mountpoint == Path("/"):
        raise SyncError("source must be a dedicated mounted filesystem, not the root filesystem")
    if source != mountpoint:
        raise SyncError(
            "source directory must be the dedicated read-only mountpoint itself; "
            f"source={source} mount={mountpoint}"
        )
    if "ro" not in opts or "rw" in opts:
        raise SyncError(
            "SOURCE WRITE BARRIER FAILED: source mount is not read-only: "
            f"mount={mountpoint} fstype={fstype} options={','.join(sorted(opts))}"
        )
    return SourceGuard(source_root=source, mountpoint=mountpoint, device=device, fstype=fstype)


def assert_no_write_roots_on_source(guard: SourceGuard, ipod_mount: Path):
    """Fail closed if any program write root could land on the source mount."""
    write_roots = {
        "state root": STATE_ROOT,
        "run root": RUN_ROOT,
        "sync state": SYNC_STATE,
        "active transaction journal": ACTIVE_TXN,
        "iPod mount": ipod_mount,
    }
    for label, path in write_roots.items():
        if _path_within(path, guard.mountpoint):
            raise SyncError(
                f"SOURCE WRITE BARRIER FAILED: {label} resolves inside source mount: {path}"
            )


def recheck_source_guard(guard: SourceGuard):
    current = require_source_ro(guard.source_root)
    if (
        current.mountpoint != guard.mountpoint
        or current.device != guard.device
        or current.fstype != guard.fstype
    ):
        raise SyncError("SOURCE WRITE BARRIER FAILED: source mount identity changed during this run")

def require_ifuse_mount(mount: Path, writable: bool | None = None):
    mi = mount_info(mount)
    if not mi:
        raise SyncError(f"iPod mount is not mounted: {mount}")
    _, _, fstype, opts = mi
    if fstype != "fuse.ifuse":
        raise SyncError(f"not an ifuse mount: {mount} ({fstype})")
    if writable is True and "rw" not in opts:
        raise SyncError("iPod mount is not writable")
    if writable is False and "ro" not in opts:
        raise SyncError("iPod mount is not read-only")
    return mi


def remount_ifuse(mount: Path, *, writable: bool):
    require_cmd("fusermount")
    require_cmd("ifuse")
    if mount_info(mount):
        run(["fusermount", "-u", str(mount)])
    mount.mkdir(parents=True, exist_ok=True)
    cmd = ["ifuse", str(mount)]
    if not writable:
        cmd += ["-o", "ro"]
    run(cmd)
    for _ in range(50):
        mi = mount_info(mount)
        if mi:
            opts = mi[3]
            if writable and "rw" in opts:
                return
            if not writable and "ro" in opts:
                return
        time.sleep(0.1)
    raise SyncError(f"failed to remount iPod {'rw' if writable else 'ro'}")


def verify_device_connection() -> str:
    require_cmd("idevice_id")
    require_cmd("idevicepair")
    ids = [x.strip() for x in run(["idevice_id", "-l"]).stdout.splitlines() if x.strip()]
    if len(ids) != 1:
        raise SyncError(f"expected exactly one connected iOS device; found {len(ids)}")
    run(["idevicepair", "validate"])
    return ids[0]


def sqlite_integrity(path: Path) -> str:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


def live_paths(mount: Path) -> dict[str, Path]:
    return {k: mount / rel for k, rel in DB_REL.items()}


def live_hashes(mount: Path) -> dict[str, str]:
    p = live_paths(mount)
    return {k: sha256_file(v) for k, v in p.items() if v.is_file()}


def library_rows(mount: Path) -> tuple[dict[int, dict], dict[int, str]]:
    p = live_paths(mount)
    lib = sqlite3.connect(f"file:{p['Library.itdb']}?mode=ro", uri=True)
    loc = sqlite3.connect(f"file:{p['Locations.itdb']}?mode=ro", uri=True)
    try:
        lib.row_factory = sqlite3.Row
        loc.row_factory = sqlite3.Row
        items: dict[int, dict] = {}
        for r in lib.execute(
            "SELECT pid,title,artist,album,album_artist,is_song,media_kind,sort_title FROM item"
        ):
            d = dict(r)
            if d.get("is_song") in (1, True) or ((d.get("media_kind") or 0) & 1):
                items[int(d["pid"])] = d
        locations = {
            int(r["item_pid"]): r["location"]
            for r in loc.execute("SELECT item_pid,location FROM location")
        }
        return items, locations
    finally:
        lib.close()
        loc.close()


def probe_audio(path: Path) -> tuple[int, int, int]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        p = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate,bit_rate,duration",
                "-show_entries", "format=duration,bit_rate",
                "-of", "json",
                str(path),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        stderr = (p.stderr or "").strip()
        if p.returncode != 0:
            detail = stderr or "ffprobe returned no diagnostic text"
            raise SyncError(
                f"cannot probe audio: {path} (ffprobe exit {p.returncode}): {detail}"
            )
        try:
            obj = json.loads(p.stdout or "")
        except json.JSONDecodeError as exc:
            detail = stderr or "stdout was empty or not valid JSON"
            raise SyncError(
                f"cannot parse ffprobe JSON for {path}: {detail}"
            ) from exc

        streams = obj.get("streams") or []
        stream = streams[0] if streams else {}
        fmt = obj.get("format") or {}
        duration_s = float(stream.get("duration") or fmt.get("duration") or 0)
        sr = int(float(stream.get("sample_rate") or 44100))
        br = int(float(stream.get("bit_rate") or fmt.get("bit_rate") or 128000) / 1000)
        return max(1, int(round(duration_s * 1000))), max(1, br), max(1, sr)

    try:
        from mutagen import File as MutagenFile
    except Exception as exc:
        raise SyncError("ffprobe unavailable and mutagen could not be imported") from exc
    m = MutagenFile(path)
    if not m or not getattr(m, "info", None):
        raise SyncError(f"cannot probe audio: {path}")
    info = m.info
    duration = max(1, int(round(float(getattr(info, "length", 0)) * 1000)))
    sr = int(getattr(info, "sample_rate", 44100) or 44100)
    bitrate = int((getattr(info, "bitrate", 128000) or 128000) / 1000)
    return duration, max(1, bitrate), max(1, sr)

def scan_source(source: Path) -> list[Track]:
    tracks = []
    for p in sorted(x for x in source.rglob("*") if x.is_file()):
        ext = p.suffix.lower()
        if ext not in SUPPORTED_DIRECT and ext not in TRANSCODE_EXTS:
            continue
        rel = p.relative_to(source).as_posix()
        duration, br, sr = probe_audio(p)
        direct = ext == ".mp3"
        tracks.append(Track(
            source=p,
            source_rel=rel,
            title=p.stem,
            sha256=sha256_file(p),
            source_size=p.stat().st_size,
            duration_ms=duration,
            bitrate_kbps=br,
            sample_rate_hz=sr,
            direct_mp3=direct,
        ))
    return tracks


def deterministic_dbid(source_rel: str, digest: str, used: set[int]) -> int:
    salt = 0
    while True:
        b = hashlib.sha256(f"{source_rel}\0{digest}\0{salt}".encode("utf-8")).digest()
        value = int.from_bytes(b[:8], "big") | (1 << 63)
        if value not in used and value != 0:
            return value
        salt += 1


def signed_pid(u64: int) -> int:
    return u64 if u64 < (1 << 63) else u64 - (1 << 64)


def allocate_destinations(
    tracks: list[Track],
    mount: Path,
    used_dbids: set[int],
    used_locations: set[str],
):
    for t in tracks:
        digest = t.sha256 or hashlib.sha256(
            f"{t.source_rel}:{t.source_size}:{t.duration_ms}".encode()
        ).hexdigest()
        t.dbid_u64 = deterministic_dbid(t.source_rel, digest, used_dbids)
        used_dbids.add(t.dbid_u64)
        t.pid = signed_pid(t.dbid_u64)

        seed = hashlib.sha256(f"{t.source_rel}\0{digest}".encode()).digest()
        first_folder = seed[0] % 50
        for n in range(100000):
            folder = f"F{(first_folder + n) % 50:02d}"
            token = hashlib.sha256(seed + n.to_bytes(4, "big")).hexdigest()[:4].upper()
            basename = f"{token}.mp3"
            loc = f"{folder}/{basename}"
            rel = f"iTunes_Control/Music/{loc}"
            if loc not in used_locations and not (mount / rel).exists():
                used_locations.add(loc)
                t.folder = folder
                t.basename = basename
                t.device_rel = rel
                t.apple_path = f":iTunes_Control:Music:{folder}:{basename}"
                break
        else:
            raise SyncError("could not allocate a unique iPod media destination")


def preflight_output_sizes(tracks: list[Track], run_dir: Path):
    # We never retain a transformed library.  For a non-MP3, one temporary
    # file is produced only long enough to freeze its exact output size/hash.
    if all(t.direct_mp3 for t in tracks):
        for t in tracks:
            t.output_size = t.source_size
            t.output_sha256 = t.sha256
        return

    ffmpeg = require_cmd("ffmpeg")
    temp_dir = run_dir / "single-track-size-probe"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        for t in tracks:
            if t.direct_mp3:
                t.output_size = t.source_size
                t.output_sha256 = t.sha256
                continue
            dst = temp_dir / "probe.mp3"
            dst.unlink(missing_ok=True)
            run([
                ffmpeg,
                "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(t.source),
                "-map", "0:a:0", "-vn", "-map_metadata", "-1",
                "-codec:a", "libmp3lame", "-b:a", "256k",
                str(dst),
            ])
            t.output_size = dst.stat().st_size
            t.output_sha256 = sha256_file(dst)
            dst.unlink()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def choose_template_pid(library: Path) -> int:
    """Select a live blank-metadata song as the conservative sort-map template."""
    con = sqlite3.connect(f"file:{library}?mode=ro", uri=True)
    try:
        row = con.execute(
            """
            SELECT pid
            FROM item
            WHERE is_song=1
              AND COALESCE(artist,'')=''
              AND COALESCE(album,'')=''
              AND COALESCE(album_artist,'')=''
            ORDER BY pid
            LIMIT 1
            """
        ).fetchone()
        if not row:
            raise SyncError(
                "no blank-metadata template track exists; this alpha refuses to invent "
                "Apple sort-map state"
            )
        return int(row[0])
    finally:
        con.close()

def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def row_dict(con: sqlite3.Connection, table: str, where: str, args=()) -> dict:
    con.row_factory = sqlite3.Row
    r = con.execute(f'SELECT * FROM "{table}" WHERE {where}', args).fetchone()
    if r is None:
        raise SyncError(f"row not found: {table} WHERE {where} {args}")
    return dict(r)


def insert_dict(con: sqlite3.Connection, table: str, row: dict):
    cols = table_columns(con, table)
    qcols = ",".join(f'"{c}"' for c in cols)
    qs = ",".join("?" for _ in cols)
    con.execute(
        f'INSERT INTO "{table}" ({qcols}) VALUES ({qs})',
        [row.get(c) for c in cols],
    )


def copy_database_only_mount(mount: Path, dst: Path):
    (dst / "iTunes_Control").mkdir(parents=True, exist_ok=True)
    src_ctrl = mount / "iTunes_Control"
    shutil.copytree(src_ctrl / "Device", dst / "iTunes_Control/Device", dirs_exist_ok=True)
    shutil.copytree(src_ctrl / "iTunes", dst / "iTunes_Control/iTunes", dirs_exist_ok=True)
    for i in range(50):
        (dst / f"iTunes_Control/Music/F{i:02d}").mkdir(parents=True, exist_ok=True)


def c_literal(s: str) -> str:
    out = ['"']
    for b in s.encode("utf-8"):
        if 32 <= b < 127 and b not in (34, 92):
            out.append(chr(b))
        elif b == 34:
            out.append(r'\"')
        elif b == 92:
            out.append(r'\\')
        else:
            out.append(f"\\{b:03o}")
    out.append('"')
    return "".join(out)


def find_libgpod_install() -> tuple[Path, Path]:
    inc = GPOD_INSTALL / "include/gpod-1.0"
    libdir = GPOD_INSTALL / "lib"
    if not (inc / "gpod/itdb.h").is_file():
        raise SyncError(f"patched libgpod headers missing under {GPOD_INSTALL}")
    if not list(libdir.glob("libgpod.so*")):
        raise SyncError(f"patched libgpod library missing under {GPOD_INSTALL}")
    return inc, libdir


def build_libgpod_donor(
    mount: Path,
    tracks: list[Track],
    work: Path,
    template_pid: int,
) -> Path:
    donor_mount = work / "libgpod-donor"
    copy_database_only_mount(mount, donor_mount)

    template_dbid = template_pid & ((1 << 64) - 1)
    rows = []
    for t in tracks:
        rows.append(
            "    {UINT64_C(%d), %s, %s, %d, %d, %d, %d}," % (
                t.dbid_u64,
                c_literal(t.apple_path),
                c_literal(t.title),
                int(t.output_size or t.source_size),
                t.duration_ms,
                t.bitrate_kbps,
                t.sample_rate_hz,
            )
        )

    csrc = f'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <gpod/itdb.h>

struct Add {{
    uint64_t dbid;
    const char *path;
    const char *title;
    guint32 size;
    guint32 tracklen;
    guint32 bitrate;
    guint32 samplerate;
}};

static struct Add ADDS[] = {{
{os.linesep.join(rows)}
}};

int main(int argc, char **argv) {{
    if (argc != 3) {{
        fprintf(stderr, "usage: %s <mountpoint> <output-cdb>\\n", argv[0]);
        return 2;
    }}
    GError *err = NULL;
    Itdb_iTunesDB *db = itdb_parse(argv[1], &err);
    if (!db) {{
        fprintf(stderr, "parse failed: %s\\n", err ? err->message : "unknown");
        return 1;
    }}

    Itdb_Track *source = NULL;
    for (GList *p = db->tracks; p; p = p->next) {{
        Itdb_Track *t = p->data;
        if ((uint64_t)t->dbid == UINT64_C({template_dbid})) {{
            source = t;
            break;
        }}
    }}
    if (!source) {{
        fprintf(stderr, "blank template DBID not found\\n");
        itdb_free(db);
        return 1;
    }}

    Itdb_Playlist *mpl = itdb_playlist_mpl(db);
    if (!mpl) {{
        fprintf(stderr, "master playlist missing\\n");
        itdb_free(db);
        return 1;
    }}

    size_t count = sizeof(ADDS)/sizeof(ADDS[0]);
    for (size_t i = 0; i < count; i++) {{
        struct Add *a = &ADDS[i];
        for (GList *p = db->tracks; p; p = p->next) {{
            Itdb_Track *x = p->data;
            if ((uint64_t)x->dbid == a->dbid) {{
                fprintf(stderr, "new DBID collision\\n");
                itdb_free(db);
                return 1;
            }}
            if (x->ipod_path && strcmp(x->ipod_path, a->path) == 0) {{
                fprintf(stderr, "new path collision\\n");
                itdb_free(db);
                return 1;
            }}
        }}

        Itdb_Track *dup = itdb_track_duplicate(source);
        if (!dup) {{
            fprintf(stderr, "track duplicate failed\\n");
            itdb_free(db);
            return 1;
        }}
        dup->id = 0;
        dup->dbid = a->dbid;
        dup->dbid2 = a->dbid;

        g_free(dup->ipod_path);
        dup->ipod_path = g_strdup(a->path);
        g_free(dup->title);
        dup->title = g_strdup(a->title);
        g_free(dup->artist);
        dup->artist = g_strdup("");
        g_free(dup->album);
        dup->album = g_strdup("");
        g_free(dup->albumartist);
        dup->albumartist = g_strdup("");

        dup->size = a->size;
        dup->tracklen = a->tracklen;
        dup->bitrate = a->bitrate;
        dup->samplerate = a->samplerate;
        itdb_track_remove_thumbnails(dup);
        itdb_track_add(db, dup, -1);
        itdb_playlist_add_track(mpl, dup, -1);
    }}

    if (!itdb_write_file(db, argv[2], &err)) {{
        fprintf(stderr, "write failed: %s\\n", err ? err->message : "unknown");
        if (err) g_error_free(err);
        itdb_free(db);
        return 1;
    }}
    printf("added=%zu total=%u\\n", count, g_list_length(db->tracks));
    itdb_free(db);
    return 0;
}}
'''

    src = work / "libgpod-add.c"
    exe = work / "libgpod-add"
    src.write_text(csrc)
    inc, libdir = find_libgpod_install()
    glib = run(["pkg-config", "--cflags", "--libs", "glib-2.0"]).stdout.split()
    run([
        "gcc", "-O2", "-Wall", "-Wextra",
        f"-I{inc}",
        str(src),
        f"-L{libdir}",
        f"-Wl,-rpath,{libdir}",
        "-lgpod",
        *glib,
        "-o", str(exe),
    ])

    output = donor_mount / "iTunes_Control/iTunes/iTunesCDB"
    run([str(exe), str(donor_mount), str(output)])
    if not output.is_file():
        raise SyncError("libgpod did not create donor iTunesCDB")
    return donor_mount


def locate_donor_sqlite(donor_mount: Path, name: str) -> Path:
    root = donor_mount / "iTunes_Control/iTunes"
    canonical = root / "iTunes Library.itlp" / name
    if canonical.is_file():
        return canonical

    hits = []
    for path in root.rglob(name):
        rel_parts = path.relative_to(root).parts
        if "DBTemp" in rel_parts or "Backup" in rel_parts:
            continue
        hits.append(path)
    if len(hits) != 1:
        raise SyncError(f"expected one canonical donor {name}, found {hits}")
    return hits[0]

def make_surgical_sqlite(
    mount: Path,
    donor_mount: Path,
    tracks: list[Track],
    work: Path,
    template_pid: int,
) -> tuple[Path, Path, Path]:
    lp = live_paths(mount)
    out_lib = work / "Library.itdb"
    out_dyn = work / "Dynamic.itdb"
    out_loc = work / "Locations.itdb"
    shutil.copy2(lp["Library.itdb"], out_lib)
    shutil.copy2(lp["Dynamic.itdb"], out_dyn)
    shutil.copy2(lp["Locations.itdb"], out_loc)

    donor_lib_p = locate_donor_sqlite(donor_mount, "Library.itdb")
    donor_loc_p = locate_donor_sqlite(donor_mount, "Locations.itdb")

    live = sqlite3.connect(out_lib)
    donor = sqlite3.connect(f"file:{donor_lib_p}?mode=ro", uri=True)
    dyn = sqlite3.connect(out_dyn)
    loc = sqlite3.connect(out_loc)
    donor_loc = sqlite3.connect(f"file:{donor_loc_p}?mode=ro", uri=True)
    try:
        live.row_factory = sqlite3.Row
        donor.row_factory = sqlite3.Row
        donor_loc.row_factory = sqlite3.Row
        template_item = row_dict(live, "item", "pid=?", (template_pid,))
        template_av = row_dict(live, "avformat_info", "item_pid=?", (template_pid,))

        live.execute("BEGIN IMMEDIATE")
        dyn.execute("BEGIN IMMEDIATE")
        loc.execute("BEGIN IMMEDIATE")

        for t in tracks:
            item = dict(template_item)
            item["pid"] = t.pid
            item["title"] = t.title
            if "artist" in item:
                item["artist"] = ""
            if "album" in item:
                item["album"] = ""
            if "album_artist" in item:
                item["album_artist"] = ""
            if "title_blank" in item:
                item["title_blank"] = 0
            if "artist_blank" in item:
                item["artist_blank"] = 1
            if "album_blank" in item:
                item["album_blank"] = 1
            if "album_artist_blank" in item:
                item["album_artist_blank"] = 1
            if "total_time_ms" in item:
                item["total_time_ms"] = float(t.duration_ms)
            if "duration" in item:
                item["duration"] = float(t.duration_ms)
            # Keep the proven blank template's sort key so Apple sort_map is
            # not expanded with guessed data.
            if "sort_title" in item:
                item["sort_title"] = template_item.get("sort_title") or template_item.get("title")
            insert_dict(live, "item", item)

            donor_av = row_dict(donor, "avformat_info", "item_pid=?", (t.pid,))
            av = dict(template_av)
            for key, value in donor_av.items():
                if key in av:
                    av[key] = value
            av["item_pid"] = t.pid
            if "channels" in av:
                av["channels"] = 0
            insert_dict(live, "avformat_info", av)

            for table in ("item_to_container", "item_to_container_orig"):
                insert_dict(live, table, row_dict(donor, table, "item_pid=?", (t.pid,)))

            dcols = table_columns(dyn, "item_stats")
            drow = {c: 0 for c in dcols}
            drow["item_pid"] = t.pid
            insert_dict(dyn, "item_stats", drow)

            insert_dict(
                loc,
                "location",
                row_dict(donor_loc, "location", "item_pid=?", (t.pid,)),
            )

        live.commit()
        dyn.commit()
        loc.commit()
    except Exception:
        with contextlib.suppress(Exception):
            live.rollback()
        with contextlib.suppress(Exception):
            dyn.rollback()
        with contextlib.suppress(Exception):
            loc.rollback()
        raise
    finally:
        live.close()
        donor.close()
        dyn.close()
        loc.close()
        donor_loc.close()

    for p in (out_lib, out_dyn, out_loc):
        if sqlite_integrity(p) != "ok":
            raise SyncError(f"candidate integrity failed: {p.name}")
    return out_lib, out_dyn, out_loc


CBK_HELPER_C = r'''#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "rijndael.h"
static const uint8_t AES_KEY[16]={
0x61,0x8c,0xa1,0x0d,0xc7,0xf5,0x7f,0xd3,0xb4,0x72,0x3e,0x08,0x15,0x74,0x63,0xd7};
static int h2b(const char*h,uint8_t*o,size_t n){if(strlen(h)!=n*2)return 0;for(size_t i=0;i<n;i++){unsigned int v;if(sscanf(h+i*2,"%2x",&v)!=1)return 0;o[i]=(uint8_t)v;}return 1;}
static void ph(const uint8_t*p,size_t n){for(size_t i=0;i<n;i++)printf("%02x",p[i]);putchar('\n');}
static void gen(uint8_t s[46],const uint8_t sh[20],const uint8_t iv[16],const uint8_t r[12]){uint8_t p[32]={0},o[32]={0};memcpy(p,sh,20);memcpy(p+20,r,12);s[0]=1;s[1]=0;memcpy(s+2,r,12);aes_set_key((uint8_t*)AES_KEY);aes_encrypt((uint8_t*)iv,p,o,32);memcpy(s+14,o,32);}
static int ext(const uint8_t s[46],const uint8_t sh[20],uint8_t iv[16],uint8_t r[12]){uint8_t p[32]={0},o[32]={0};if(s[0]!=1||s[1]!=0)return-1;memcpy(p,sh,20);memcpy(p+20,s+2,12);memcpy(o,p,32);aes_set_key((uint8_t*)AES_KEY);aes_decrypt(p,(uint8_t*)s+14,o,16);if(memcmp(p+16,o+16,16))return-1;memcpy(iv,o,16);memcpy(r,s+2,12);return 0;}
int main(int ac,char**av){if(ac==4&&!strcmp(av[1],"extract")){uint8_t sh[20],s[46],iv[16],r[12];if(!h2b(av[2],sh,20)||!h2b(av[3],s,46)||ext(s,sh,iv,r))return 2;printf("IV=");ph(iv,16);printf("RND=");ph(r,12);return 0;}if(ac==5&&!strcmp(av[1],"sign")){uint8_t sh[20],iv[16],r[12],s[46];if(!h2b(av[2],sh,20)||!h2b(av[3],iv,16)||!h2b(av[4],r,12))return 2;gen(s,sh,iv,r);printf("SIG=");ph(s,46);return 0;}return 1;}
'''


def compile_cbk_helper(work: Path) -> Path:
    src = work / "cbk-helper.c"
    exe = work / "cbk-helper"
    src.write_text(CBK_HELPER_C)
    flags = run(["pkg-config", "--cflags", "--libs", "glib-2.0"]).stdout.split()
    run([
        "gcc", "-O2", "-Wall", "-Wextra", f"-I{RIJNDAEL_SRC.parent}",
        str(src), str(RIJNDAEL_SRC), *flags, "-o", str(exe),
    ])
    return exe


def helper_kv(exe: Path, args: list[str]) -> dict[str, str]:
    p = run([str(exe), *args])
    result = {}
    for line in p.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def cbk_material(path: Path):
    data = path.read_bytes()
    blocks = len(data) // 1024
    hashes = b"".join(
        hashlib.sha1(data[i * 1024:(i + 1) * 1024]).digest()
        for i in range(blocks)
    )
    if not hashes:
        raise SyncError("Locations.itdb too small for CBK")
    return blocks, len(data) % 1024, hashes, hashlib.sha1(hashes).digest()


def build_cbk(
    live_locations: Path,
    live_cbk: Path,
    candidate_locations: Path,
    output: Path,
    helper: Path,
):
    lb, _, lh, lf = cbk_material(live_locations)
    raw = live_cbk.read_bytes()
    if len(raw) != 66 + 20 * lb or raw[66:] != lh or raw[46:66] != lf:
        raise SyncError("live Locations.itdb.cbk does not match live Locations.itdb")
    sig = raw[:46]
    state = helper_kv(helper, ["extract", lf.hex(), sig.hex()])
    iv = bytes.fromhex(state["IV"])
    rnd = bytes.fromhex(state["RND"])
    regen = bytes.fromhex(helper_kv(helper, ["sign", lf.hex(), iv.hex(), rnd.hex()])["SIG"])
    if regen != sig:
        raise SyncError("live CBK signature calibration failed")

    cb, _, ch, cf = cbk_material(candidate_locations)
    csig = bytes.fromhex(helper_kv(helper, ["sign", cf.hex(), iv.hex(), rnd.hex()])["SIG"])
    output.write_bytes(csig + cf + ch)
    if len(output.read_bytes()) != 66 + 20 * cb:
        raise SyncError("candidate CBK length mismatch")


def compile_current_cdb_signer(work: Path) -> Path:
    if not SIGN_CDB_SRC.is_file():
        raise SyncError(f"missing CDB signer source: {SIGN_CDB_SRC}")
    text = SIGN_CDB_SRC.read_text()
    for forbidden in ("EXPECT_" + "RND", "EXPECT_" + "IV", "EXPECT_" + "PRISTINE_SIG"):
        if forbidden in text:
            raise SyncError(f"public CDB signer contains forbidden device calibration: {forbidden}")
    for required in (
        "pristine calibration failed",
        "inverse Hash72 verification failed",
        "bytes outside Hash72 changed",
        "compressed body changed",
        "final signature",
    ):
        if required not in text:
            raise SyncError(f"CDB signer lost required safety check: {required}")

    src = work / "sign-cdb-current.c"
    exe = work / "sign-cdb-current"
    src.write_text(text)
    flags = run(["pkg-config", "--cflags", "--libs", "glib-2.0"]).stdout.split()
    run([
        "gcc", "-O2", "-Wall", "-Wextra", f"-I{RIJNDAEL_SRC.parent}",
        str(src), str(RIJNDAEL_SRC), *flags, "-o", str(exe),
    ])
    return exe

def import_cdb_module():
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    try:
        from ipodctl.cdb import inflate_container, build_unsigned_container
    except Exception as exc:
        raise SyncError("cannot import ipodctl.cdb") from exc
    return inflate_container, build_unsigned_container


def build_generic_candidate(mount: Path, tracks: list[Track], run_dir: Path) -> Candidate:
    work = run_dir / "candidate"
    work.mkdir(parents=True, exist_ok=False)
    lp = live_paths(mount)

    template_pid = choose_template_pid(lp["Library.itdb"])
    donor_mount = build_libgpod_donor(mount, tracks, work, template_pid)
    lib, dyn, loc = make_surgical_sqlite(
        mount, donor_mount, tracks, work, template_pid
    )

    cbk_helper = compile_cbk_helper(work)
    cbk = work / "Locations.itdb.cbk"
    build_cbk(lp["Locations.itdb"], lp["Locations.itdb.cbk"], loc, cbk, cbk_helper)

    inflate_container, build_unsigned_container = import_cdb_module()
    donor_cdb = donor_mount / "iTunes_Control/iTunes/iTunesCDB"
    donor_body = inflate_container(donor_cdb.read_bytes())
    unsigned = build_unsigned_container(lp["iTunesCDB"].read_bytes(), donor_body)
    unsigned_path = work / "iTunesCDB.unsigned"
    unsigned_path.write_bytes(unsigned)

    signer = compile_current_cdb_signer(work)
    signed = work / "iTunesCDB.signed"
    run([
        str(signer),
        str(lp["iTunesCDB"]),
        str(lp["HashInfo"]),
        str(unsigned_path),
        str(signed),
    ])
    if inflate_container(signed.read_bytes()) != donor_body:
        raise SyncError("signed CDB body differs from donor body")

    new_pids = {t.pid for t in tracks}
    con = sqlite3.connect(f"file:{lib}?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" for _ in new_pids)
        got = {
            int(r[0]) for r in con.execute(
                f"SELECT pid FROM item WHERE pid IN ({placeholders})",
                tuple(new_pids),
            )
        }
        if got != new_pids:
            raise SyncError("generic candidate is missing new Library rows")
    finally:
        con.close()

    return Candidate(
        workdir=work,
        library=lib,
        dynamic=dyn,
        locations=loc,
        cbk=cbk,
        cdb=signed,
        tracks=tracks,
        mode="generic-incremental-add",
    )


def _location_to_music_rel(location: str) -> str:
    """Normalize known Locations.itdb forms to Fxx/basename.

    Legacy iPod SQLite databases are not fully uniform here.  On the same
    device we can encounter compact rows such as ``F06/SCLD.mp3`` as well as
    full Apple-style paths such as ``:iTunes_Control:Music:F06:SCLD.mp3``.
    Normalize both forms before readback and collision checks.
    """
    raw = str(location or "").strip()
    if not raw:
        raise SyncError("song row has an empty media location")

    if raw.startswith(":") or (":" in raw and "/" not in raw and "\\" not in raw):
        parts = [p for p in raw.split(":") if p]
    else:
        parts = [p for p in raw.replace("\\", "/").lstrip("/").split("/") if p]

    if any(p in {".", ".."} for p in parts):
        raise SyncError(f"unsafe iPod media location: {location!r}")

    # Accepted database encodings, all normalized to Fxx/basename.
    if len(parts) >= 4 and parts[0] == "iTunes_Control" and parts[1] == "Music":
        parts = parts[2:]
    elif len(parts) >= 3 and parts[0] == "Music":
        parts = parts[1:]

    if len(parts) != 2:
        raise SyncError(f"unexpected iPod media location: {location!r}")
    folder, basename = parts
    if len(folder) != 3 or folder[0] != "F" or not folder[1:].isdigit():
        raise SyncError(f"unexpected iPod media folder: {location!r}")
    if not basename or "/" in basename or "\\" in basename or basename in {".", ".."}:
        raise SyncError(f"unsafe iPod media basename: {location!r}")
    return f"{folder}/{basename}"


def _location_to_device_rel(location: str) -> str:
    return f"iTunes_Control/Music/{_location_to_music_rel(location)}"


def _device_media_hash_counts(
    mount: Path,
    items: dict[int, dict],
    locs: dict[int, str],
) -> Counter:
    """Build a read-only content index for every song referenced by the DB."""
    counts: Counter = Counter()
    cache: dict[str, str] = {}
    music_root = (mount / "iTunes_Control/Music").resolve()
    pids = sorted(items)
    total = len(pids)

    for n, pid in enumerate(pids, 1):
        location = locs.get(pid)
        if not location:
            raise SyncError(f"song PID {pid} has no Locations.itdb media row")
        rel = _location_to_device_rel(location)
        path = mount / rel
        if not path.is_file():
            raise SyncError(f"iPod database references missing media: {rel}")
        try:
            path.resolve().relative_to(music_root)
        except ValueError as exc:
            raise SyncError(f"iPod media escaped Music root: {rel}") from exc

        h = cache.get(rel)
        if h is None:
            h = sha256_file(path)
            cache[rel] = h
        counts[h] += 1

        if n % 100 == 0 or n == total:
            print(f"device content index: {n}/{total}")

    return counts


def plan_generic(source: Path, mount: Path, run_dir: Path) -> list[Track]:
    items, locs = library_rows(mount)
    used_locations = {_location_to_music_rel(x) for x in locs.values() if x}
    used_dbids = {pid & ((1 << 64) - 1) for pid in items}

    scanned = scan_source(source)
    if not scanned:
        return []

    # Freeze the exact bytes that would be written. Direct MP3 files simply
    # reuse their source hash; transformations, when used, are probed one at a
    # time on VM-local storage and never modify the source filesystem.
    preflight_output_sizes(scanned, run_dir)

    # Content matching deliberately replaces title matching.  Multiplicity is
    # retained, so two identical source files require two matching device song
    # entries before both are considered already present.
    device_counts = _device_media_hash_counts(mount, items, locs)
    consumed: Counter = Counter()
    adds: list[Track] = []
    matched = 0
    for t in scanned:
        h = t.output_sha256
        if not h:
            raise SyncError(f"planned output hash missing: {t.source_rel}")
        if consumed[h] < device_counts[h]:
            consumed[h] += 1
            matched += 1
        else:
            adds.append(t)

    print(f"content-matched existing source tracks: {matched}/{len(scanned)}")
    print(f"new source tracks by content:          {len(adds)}")
    if adds:
        for t in adds[:20]:
            print(f"  ADD source: {t.source_rel}")
        if len(adds) > 20:
            print(f"  ... and {len(adds) - 20} more")

    title_counts: dict[str, int] = {}
    for t in adds:
        title_counts[t.title] = title_counts.get(t.title, 0) + 1
    duplicates = sorted(k for k, n in title_counts.items() if n > 1)
    if duplicates:
        raise SyncError(
            "duplicate NEW filename stems are ambiguous; refusing to guess: "
            + ", ".join(duplicates[:20])
        )

    if not adds:
        return []
    allocate_destinations(adds, mount, used_dbids, used_locations)
    return adds

def validate_tracks_source(
    tracks: list[Track], source_root: Path, source_guard: SourceGuard | None = None
):
    root = source_root.resolve()
    if source_guard is not None:
        recheck_source_guard(source_guard)
    for t in tracks:
        if not t.source.is_file():
            raise SyncError(f"source disappeared: {t.source}")
        resolved_source = t.source.resolve()
        try:
            resolved_source.relative_to(root)
        except ValueError:
            raise SyncError(f"source escaped configured root: {t.source}")
        if source_guard is not None and not _path_within(resolved_source, source_guard.mountpoint):
            raise SyncError(f"source escaped read-only source mount: {t.source}")
        if t.source.stat().st_size != t.source_size:
            raise SyncError(f"source size changed: {t.source}")
        actual = sha256_file(t.source)
        if t.sha256 and actual != t.sha256:
            raise SyncError(f"source SHA256 changed: {t.source}")
        t.sha256 = actual
        if t.direct_mp3:
            t.output_size = t.source_size
            t.output_sha256 = actual


def candidate_hashes(c: Candidate) -> dict[str, str]:
    return {
        "Library.itdb": sha256_file(c.library),
        "Dynamic.itdb": sha256_file(c.dynamic),
        "Locations.itdb": sha256_file(c.locations),
        "Locations.itdb.cbk": sha256_file(c.cbk),
        "iTunesCDB": sha256_file(c.cdb),
    }


def sqlite_schema_signature(path: Path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
    finally:
        con.close()


def table_multiset(path: Path, table: str) -> Counter:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return Counter(tuple(r) for r in con.execute(f'SELECT * FROM "{table}"'))
    finally:
        con.close()


def user_tables(path: Path) -> list[str]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
    finally:
        con.close()


def compare_add_only_sqlite(
    live: Path,
    candidate: Path,
    changed_tables: set[str],
    expected_adds: int,
    label: str,
):
    if sqlite_schema_signature(live) != sqlite_schema_signature(candidate):
        raise SyncError(f"{label} candidate schema differs from live")
    live_tables = user_tables(live)
    if live_tables != user_tables(candidate):
        raise SyncError(f"{label} candidate table set differs from live")

    unexpected = []
    for table in live_tables:
        before = table_multiset(live, table)
        after = table_multiset(candidate, table)
        if table in changed_tables:
            removed = before - after
            added = after - before
            if removed:
                raise SyncError(f"{label}.{table}: existing rows changed/removed")
            if sum(added.values()) != expected_adds:
                raise SyncError(
                    f"{label}.{table}: expected +{expected_adds} rows, "
                    f"got +{sum(added.values())}"
                )
        elif before != after:
            unexpected.append(table)
    if unexpected:
        raise SyncError(f"{label}: unexpected changed tables: {unexpected}")


def sqlite_semantically_equal(a: Path, b: Path) -> bool:
    if sqlite_schema_signature(a) != sqlite_schema_signature(b):
        return False
    ta = user_tables(a)
    if ta != user_tables(b):
        return False
    return all(table_multiset(a, t) == table_multiset(b, t) for t in ta)


def cp_record_sequence(path: Path) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in con.execute(
            'PRAGMA table_info("_SqliteDatabaseProperties")'
        )]
        if "key" not in cols or "value" not in cols:
            raise SyncError(f"{path.name}: _SqliteDatabaseProperties lacks key/value columns")
        rows = con.execute(
            'SELECT value FROM "_SqliteDatabaseProperties" WHERE key=?',
            ("__CPRecordSequenceNumber",),
        ).fetchall()
        if len(rows) != 1:
            raise SyncError(f"{path.name}: expected one __CPRecordSequenceNumber row, got {len(rows)}")
        return int(rows[0][0])
    finally:
        con.close()


def library_equal_except_cp_sequence(reference: Path, live: Path) -> dict[str, int]:
    if sqlite_integrity(reference) != "ok" or sqlite_integrity(live) != "ok":
        raise SyncError("Library integrity failed while checking CP sequence drift")
    if sqlite_schema_signature(reference) != sqlite_schema_signature(live):
        raise SyncError("Library schema changed; CP-sequence-only drift not proven")
    rt = user_tables(reference)
    if rt != user_tables(live):
        raise SyncError("Library table set changed; CP-sequence-only drift not proven")
    props = "_SqliteDatabaseProperties"
    if props not in rt:
        raise SyncError("Library has no _SqliteDatabaseProperties table")
    for table in rt:
        if table == props:
            continue
        if table_multiset(reference, table) != table_multiset(live, table):
            raise SyncError(f"Library changed outside CP sequence: table={table}")
    def non_cp_rows(path: Path) -> Counter:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return Counter(tuple(r) for r in con.execute(
                'SELECT * FROM "_SqliteDatabaseProperties" WHERE key<>? OR key IS NULL',
                ("__CPRecordSequenceNumber",),
            ))
        finally:
            con.close()
    if non_cp_rows(reference) != non_cp_rows(live):
        raise SyncError("Library database properties changed beyond __CPRecordSequenceNumber")
    before = cp_record_sequence(reference)
    after = cp_record_sequence(live)
    if after < before:
        raise SyncError(f"Library CP sequence moved backwards: {before} -> {after}")
    return {"reference": before, "live": after}


def validate_expected_new_rows(c: Candidate, mount: Path):
    pids = {t.pid for t in c.tracks}
    if len(pids) != len(c.tracks):
        raise SyncError("candidate contains duplicate SQLite PIDs")
    if len({t.dbid_u64 for t in c.tracks}) != len(c.tracks):
        raise SyncError("candidate contains duplicate persistent DBIDs")
    if len({t.device_rel for t in c.tracks}) != len(c.tracks):
        raise SyncError("candidate contains duplicate device destinations")

    live = live_paths(mount)
    n = len(c.tracks)
    compare_add_only_sqlite(
        live["Library.itdb"], c.library,
        {"avformat_info", "ext_item_view_membership", "item", "item_to_container", "item_to_container_orig"},
        n, "Library.itdb",
    )
    compare_add_only_sqlite(
        live["Dynamic.itdb"], c.dynamic, {"item_stats"}, n, "Dynamic.itdb"
    )
    compare_add_only_sqlite(
        live["Locations.itdb"], c.locations, {"location"}, n, "Locations.itdb"
    )

    lib = sqlite3.connect(f"file:{c.library}?mode=ro", uri=True)
    dyn = sqlite3.connect(f"file:{c.dynamic}?mode=ro", uri=True)
    loc = sqlite3.connect(f"file:{c.locations}?mode=ro", uri=True)
    try:
        for t in c.tracks:
            row = lib.execute(
                "SELECT title,COALESCE(artist,''),COALESCE(album,''),COALESCE(album_artist,'') "
                "FROM item WHERE pid=?", (t.pid,)
            ).fetchone()
            if row is None or tuple(row) != (t.title, "", "", ""):
                raise SyncError(f"candidate Library metadata mismatch: {t.title}")
            for table, col in (
                ("avformat_info", "item_pid"),
                ("ext_item_view_membership", "item_pid"),
                ("item_to_container", "item_pid"),
                ("item_to_container_orig", "item_pid"),
            ):
                count = lib.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{col}"=?', (t.pid,)
                ).fetchone()[0]
                if count != 1:
                    raise SyncError(f"candidate {table} PID cardinality != 1 for {t.title}")
            if dyn.execute("SELECT COUNT(*) FROM item_stats WHERE item_pid=?", (t.pid,)).fetchone()[0] != 1:
                raise SyncError(f"candidate Dynamic row missing: {t.title}")
            lr = loc.execute("SELECT location,file_size FROM location WHERE item_pid=?", (t.pid,)).fetchone()
            expected_loc = f"{t.folder}/{t.basename}"
            if lr is None or lr[0] != expected_loc or int(lr[1]) != int(t.output_size or t.source_size):
                raise SyncError(f"candidate Locations row mismatch: {t.title}")
    finally:
        lib.close(); dyn.close(); loc.close()


CDB_AUDIT_C = r'''
#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>
#include <gpod/itdb.h>

static void hexs(const char *s){
    if(!s) return;
    const unsigned char *p=(const unsigned char*)s;
    while(*p){printf("%02x",*p);p++;}
}

int main(int argc,char **argv){
    if(argc!=2){
        fprintf(stderr,"usage: %s <ipod-style-mount-root>\n",argv[0]);
        return 2;
    }

    GError *err=NULL;

    /*
     * iTunesCDB is compressed.  The proven libgpod path is itdb_parse()
     * against an iPod-style mount tree.  Direct itdb_parse_file() on the
     * CDB is not equivalent on this device.
     */
    Itdb_iTunesDB *db=itdb_parse(argv[1],&err);
    if(!db){
        fprintf(stderr,"parse failed: %s\n",err?err->message:"unknown");
        if(err) g_error_free(err);
        return 1;
    }

    printf("COUNT\t%u\n",g_list_length(db->tracks));
    for(GList *p=db->tracks;p;p=p->next){
        Itdb_Track *t=p->data;
        printf("T\t%" PRIu64 "\t",(uint64_t)t->dbid);
        hexs(t->ipod_path);
        putchar('\t');
        hexs(t->title);
        putchar('\n');
    }

    itdb_free(db);
    return 0;
}
'''


def compile_cdb_auditor(work: Path) -> Path:
    src = work / "cdb-audit.c"
    exe = work / "cdb-audit"
    src.write_text(CDB_AUDIT_C)
    inc, libdir = find_libgpod_install()
    glib = run(["pkg-config", "--cflags", "--libs", "glib-2.0"]).stdout.split()
    run([
        "gcc", "-O2", "-Wall", "-Wextra", f"-I{inc}", str(src),
        f"-L{libdir}", f"-Wl,-rpath,{libdir}", "-lgpod", *glib,
        "-o", str(exe),
    ])
    return exe


def cdb_inventory(
    exe: Path,
    cdb_path: Path,
    device_dir: Path,
    work: Path,
    label: str,
) -> dict[int, tuple[str, str]]:
    """
    Parse exactly one CDB through libgpod's normal compressed-CDB path.

    The auditor receives a disposable host-side iPod tree containing only the
    real Device metadata and the CDB under test.  It never points libgpod at
    the writable live iPod tree.
    """
    root = work / f"cdb-audit-mount-{label}"
    if root.exists():
        shutil.rmtree(root)

    (root / "iTunes_Control/iTunes").mkdir(parents=True, exist_ok=False)
    shutil.copytree(device_dir, root / "iTunes_Control/Device")
    shutil.copy2(cdb_path, root / "iTunes_Control/iTunes/iTunesCDB")

    try:
        proc = run([str(exe), str(root)], check=False)
        if proc.returncode != 0:
            detail = (proc.stdout or "").strip()
            raise SyncError(
                f"libgpod CDB audit failed for {label} ({cdb_path}); "
                f"exit={proc.returncode}; output={detail!r}"
            )
        out = proc.stdout.splitlines()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if not out or not out[0].startswith("COUNT\t"):
        raise SyncError(f"cannot audit CDB: {cdb_path}")

    expected = int(out[0].split("\t", 1)[1])
    tracks: dict[int, tuple[str, str]] = {}
    for line in out[1:]:
        parts = line.split("\t")
        if len(parts) != 4 or parts[0] != "T":
            raise SyncError(f"malformed CDB auditor output for {label}: {line!r}")
        dbid = int(parts[1])
        try:
            path_s = bytes.fromhex(parts[2]).decode("utf-8") if parts[2] else ""
            title = bytes.fromhex(parts[3]).decode("utf-8") if parts[3] else ""
        except (ValueError, UnicodeDecodeError) as exc:
            raise SyncError(f"invalid UTF-8/hex from CDB auditor for {label}") from exc
        if dbid in tracks:
            raise SyncError(f"duplicate persistent DBID in CDB: {dbid}")
        tracks[dbid] = (path_s, title)

    if len(tracks) != expected:
        raise SyncError(
            f"CDB count mismatch for {label}: header={expected}, parsed={len(tracks)}"
        )
    return tracks


def validate_cdb_semantics(c: Candidate, mount: Path, validation_dir: Path):
    exe = compile_cdb_auditor(validation_dir)
    lp = live_paths(mount)
    device_dir = mount / "iTunes_Control/Device"
    live = cdb_inventory(
        exe, lp["iTunesCDB"], device_dir, validation_dir, "live"
    )
    cand = cdb_inventory(
        exe, c.cdb, device_dir, validation_dir, "candidate"
    )
    n = len(c.tracks)
    if len(cand) != len(live) + n:
        raise SyncError(f"candidate CDB count {len(cand)} != live {len(live)} + {n}")
    for dbid, semantic in live.items():
        if cand.get(dbid) != semantic:
            raise SyncError(f"existing CDB persistent semantic changed for DBID {dbid}")
    expected_new = {t.dbid_u64 for t in c.tracks}
    actual_new = set(cand) - set(live)
    if actual_new != expected_new:
        raise SyncError("candidate CDB new persistent DBID set is not exact")
    for t in c.tracks:
        semantic = cand[t.dbid_u64]
        if semantic != (t.apple_path, t.title):
            raise SyncError(f"candidate CDB path/title mismatch: {t.title}")

def validate_cbk_exact(c: Candidate, mount: Path, validation_dir: Path):
    helper = compile_cbk_helper(validation_dir)
    regenerated = validation_dir / "Locations.itdb.cbk.regenerated"
    lp = live_paths(mount)
    build_cbk(lp["Locations.itdb"], lp["Locations.itdb.cbk"], c.locations, regenerated, helper)
    if regenerated.read_bytes() != c.cbk.read_bytes():
        raise SyncError("candidate Locations.itdb.cbk does not exactly sign candidate Locations.itdb")


def validate_cdb_signature_exact(c: Candidate, mount: Path, validation_dir: Path):
    raw = c.cdb.read_bytes()
    if len(raw) < HASH72_OFF + HASH72_LEN or raw[:4] != b"mhbd":
        raise SyncError("candidate iTunesCDB container is malformed")
    unsigned = bytearray(raw)
    unsigned[HASH72_OFF:HASH72_OFF + HASH72_LEN] = b"\x00" * HASH72_LEN
    unsigned_path = validation_dir / "iTunesCDB.verify-unsigned"
    regenerated = validation_dir / "iTunesCDB.verify-signed"
    # The native signer deliberately refuses to overwrite an existing signed
    # output. Candidate validation can run more than once in a single --apply
    # invocation, so each pass must start with a nonexistent output path.
    unsigned_path.unlink(missing_ok=True)
    regenerated.unlink(missing_ok=True)
    unsigned_path.write_bytes(unsigned)
    signer = compile_current_cdb_signer(validation_dir)
    lp = live_paths(mount)
    run([str(signer), str(lp["iTunesCDB"]), str(lp["HashInfo"]), str(unsigned_path), str(regenerated)])
    if regenerated.read_bytes() != raw:
        raise SyncError("candidate CDB Hash72 does not regenerate exactly from current device state")
    inflate_container, _ = import_cdb_module()
    inflate_container(raw)


def validate_candidate(c: Candidate, mount: Path, run_dir: Path):
    for p in (c.library, c.dynamic, c.locations):
        if sqlite_integrity(p) != "ok":
            raise SyncError(f"candidate SQLite integrity failed: {p}")
    for p in (c.cbk, c.cdb):
        if not p.is_file() or p.stat().st_size == 0:
            raise SyncError(f"candidate file missing/empty: {p}")

    validate_expected_new_rows(c, mount)

    validation_root = run_dir / "validation"
    validation_root.mkdir(parents=True, exist_ok=True)
    # Validation is intentionally repeatable: main() validates once before
    # presenting the plan and apply_transaction() validates again immediately
    # before any writable-device preparation. Never let artifacts from the
    # first pass affect the second pass.
    validation_dir = validation_root / f"pass-{time.time_ns()}"
    validation_dir.mkdir(parents=False, exist_ok=False)
    validate_cbk_exact(c, mount, validation_dir)
    validate_cdb_signature_exact(c, mount, validation_dir)
    validate_cdb_semantics(c, mount, validation_dir)

    result = {
        "status": "PASS",
        "mode": c.mode,
        "tracks": len(c.tracks),
        "candidate_sha256": candidate_hashes(c),
        "gates": {
            "sqlite_integrity": True,
            "schema_identical": True,
            "existing_rows_preserved": True,
            "exact_new_pid_rows": True,
            "locations_cbk_exact": True,
            "cdb_hash72_exact": True,
            "cdb_existing_persistent_semantics_preserved": True,
            "cdb_new_dbids_paths_titles_exact": True,
        },
    }
    atomic_write_json(run_dir / "VALIDATION.json", result)


def fsync_dir(path: Path):
    with contextlib.suppress(OSError):
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    with tmp.open("w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def set_active_journal(journal: dict, **updates):
    journal.update(updates)
    journal["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    atomic_write_json(ACTIVE_TXN, journal)


def clear_active_journal():
    ACTIVE_TXN.unlink(missing_ok=True)
    fsync_dir(ACTIVE_TXN.parent)


def free_bytes(path: Path) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def backup_databases(mount: Path, run_dir: Path) -> dict[str, Path]:
    rollback = run_dir / "rollback"
    rollback.mkdir(parents=True, exist_ok=False)
    lp = live_paths(mount)
    result: dict[str, Path] = {}
    for name in SNAPSHOT_NAMES:
        dst = rollback / name
        shutil.copy2(lp[name], dst)
        if sha256_file(dst) != sha256_file(lp[name]):
            raise SyncError(f"rollback snapshot verification failed: {name}")
        result[name] = dst
    return result


def safe_replace_file(src: Path, dst: Path):
    tmp = dst.with_name(dst.name + ".ipodctl-new")
    tmp.unlink(missing_ok=True)
    expected = sha256_file(src)
    shutil.copyfile(src, tmp)
    if sha256_file(tmp) != expected:
        tmp.unlink(missing_ok=True)
        raise SyncError(f"device-side verification failed: {dst}")
    os.replace(tmp, dst)


def restore_databases(rollback: dict[str, Path], mount: Path):
    lp = live_paths(mount)
    for name in REPLACED_DB_NAMES:
        safe_replace_file(rollback[name], lp[name])


def validate_rollback_snapshots(rollback: dict[str, Path], expected: dict[str, str]):
    for name in SNAPSHOT_NAMES:
        path = rollback.get(name)
        if path is None or not path.is_file():
            raise SyncError(f"rollback snapshot missing: {name}")
        if sha256_file(path) != expected[name]:
            raise SyncError(f"rollback snapshot hash changed: {name}")


def validate_destinations_absent(tracks: list[Track], mount: Path):
    for t in tracks:
        final = mount / t.device_rel
        part = final.with_name(final.name + ".ipodctl-part")
        dbtmp = final.with_name(final.name + ".ipodctl-new")
        if final.exists() or part.exists() or dbtmp.exists():
            raise SyncError(f"planned destination is not clean: {t.device_rel}")


def delete_transaction_media(tracks: list[Track], mount: Path):
    music_root = (mount / "iTunes_Control/Music").resolve()
    for t in tracks:
        final = mount / t.device_rel
        try:
            final.resolve().relative_to(music_root)
        except ValueError:
            raise SyncError(f"unsafe recovery media path: {t.device_rel}")
        for path in (final, final.with_name(final.name + ".ipodctl-part")):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()


def verify_live_preimage_hashes(mount: Path, expected: dict[str, str]):
    lp = live_paths(mount)
    for name in SNAPSHOT_NAMES:
        actual = sha256_file(lp[name])
        if actual != expected[name]:
            raise SyncError(f"live preimage mismatch for {name}: {actual} != {expected[name]}")


def verify_core_rollback(mount: Path, expected: dict[str, str]):
    lp = live_paths(mount)
    for name in REPLACED_DB_NAMES:
        if sha256_file(lp[name]) != expected[name]:
            raise SyncError(f"rollback did not restore {name}")
    if sha256_file(lp["HashInfo"]) != expected["HashInfo"]:
        raise SyncError("HashInfo changed unexpectedly")
    for name in ("Library.itdb", "Dynamic.itdb", "Locations.itdb"):
        if sqlite_integrity(lp[name]) != "ok":
            raise SyncError(f"rollback SQLite integrity failed: {name}")


class SyncEnvelope:
    """Hold the validated native iTunes sync lock while Python writes."""

    def __init__(self, helper: Path):
        self.helper = helper
        self.p: subprocess.Popen | None = None

    def __enter__(self):
        if not self.helper.is_file():
            raise SyncError(f"sync envelope helper missing: {self.helper}")
        self.p = subprocess.Popen(
            [str(self.helper)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
        )
        assert self.p.stdout is not None
        active = False
        deadline = time.monotonic() + 30.0

        # The current native helper emits a single READY line only after the
        # syncWillStart / syncLockRequest / exclusive AFC lock / syncDidStart
        # sequence has succeeded, then blocks on stdin until we close it.
        # Older proven helpers emitted "SYNC SESSION IS NOW ACTIVE".
        # Read the pipe in unbuffered binary mode: using TextIOWrapper.readline
        # together with select can strand already-buffered lines in Python and
        # deadlock even though the OS fd is no longer readable.
        selector = selectors.DefaultSelector()
        selector.register(self.p.stdout, selectors.EVENT_READ)
        pending = b""
        try:
            while time.monotonic() < deadline and not active:
                if self.p.poll() is not None and not pending:
                    break
                remaining = max(0.0, deadline - time.monotonic())
                events = selector.select(timeout=min(0.5, remaining))
                if not events:
                    continue
                chunk = os.read(self.p.stdout.fileno(), 4096)
                if not chunk:
                    if self.p.poll() is not None:
                        break
                    continue
                pending += chunk
                while b"\n" in pending:
                    raw_line, pending = pending.split(b"\n", 1)
                    line = raw_line.decode("utf-8", errors="replace") + "\n"
                    print(line, end="", flush=True)
                    stripped = line.strip()
                    if stripped == "READY" or "SYNC SESSION IS NOW ACTIVE" in line:
                        active = True
                        break
        finally:
            selector.close()

        if not active:
            try:
                self.close()
            finally:
                raise SyncError("sync envelope did not become active")
        return self

    def close(self):
        p = self.p
        if not p:
            return
        self.p = None
        if p.poll() is None and p.stdin:
            with contextlib.suppress(Exception):
                p.stdin.write(b"FINISH\n")
                p.stdin.flush()
        try:
            out, _ = p.communicate(timeout=20)
            if out:
                print(out.decode("utf-8", errors="replace"), end="")
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
            if out:
                print(out.decode("utf-8", errors="replace"), end="")
            raise SyncError("sync envelope helper did not close")
        if p.returncode != 0:
            raise SyncError(f"sync envelope helper exited {p.returncode}")

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def write_media(track: Track, mount: Path):
    dst = mount / track.device_rel
    if dst.exists():
        raise SyncError(f"destination unexpectedly exists: {track.device_rel}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".ipodctl-part")
    tmp.unlink(missing_ok=True)

    if track.direct_mp3:
        digest, size = sha256_stream_copy(track.source, tmp)
        if digest != track.sha256 or size != track.source_size:
            tmp.unlink(missing_ok=True)
            raise SyncError(f"stream verification failed: {track.source}")
    else:
        ffmpeg = require_cmd("ffmpeg")
        run([
            ffmpeg,
            "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(track.source),
            "-map", "0:a:0", "-vn", "-map_metadata", "-1",
            "-codec:a", "libmp3lame", "-b:a", "256k",
            "-f", "mp3",
            str(tmp),
        ])
        if track.output_size is not None and tmp.stat().st_size != track.output_size:
            tmp.unlink(missing_ok=True)
            raise SyncError(f"transcode output size changed: {track.source}")
        if track.output_sha256 and sha256_file(tmp) != track.output_sha256:
            tmp.unlink(missing_ok=True)
            raise SyncError(f"transcode output hash changed: {track.source}")
    os.replace(tmp, dst)


def post_validate(
    mount: Path,
    tracks: list[Track],
    candidate: Candidate,
    extras_snapshot: Path,
    run_dir: Path,
):
    lp = live_paths(mount)
    for p in (lp["Library.itdb"], lp["Dynamic.itdb"], lp["Locations.itdb"], lp["Extras.itdb"]):
        if sqlite_integrity(p) != "ok":
            raise SyncError(f"post-sync integrity failed: {p.name}")

    # iOS may advance __CPRecordSequenceNumber, but the actual music tables
    # must remain semantically equal to the validated candidate.
    for table in user_tables(candidate.library):
        if table == "_SqliteDatabaseProperties":
            continue
        if table_multiset(candidate.library, table) != table_multiset(lp["Library.itdb"], table):
            raise SyncError(f"post-sync Library semantic mismatch in table {table}")
    if not sqlite_semantically_equal(candidate.dynamic, lp["Dynamic.itdb"]):
        raise SyncError("post-sync Dynamic.itdb semantic mismatch")
    if not sqlite_semantically_equal(candidate.locations, lp["Locations.itdb"]):
        raise SyncError("post-sync Locations.itdb semantic mismatch")

    # Extras is never replaced by us.  SQLite container bytes may be rewritten
    # by iOS, so require semantic equality rather than byte identity.
    if not sqlite_semantically_equal(extras_snapshot, lp["Extras.itdb"]):
        raise SyncError("Extras.itdb semantic content changed")

    lib = sqlite3.connect(f"file:{lp['Library.itdb']}?mode=ro", uri=True)
    loc = sqlite3.connect(f"file:{lp['Locations.itdb']}?mode=ro", uri=True)
    try:
        for t in tracks:
            r = lib.execute(
                "SELECT title,COALESCE(artist,''),COALESCE(album,''),COALESCE(album_artist,'') "
                "FROM item WHERE pid=?", (t.pid,),
            ).fetchone()
            if not r or tuple(r) != (t.title, "", "", ""):
                raise SyncError(f"post-sync Library mismatch for {t.title}")
            l = loc.execute("SELECT location FROM location WHERE item_pid=?", (t.pid,)).fetchone()
            if not l or l[0] != f"{t.folder}/{t.basename}":
                raise SyncError(f"post-sync Locations mismatch for {t.title}")
    finally:
        lib.close(); loc.close()

    # Full device-side media readback.  This is intentionally expensive on the
    # first bulk sync: success means every new device file hashes exactly.
    for i, t in enumerate(tracks, 1):
        path = mount / t.device_rel
        if not path.is_file():
            raise SyncError(f"post-sync media missing: {t.device_rel}")
        expected_size = int(t.output_size or t.source_size)
        if path.stat().st_size != expected_size:
            raise SyncError(f"post-sync media size mismatch: {t.device_rel}")
        expected_hash = t.output_sha256 or (t.sha256 if t.direct_mp3 else "")
        if not expected_hash:
            raise SyncError(f"no planned output hash for readback: {t.source_rel}")
        if sha256_file(path) != expected_hash:
            raise SyncError(f"post-sync media SHA256 mismatch: {t.device_rel}")
        if i % 25 == 0 or i == len(tracks):
            print(f"device media readback: {i}/{len(tracks)}")

    # CDB persistent semantics and CBK relationship are checked again against
    # the actual post-sync live files.
    validation_dir = run_dir / "post-validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    auditor = compile_cdb_auditor(validation_dir)
    device_dir = mount / "iTunes_Control/Device"
    cand_cdb = cdb_inventory(
        auditor, candidate.cdb, device_dir, validation_dir, "candidate-post"
    )
    live_cdb = cdb_inventory(
        auditor, lp["iTunesCDB"], device_dir, validation_dir, "live-post"
    )
    if live_cdb != cand_cdb:
        raise SyncError("post-sync live CDB persistent semantics differ from candidate")

    helper = compile_cbk_helper(validation_dir)
    regenerated_cbk = validation_dir / "live-locations.cbk.regenerated"
    build_cbk(lp["Locations.itdb"], lp["Locations.itdb.cbk"], lp["Locations.itdb"], regenerated_cbk, helper)
    if regenerated_cbk.read_bytes() != lp["Locations.itdb.cbk"].read_bytes():
        raise SyncError("post-sync live Locations CBK failed exact regeneration")


def tracks_to_journal(tracks: list[Track]) -> list[dict]:
    return [{
        "source_rel": t.source_rel,
        "title": t.title,
        "sha256": t.sha256,
        "source_size": t.source_size,
        "output_size": t.output_size,
        "output_sha256": t.output_sha256,
        "pid": t.pid,
        "dbid_u64": t.dbid_u64,
        "folder": t.folder,
        "basename": t.basename,
        "device_rel": t.device_rel,
        "apple_path": t.apple_path,
    } for t in tracks]


def track_from_journal(r: dict) -> Track:
    # Recovery never reads the source, but Track keeps a placeholder path.
    return Track(
        source=Path("/nonexistent-recovery-source"),
        source_rel=r["source_rel"], title=r["title"], sha256=r.get("sha256", ""),
        source_size=int(r["source_size"]), duration_ms=0, bitrate_kbps=0,
        sample_rate_hz=0, direct_mp3=True, dbid_u64=int(r["dbid_u64"]),
        pid=int(r["pid"]), folder=r["folder"], basename=r["basename"],
        device_rel=r["device_rel"], apple_path=r["apple_path"],
        output_size=int(r["output_size"]) if r.get("output_size") is not None else None,
        output_sha256=r.get("output_sha256", ""),
    )


def rollback_under_lock(
    rollback: dict[str, Path],
    mount: Path,
    tracks: list[Track],
    pre_hash: dict[str, str],
):
    restore_databases(rollback, mount)
    delete_transaction_media(tracks, mount)
    verify_core_rollback(mount, pre_hash)


def fresh_envelope_rollback(
    rollback: dict[str, Path], mount: Path, tracks: list[Track], pre_hash: dict[str, str]
):
    with SyncEnvelope(SYNC_ENVELOPE):
        rollback_under_lock(rollback, mount, tracks, pre_hash)


def journal_rollback_paths(run_dir: Path) -> dict[str, Path]:
    return {name: run_dir / "rollback" / name for name in SNAPSHOT_NAMES}


def verify_prewrite_noop_state(rollback, mount: Path, tracks: list[Track], pre_hash: dict[str, str]) -> dict:
    lp = live_paths(mount)
    leftovers = []
    for t in tracks:
        final = mount / t.device_rel
        partial = final.with_name(final.name + ".ipodctl-part")
        if final.exists(): leftovers.append(str(final))
        if partial.exists(): leftovers.append(str(partial))
    for name in REPLACED_DB_NAMES:
        tmp = lp[name].with_name(lp[name].name + ".ipodctl-new")
        if tmp.exists(): leftovers.append(str(tmp))
    if leftovers:
        raise SyncError("pre-write recovery found transaction output; refusing no-write cleanup: " + ", ".join(leftovers[:10]))
    exact_names = ("Dynamic.itdb", "Locations.itdb", "Locations.itdb.cbk", "iTunesCDB", "HashInfo")
    for name in exact_names:
        actual = sha256_file(lp[name])
        if actual != pre_hash[name]:
            raise SyncError(f"pre-write recovery mismatch for {name}: {actual} != {pre_hash[name]}")
    if sqlite_integrity(lp["Extras.itdb"]) != "ok":
        raise SyncError("live Extras.itdb integrity failed during pre-write recovery")
    if not sqlite_semantically_equal(rollback["Extras.itdb"], lp["Extras.itdb"]):
        raise SyncError("Extras.itdb changed semantically; refusing no-write recovery cleanup")
    cp = library_equal_except_cp_sequence(rollback["Library.itdb"], lp["Library.itdb"])
    return {
        "library_cp_sequence_before": cp["reference"],
        "library_cp_sequence_after": cp["live"],
        "library_only_cp_sequence_drift": cp["live"] != cp["reference"],
        "extras_semantically_equal": True,
        "exact_files": list(exact_names),
        "transaction_media_absent": True,
    }


RECOVERABLE_JOURNAL_PHASES = frozenset({
    "prepared",
    "rw-preimage-verified",
    "sync-lock-active",
    "media-copying",
    "media-complete",
    "db-commit-started",
    "db-committed",
    "rollback-started",
    "rollback-complete",
    "sync-envelope-closed",
    "sync-close-failed",
    "rollback-complete-after-close-failure",
    "recovery-required",
    "post-validating",
    "post-validation-failed",
    "rollback-complete-after-post-validation",
    "recovery-started",
    "recovery-restored",
    "recovery-failed",
})


def recovery_journal_phase(journal: dict) -> str:
    phase = journal.get("phase")
    if phase not in RECOVERABLE_JOURNAL_PHASES:
        raise SyncError(
            f"unknown or non-recoverable transaction journal phase: {phase!r}"
        )
    return phase


def recover_check(mount: Path) -> int:
    """Read-only inspection of an incomplete transaction.

    Never remounts the iPod writable, never clears the active journal, and
    never touches the source.  It only proves whether the saved preimage has
    already been restored and whether transaction media is absent.
    """
    if not ACTIVE_TXN.is_file():
        print("No incomplete transaction journal exists. Nothing to check.")
        return 0

    journal = load_json(ACTIVE_TXN)
    phase = recovery_journal_phase(journal)
    run_dir = Path(journal["run_dir"])
    print(f"RECOVERY CHECK: {run_dir}")
    verify_device_connection()
    require_ifuse_mount(mount, writable=False)

    rollback = journal_rollback_paths(run_dir)
    pre_hash = journal["preimage_sha256"]
    validate_rollback_snapshots(rollback, pre_hash)
    tracks = [track_from_journal(r) for r in journal["tracks"]]

    try:
        report = verify_prewrite_noop_state(rollback, mount, tracks, pre_hash)
    except SyncError as exc:
        print(f"journal phase:      {phase}")
        print("rollback state:     NOT PROVEN")
        print(f"reason:             {exc}")
        print("iPod remains read-only: PASS")
        print("No recovery write was attempted.")
        return 2

    print(f"journal phase:      {phase}")
    print("core preimage:      PASS")
    print("transaction media: ABSENT")
    print("Extras semantics:  PASS")
    if report["library_only_cp_sequence_drift"]:
        print(
            "Library CP sequence: "
            f"{report['library_cp_sequence_before']} -> {report['library_cp_sequence_after']} "
            "(allowed bookkeeping-only drift)"
        )
    else:
        print(f"Library CP sequence: {report['library_cp_sequence_after']} (unchanged)")
    print("RECOVERY CHECK: PASS (rollback already complete; no iPod write required)")
    print("iPod remains read-only: PASS")
    print("Active journal preserved for explicit --recover cleanup.")
    return 0


def recover_transaction(mount: Path) -> int:
    if not ACTIVE_TXN.is_file():
        print("No incomplete transaction journal exists. Nothing to recover.")
        return 0
    journal = load_json(ACTIVE_TXN)
    run_dir = Path(journal["run_dir"])
    commit = run_dir / "COMMIT.json"
    if commit.is_file():
        print("Transaction already has a durable COMMIT record; clearing stale active journal.")
        clear_active_journal()
        return 0

    phase = recovery_journal_phase(journal)

    print(f"RECOVERY REQUIRED: {run_dir}")
    verify_device_connection()
    require_ifuse_mount(mount, writable=False)
    rollback = journal_rollback_paths(run_dir)
    pre_hash = journal["preimage_sha256"]
    validate_rollback_snapshots(rollback, pre_hash)
    tracks = [track_from_journal(r) for r in journal["tracks"]]

    # First try to prove that no device write is required for recovery.
    # This applies not only to pre-media interruptions, but also to failures
    # where rollback_under_lock() completed and only the envelope FINISH
    # handshake failed afterward.  The proof is deliberately strict:
    # all transaction media/partials must be absent, all non-Library core
    # files must exactly match the saved preimage, Extras must be
    # semantically unchanged, and Library may differ only by Apple's
    # monotonically-advanced __CPRecordSequenceNumber bookkeeping.
    try:
        report = verify_prewrite_noop_state(rollback, mount, tracks, pre_hash)
    except SyncError:
        report = None

    if report is not None:
        mode = (
            "pre-write-interruption"
            if phase in {"prepared", "rw-preimage-verified"}
            else "rollback-already-complete"
        )
        atomic_write_json(run_dir / "RECOVERY.json", {
            "status": "PASS",
            "mode": mode,
            "interrupted_phase": phase,
            "verification": report,
            "recovered_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        clear_active_journal()
        if report["library_only_cp_sequence_drift"]:
            print(
                "Library CPRecordSequenceNumber advanced during sync-envelope close: "
                f"{report['library_cp_sequence_before']} -> {report['library_cp_sequence_after']} "
                "(allowed bookkeeping-only drift)"
            )
        if mode == "rollback-already-complete":
            print("RECOVERY: PASS (rollback already complete; no iPod write required)")
        else:
            print("RECOVERY: PASS (pre-write interruption; no iPod write required)")
        print("iPod remains read-only: PASS")
        return 0

    set_active_journal(journal, phase="recovery-started")
    remount_ifuse(mount, writable=True)
    try:
        with SyncEnvelope(SYNC_ENVELOPE):
            rollback_under_lock(rollback, mount, tracks, pre_hash)
        set_active_journal(journal, phase="recovery-restored")
    except Exception as exc:
        set_active_journal(journal, phase="recovery-failed", error=str(exc))
        raise SyncError(
            "automatic recovery did not complete; journal preserved at "
            f"{ACTIVE_TXN}: {exc}"
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            remount_ifuse(mount, writable=False)

    require_ifuse_mount(mount, writable=False)
    verify_core_rollback(mount, pre_hash)
    for t in tracks:
        if (mount / t.device_rel).exists():
            raise SyncError(f"recovery left transaction media behind: {t.device_rel}")
    atomic_write_json(run_dir / "RECOVERY.json", {
        "status": "PASS", "recovered_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "restored_sha256": {name: sha256_file(live_paths(mount)[name]) for name in REPLACED_DB_NAMES},
    })
    clear_active_journal()
    print("RECOVERY: PASS")
    print("iPod remounted read-only: PASS")
    return 0


def update_state(tracks: list[Track], mode: str):
    state: dict[str, Any] = {"version": 1, "tracks": {}, "last_mode": mode}
    if SYNC_STATE.is_file():
        with contextlib.suppress(Exception):
            old = json.loads(SYNC_STATE.read_text())
            if isinstance(old, dict):
                state.update(old)
                state.setdefault("tracks", {})
    for t in tracks:
        state["tracks"][t.source_rel] = {
            "title": t.title,
            "sha256": t.sha256,
            "pid": t.pid,
            "dbid_u64": t.dbid_u64,
            "device_rel": t.device_rel,
        }
    SYNC_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SYNC_STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, SYNC_STATE)


def write_run_manifest(run_dir: Path, candidate: Candidate, apply: bool):
    obj = {
        "app": APP,
        "version": VERSION,
        "mode": candidate.mode,
        "apply": apply,
        "device_write_authorized": bool(apply),
        "nas_write_policy": "FORBIDDEN; source filesystem must remain kernel-mounted read-only",
        "candidate_sha256": candidate_hashes(candidate),
        "tracks": [
            {
                "source": str(t.source),
                "source_rel": t.source_rel,
                "title": t.title,
                "sha256": t.sha256,
                "source_size": t.source_size,
                "output_size": t.output_size,
                "output_sha256": t.output_sha256,
                "pid": t.pid,
                "dbid_u64": t.dbid_u64,
                "device_rel": t.device_rel,
                "apple_path": t.apple_path,
            }
            for t in candidate.tracks
        ],
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(obj, indent=2, sort_keys=True) + "\n"
    )


def apply_transaction(
    source: Path,
    mount: Path,
    candidate: Candidate,
    run_dir: Path,
):
    if ACTIVE_TXN.exists():
        raise SyncError(f"incomplete transaction journal exists; run --recover first: {ACTIVE_TXN}")

    verify_device_connection()
    source_guard = require_source_ro(source)
    assert_no_write_roots_on_source(source_guard, mount)
    require_ifuse_mount(mount, writable=False)
    validate_tracks_source(candidate.tracks, source, source_guard)
    validate_candidate(candidate, mount, run_dir)
    validate_destinations_absent(candidate.tracks, mount)

    media_bytes = sum(int(t.output_size or t.source_size) for t in candidate.tracks)
    available = free_bytes(mount)
    if available < media_bytes + IPOD_RESERVE_BYTES:
        raise SyncError(
            f"insufficient iPod space: available={available}, media={media_bytes}, "
            f"reserve={IPOD_RESERVE_BYTES}"
        )

    rollback = backup_databases(mount, run_dir)
    pre_hash = {name: sha256_file(path) for name, path in rollback.items()}
    validate_rollback_snapshots(rollback, pre_hash)
    atomic_write_json(run_dir / "preimage.json", pre_hash)

    journal = {
        "app": APP,
        "version": VERSION,
        "run_dir": str(run_dir),
        "phase": "prepared",
        "preimage_sha256": pre_hash,
        "candidate_sha256": candidate_hashes(candidate),
        "candidate_mode": candidate.mode,
        "tracks": tracks_to_journal(candidate.tracks),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    set_active_journal(journal, phase="prepared")

    operation_error: Exception | None = None
    rollback_done = False
    envelope_closed = False
    db_committed = False
    env: SyncEnvelope | None = None

    remount_ifuse(mount, writable=True)
    try:
        verify_live_preimage_hashes(mount, pre_hash)
        validate_destinations_absent(candidate.tracks, mount)
        set_active_journal(journal, phase="rw-preimage-verified")

        recheck_source_guard(source_guard)
        env = SyncEnvelope(SYNC_ENVELOPE)
        env.__enter__()
        set_active_journal(journal, phase="sync-lock-active")

        try:
            set_active_journal(journal, phase="media-copying")
            total = len(candidate.tracks)
            for i, t in enumerate(candidate.tracks, 1):
                # Re-assert the kernel read-only source barrier before every source read.
                recheck_source_guard(source_guard)
                print(f"[{i}/{total}] {t.source_rel} -> {t.device_rel}")
                write_media(t, mount)
            set_active_journal(journal, phase="media-complete")

            # Recheck host candidate hashes and device preimage immediately
            # before the five-file database commit.
            if candidate_hashes(candidate) != journal["candidate_sha256"]:
                raise SyncError("candidate database files changed during media transfer")
            verify_live_preimage_hashes(mount, pre_hash)
            set_active_journal(journal, phase="db-commit-started")

            lp = live_paths(mount)
            committed = []
            for name, src in (
                ("Dynamic.itdb", candidate.dynamic),
                ("Library.itdb", candidate.library),
                ("Locations.itdb", candidate.locations),
                ("Locations.itdb.cbk", candidate.cbk),
                ("iTunesCDB", candidate.cdb),
            ):
                safe_replace_file(src, lp[name])
                if sha256_file(lp[name]) != sha256_file(src):
                    raise SyncError(f"post-replace hash mismatch: {name}")
                committed.append(name)
                set_active_journal(journal, phase="db-commit-started", db_files_committed=committed)
            db_committed = True
            set_active_journal(journal, phase="db-committed", db_files_committed=committed)

        except Exception as exc:
            operation_error = exc
            set_active_journal(journal, phase="rollback-started", error=str(exc))
            try:
                rollback_under_lock(rollback, mount, candidate.tracks, pre_hash)
                rollback_done = True
                set_active_journal(journal, phase="rollback-complete")
            except Exception as rb_exc:
                set_active_journal(journal, phase="recovery-required", error=f"{exc}; rollback: {rb_exc}")

        # Close explicitly so a close/notification failure is part of the
        # transaction result, not something that escapes after commit.
        try:
            env.close()
            env = None
            envelope_closed = True
            set_active_journal(journal, phase="sync-envelope-closed")
        except Exception as close_exc:
            set_active_journal(journal, phase="sync-close-failed", error=str(close_exc))
            if not rollback_done:
                try:
                    fresh_envelope_rollback(rollback, mount, candidate.tracks, pre_hash)
                    rollback_done = True
                    set_active_journal(journal, phase="rollback-complete-after-close-failure")
                except Exception as rb_exc:
                    set_active_journal(
                        journal, phase="recovery-required",
                        error=f"sync close: {close_exc}; rollback: {rb_exc}",
                    )
            operation_error = operation_error or close_exc

    finally:
        if env is not None:
            with contextlib.suppress(Exception):
                env.close()
        try:
            remount_ifuse(mount, writable=False)
        except Exception as exc:
            set_active_journal(journal, phase="recovery-required", error=f"remount-ro: {exc}")
            raise SyncError(f"could not restore read-only iPod mount; run --recover: {exc}") from exc

    require_ifuse_mount(mount, writable=False)

    if operation_error is not None:
        if rollback_done:
            verify_core_rollback(mount, pre_hash)
            for t in candidate.tracks:
                if (mount / t.device_rel).exists():
                    raise SyncError(
                        f"rollback left media behind; run --recover: {t.device_rel}"
                    ) from operation_error
            if envelope_closed:
                atomic_write_json(run_dir / "ROLLBACK.json", {
                    "status": "PASS",
                    "reason": str(operation_error),
                    "restored_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                })
                clear_active_journal()
                raise SyncError(f"transaction aborted and rolled back safely: {operation_error}") from operation_error
        raise SyncError(
            f"transaction incomplete; persistent recovery journal preserved. "
            f"Run {Path(sys.argv[0]).name} --recover"
        ) from operation_error

    if not db_committed or not envelope_closed:
        set_active_journal(journal, phase="recovery-required", error="commit state incomplete")
        raise SyncError("transaction state incomplete; run --recover")

    # Read-only post-commit verification.  A failure here triggers a fresh
    # sync-locked rollback rather than leaving an unvalidated commit live.
    try:
        set_active_journal(journal, phase="post-validating")
        post_validate(
            mount, candidate.tracks, candidate,
            rollback["Extras.itdb"], run_dir,
        )
    except Exception as post_exc:
        set_active_journal(journal, phase="post-validation-failed", error=str(post_exc))
        remount_ifuse(mount, writable=True)
        try:
            fresh_envelope_rollback(rollback, mount, candidate.tracks, pre_hash)
            rollback_done = True
            set_active_journal(journal, phase="rollback-complete-after-post-validation")
        except Exception as rb_exc:
            set_active_journal(
                journal, phase="recovery-required",
                error=f"post-validation: {post_exc}; rollback: {rb_exc}",
            )
            raise SyncError("post-validation failed and automatic rollback failed; run --recover") from post_exc
        finally:
            with contextlib.suppress(Exception):
                remount_ifuse(mount, writable=False)
        require_ifuse_mount(mount, writable=False)
        verify_core_rollback(mount, pre_hash)
        atomic_write_json(run_dir / "ROLLBACK.json", {
            "status": "PASS", "reason": f"post-validation failed: {post_exc}",
            "restored_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        clear_active_journal()
        raise SyncError(f"post-validation failed; transaction rolled back safely: {post_exc}") from post_exc

    commit = {
        "status": "PASS",
        "committed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tracks_added": len(candidate.tracks),
        "candidate_mode": candidate.mode,
        "device_read_only": True,
        "full_media_readback": True,
        "extras_semantically_preserved": True,
        "candidate_sha256": candidate_hashes(candidate),
    }
    atomic_write_json(run_dir / "COMMIT.json", commit)
    set_active_journal(journal, phase="committed")
    clear_active_journal()
    update_state(candidate.tracks, candidate.mode)


def build_candidate(source: Path, mount: Path, run_dir: Path) -> Candidate | None:
    print("candidate mode: generic incremental ADD-only")
    tracks = plan_generic(source, mount, run_dir)
    if not tracks:
        return None
    return build_generic_candidate(mount, tracks, run_dir)

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="ADD-only legacy iPod music sync with a kernel read-only source"
    )
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--mount", type=Path, default=DEFAULT_MOUNT)
    ap.add_argument(
        "--apply", action="store_true",
        help="perform live device writes; without this flag the tool is dry-run only",
    )
    ap.add_argument(
        "--recover", action="store_true",
        help="recover/roll back the persistent incomplete transaction journal",
    )
    ap.add_argument(
        "--recover-check", action="store_true",
        help="read-only inspection of an incomplete transaction; never writes to the iPod",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    mount = args.mount.expanduser().resolve()
    require_ifuse_mount(mount, writable=False)

    if args.recover and args.recover_check:
        raise SyncError("--recover and --recover-check are mutually exclusive")
    if args.recover_check:
        if args.apply:
            raise SyncError("--recover-check and --apply are mutually exclusive")
        return recover_check(mount)
    if args.recover:
        if args.apply:
            raise SyncError("--recover and --apply are mutually exclusive")
        return recover_transaction(mount)

    if ACTIVE_TXN.exists():
        journal = load_json(ACTIVE_TXN)
        raise SyncError(
            "an incomplete transaction journal exists and normal sync is blocked: "
            f"phase={journal.get('phase')} run_dir={journal.get('run_dir')}. "
            "Run with --recover."
        )

    source = args.source.expanduser().resolve()
    if not source.is_dir():
        raise SyncError(f"source directory missing: {source}")
    source_guard = require_source_ro(source)
    assert_no_write_roots_on_source(source_guard, mount)
    print(
        f"source write barrier: PASS (kernel RO; {source_guard.fstype} "
        f"mount {source_guard.mountpoint})"
    )

    lp = live_paths(mount)
    for name in ("Library.itdb", "Dynamic.itdb", "Locations.itdb", "Extras.itdb"):
        if sqlite_integrity(lp[name]) != "ok":
            raise SyncError(f"live {name} integrity failed")

    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = RUN_ROOT / stamp
    run_dir.mkdir(parents=True, exist_ok=False)

    recheck_source_guard(source_guard)
    candidate = build_candidate(source, mount, run_dir)
    if candidate is None:
        print("No new songs found. Nothing to do.")
        return 0

    validate_tracks_source(candidate.tracks, source)
    validate_candidate(candidate, mount, run_dir)
    validate_destinations_absent(candidate.tracks, mount)
    write_run_manifest(run_dir, candidate, args.apply)

    media_bytes = sum(int(t.output_size or t.source_size) for t in candidate.tracks)
    print()
    print(f"ADD tracks:       {len(candidate.tracks)}")
    print(f"media bytes:      {media_bytes}")
    print(f"candidate mode:   {candidate.mode}")
    print(f"run directory:    {run_dir}")
    print("VM media staging: none")
    print("source writes:    FORBIDDEN (kernel read-only mount required)")
    print("Extras.itdb:      preserved semantically")
    print("candidate gates:  PASS")
    print("recovery journal: armed only during --apply")
    print()

    if not args.apply:
        print("DRY RUN COMPLETE")
        print("No iPod files modified.")
        print("Use --apply only when you intend to perform the live sync.")
        return 0

    print("LIVE DEVICE WRITE AUTHORIZED BY --apply")
    apply_transaction(source, mount, candidate, run_dir)
    print()
    print("=" * 72)
    print("SYNC COMMITTED")
    print("=" * 72)
    print(f"added: {len(candidate.tracks)}")
    print("full device media SHA256 readback: PASS")
    print("iPod remounted read-only: PASS")
    print("post-sync database validation: PASS")
    print("recovery journal cleared: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        eprint("ABORTED by user")
        raise SystemExit(130)
    except SyncError as exc:
        eprint(f"ERROR: {exc}")
        raise SystemExit(1)
