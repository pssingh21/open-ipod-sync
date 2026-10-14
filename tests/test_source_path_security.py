#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "src" / "ipod_sync.py"

SPEC = importlib.util.spec_from_file_location(
    "ipod_sync_source_security_test",
    APP_PATH,
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load ipod_sync.py")

APP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = APP
SPEC.loader.exec_module(APP)


def fake_probe(_path: Path) -> tuple[int, int, int]:
    return (1000, 128, 44100)


def expect_scan_error(
    root: Path,
    expected: str,
) -> None:
    original = APP.probe_audio
    APP.probe_audio = fake_probe

    try:
        try:
            APP.scan_source(root)
        except APP.SyncError as exc:
            message = str(exc)

            if expected not in message:
                raise AssertionError(
                    f"expected {expected!r} in {message!r}"
                )

            return

        raise AssertionError(
            f"expected source scan failure containing {expected!r}"
        )
    finally:
        APP.probe_audio = original


def test_nested_regular_files_are_supported() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        nested = root / "Artist" / "Album" / "Disc 1"
        nested.mkdir(parents=True)

        first = root / "root-track.mp3"
        second = nested / "nested-track.mp3"

        first.write_bytes(b"root-track")
        second.write_bytes(b"nested-track")
        (nested / "cover.jpg").write_bytes(b"not music")

        original = APP.probe_audio
        APP.probe_audio = fake_probe

        try:
            tracks = APP.scan_source(root)
        finally:
            APP.probe_audio = original

        rels = [
            track.source_rel
            for track in tracks
        ]

        assert rels == [
            "Artist/Album/Disc 1/nested-track.mp3",
            "root-track.mp3",
        ], rels

        for track in tracks:
            assert track.source.is_absolute()


def test_internal_file_symlink_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = root / "real.mp3"
        target.write_bytes(b"real")

        (root / "alias.mp3").symlink_to(
            target.name
        )

        expect_scan_error(
            root,
            "source symlink forbidden",
        )


def test_external_file_symlink_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as source_td, \
         tempfile.TemporaryDirectory() as outside_td:
        root = Path(source_td)
        outside = Path(outside_td) / "outside.mp3"
        outside.write_bytes(b"outside")

        (root / "escape.mp3").symlink_to(
            outside
        )

        expect_scan_error(
            root,
            "source symlink forbidden",
        )


def test_broken_symlink_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        (root / "broken.mp3").symlink_to(
            "does-not-exist.mp3"
        )

        expect_scan_error(
            root,
            "source symlink forbidden",
        )


def test_directory_symlink_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as source_td, \
         tempfile.TemporaryDirectory() as outside_td:
        root = Path(source_td)
        outside = Path(outside_td)

        (outside / "track.mp3").write_bytes(
            b"outside"
        )

        (root / "linked-dir").symlink_to(
            outside,
            target_is_directory=True,
        )

        expect_scan_error(
            root,
            "source symlink forbidden",
        )


def test_fifo_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fifo = root / "stream.mp3"

        os.mkfifo(fifo)

        expect_scan_error(
            root,
            "source special file forbidden",
        )


def test_unix_socket_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        socket_path = root / "metadata.sock"

        sock = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )

        try:
            sock.bind(str(socket_path))

            expect_scan_error(
                root,
                "source special file forbidden",
            )
        finally:
            sock.close()


def test_source_root_symlink_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        real = base / "real"
        real.mkdir()
        (real / "track.mp3").write_bytes(b"track")

        link = base / "source-link"
        link.symlink_to(
            real,
            target_is_directory=True,
        )

        expect_scan_error(
            link,
            "source root symlink forbidden",
        )


