#!/usr/bin/env python3

from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "tools" / "privacy-scan.py"


def run_scan(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCANNER),
            *[str(path) for path in paths],
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require_pass(
    result: subprocess.CompletedProcess[str],
) -> None:
    if result.returncode != 0:
        raise AssertionError(
            "expected privacy scan to pass\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def require_rule(
    result: subprocess.CompletedProcess[str],
    rule: str,
    secret: bytes | None = None,
) -> None:
    if result.returncode != 1:
        raise AssertionError(
            f"expected privacy rule {rule!r} to reject fixture\n"
            f"returncode={result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    if f"rule={rule}" not in result.stderr:
        raise AssertionError(
            f"missing rule {rule!r}\n"
            f"stderr:\n{result.stderr}"
        )

    if secret is not None:
        rendered = secret.decode(
            "utf-8",
            errors="ignore",
        )

        if rendered and (
            rendered in result.stdout
            or rendered in result.stderr
        ):
            raise AssertionError(
                "privacy scanner leaked matched secret into logs"
            )


def test_clean_placeholders() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        (root / "README.txt").write_text(
            "username=YOUR_NAS_USERNAME\n"
            "password=YOUR_NAS_PASSWORD\n"
            "host=nas.example\n"
            "token=${GH_TOKEN}\n"
        )

        require_pass(
            run_scan(root)
        )


def test_content_rules() -> None:
    fixtures = [
        (
            b"/" + b"home" + b"/alice/private/file",
            "linux-user-home-path",
        ),
        (
            b"/" + b"Users" + b"/alice/private/file",
            "macos-user-home-path",
        ),
        (
            b"192" + b".168.44.2",
            "private-rfc1918-ipv4",
        ),
        (
            b"10" + b".20.30.40",
            "private-rfc1918-ipv4",
        ),
        (
            b"172" + b".16.8.9",
            "private-rfc1918-ipv4",
        ),
        (
            b"gh" + b"p_" + (b"A" * 40),
            "github-classic-token",
        ),
        (
            b"github_" + b"pat_" + (b"A" * 30),
            "github-fine-grained-token",
        ),
        (
            b"AKIA" + (b"A" * 16),
            "aws-access-key-id",
        ),
        (
            b"-----BEGIN "
            + b"OPENSSH "
            + b"PRIVATE KEY-----",
            "private-key-material",
        ),
        (
            b"<key>Host"
            + b"PrivateKey</key>",
            "apple-pairing-private-key",
        ),
        (
            b"<key>UniqueDevice"
            + b"ID</key><string>"
            + (b"a" * 40)
            + b"</string>",
            "apple-device-identifier",
        ),
        (
            b"syn_" + b"admin",
            "legacy-private-nas-user",
        ),
        (
            b"ipod-" + b"test-add",
            "legacy-private-test-path",
        ),
        (
            b"rename-" + b"601",
            "legacy-private-rename-plan",
        ),
    ]

    for payload, rule in fixtures:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixture.bin"
            path.write_bytes(payload)

            require_rule(
                run_scan(path),
                rule,
                secret=payload,
            )


def test_symlink_target_is_scanned_without_following() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        target = (
            "/"
            + "home"
            + "/private-user/"
            + "secret"
        )

        link = root / "external-link"

        os.symlink(
            target,
            link,
        )

        require_rule(
            run_scan(root),
            "linux-user-home-path",
            secret=target.encode(),
        )


def test_tar_members_are_scanned_without_extraction() -> None:
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "source.tar.gz"

        private_value = (
            b"192"
            + b".168.77.88"
        )

        info = tarfile.TarInfo(
            name="nested/metadata.txt"
        )
        info.size = len(private_value)

        with tarfile.open(
            archive,
            mode="w:gz",
        ) as tf:
            tf.addfile(
                info,
                io.BytesIO(private_value),
            )

        require_rule(
            run_scan(archive),
            "private-rfc1918-ipv4",
            secret=private_value,
        )


def test_debian_payload_is_scanned() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        package_root = root / "pkg"
        control = package_root / "DEBIAN"
        payload = package_root / "usr/share/ipod-sync"

        control.mkdir(parents=True)
        payload.mkdir(parents=True)

        (control / "control").write_text(
            "Package: privacy-test\n"
            "Version: 1\n"
            "Architecture: all\n"
            "Maintainer: test <test@example.invalid>\n"
            "Description: privacy scanner fixture\n"
        )

        private_value = (
            b"/"
            + b"home"
            + b"/private-user/device-data"
        )

        (payload / "fixture.txt").write_bytes(
            private_value
        )

        deb = root / "privacy-test.deb"

        subprocess.run(
            [
                "dpkg-deb",
                "--build",
                str(package_root),
                str(deb),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        require_rule(
            run_scan(deb),
            "linux-user-home-path",
            secret=private_value,
        )


def test_pairing_record_filename_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        filename = (
            ("a" * 40)
            + ".plist"
        )

        (root / filename).write_text(
            "synthetic"
        )

        require_rule(
            run_scan(root),
            "apple-pairing-record-filename",
        )


def main() -> None:
    test_clean_placeholders()
    test_content_rules()
    test_symlink_target_is_scanned_without_following()
    test_tar_members_are_scanned_without_extraction()
    test_debian_payload_is_scanned()
    test_pairing_record_filename_is_rejected()

    print("privacy scanner tests: PASS")


if __name__ == "__main__":
    main()