def test_hostile_filenames_remain_argv_data() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        names = [
            "--help.mp3",
            "semi;colon.mp3",
            "quote'\".mp3",
            "line\nbreak.mp3",
            "unicode-音楽-ß.mp3",
            "[brackets] $(touch PWNED).mp3",
        ]

        for name in names:
            (root / name).write_bytes(
                name.encode(
                    "utf-8",
                    errors="surrogateescape",
                )
            )

        calls: list[tuple[list[str], dict]] = []

        original_run = APP.subprocess.run
        original_which = APP.shutil.which

        def fake_which(name: str):
            if name == "ffprobe":
                return "/usr/bin/ffprobe"
            return original_which(name)

        def fake_run(args, **kwargs):
            if not isinstance(args, list):
                raise AssertionError(
                    f"external command is not argv list: {args!r}"
                )

            if kwargs.get("shell"):
                raise AssertionError(
                    "shell=True used for hostile source filename"
                )

            calls.append(
                (
                    list(args),
                    dict(kwargs),
                )
            )

            return SimpleNamespace(
                returncode=0,
                stdout=(
                    '{"streams":[{"sample_rate":"44100",'
                    '"bit_rate":"128000","duration":"1.0"}],'
                    '"format":{"duration":"1.0"}}'
                ),
                stderr="",
            )

        APP.shutil.which = fake_which
        APP.subprocess.run = fake_run

        try:
            tracks = APP.scan_source(root)
        finally:
            APP.subprocess.run = original_run
            APP.shutil.which = original_which

        assert len(tracks) == len(names)
        assert len(calls) == len(names)

        scanned = {
            track.source.name
            for track in tracks
        }

        assert scanned == set(names)

        for args, kwargs in calls:
            assert args[0] == "/usr/bin/ffprobe"
            assert Path(args[-1]).is_absolute()
            assert Path(args[-1]).name in names
            assert not kwargs.get("shell", False)

        assert not (root / "PWNED").exists()


def test_leaf_symlink_swap_is_rejected_before_write() -> None:
    with tempfile.TemporaryDirectory() as source_td, \
         tempfile.TemporaryDirectory() as outside_td:
        root = Path(source_td)
        track = root / "track.mp3"
        track.write_bytes(b"original")

        original = APP.probe_audio
        APP.probe_audio = fake_probe

        try:
            tracks = APP.scan_source(root)
        finally:
            APP.probe_audio = original

        outside = Path(outside_td) / "replacement.mp3"
        outside.write_bytes(b"original")

        track.unlink()
        track.symlink_to(outside)

        try:
            APP.validate_tracks_source(
                tracks,
                root,
            )
        except APP.SyncError as exc:
            assert "source symlink forbidden" in str(exc)
        else:
            raise AssertionError(
                "leaf symlink swap was accepted"
            )


def test_parent_symlink_swap_is_rejected_before_write() -> None:
    with tempfile.TemporaryDirectory() as source_td, \
         tempfile.TemporaryDirectory() as outside_td:
        root = Path(source_td)
        album = root / "album"
        album.mkdir()

        track = album / "track.mp3"
        track.write_bytes(b"original")

        original = APP.probe_audio
        APP.probe_audio = fake_probe

        try:
            tracks = APP.scan_source(root)
        finally:
            APP.probe_audio = original

        old_album = root / "album-old"
        album.rename(old_album)

        outside = Path(outside_td)
        (outside / "track.mp3").write_bytes(
            b"original"
        )

        album.symlink_to(
            outside,
            target_is_directory=True,
        )

        try:
            APP.validate_tracks_source(
                tracks,
                root,
            )
        except APP.SyncError as exc:
            assert "source symlink forbidden" in str(exc)
        else:
            raise AssertionError(
                "parent-directory symlink swap was accepted"
            )


def main() -> None:
    test_nested_regular_files_are_supported()
    test_internal_file_symlink_fails_closed()
    test_external_file_symlink_fails_closed()
    test_broken_symlink_fails_closed()
    test_directory_symlink_fails_closed()
    test_fifo_fails_closed()
    test_unix_socket_fails_closed()
    test_source_root_symlink_fails_closed()
    test_hostile_filenames_remain_argv_data()
    test_leaf_symlink_swap_is_rejected_before_write()
    test_parent_symlink_swap_is_rejected_before_write()

    print("source path security tests: PASS")


if __name__ == "__main__":
    main()
