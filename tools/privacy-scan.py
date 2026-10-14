#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


MAX_ARCHIVE_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 512 * 1024 * 1024

SKIP_DIRECTORY_NAMES = {
    ".git",
}


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[bytes]


@dataclass(frozen=True)
class Finding:
    location: str
    rule: str


class ScanError(RuntimeError):
    pass


def exact_rule(
    name: str,
    value: bytes,
    *,
    flags: int = 0,
) -> Rule:
    return Rule(
        name=name,
        pattern=re.compile(
            re.escape(value),
            flags,
        ),
    )


RULES = [
    Rule(
        "linux-user-home-path",
        re.compile(
            rb"(?<![A-Za-z0-9_.-])/"
            rb"(?:home/[A-Za-z0-9_.-]+|root)/"
        ),
    ),
    Rule(
        "macos-user-home-path",
        re.compile(
            rb"(?<![A-Za-z0-9_.-])/"
            rb"Users/[A-Za-z0-9_.-]+/"
        ),
    ),
    Rule(
        "windows-user-home-path",
        re.compile(
            rb"(?i)(?<![A-Za-z0-9_.-])"
            rb"[A-Z]:\\Users\\[A-Za-z0-9_. -]+\\"
        ),
    ),
    Rule(
        "private-rfc1918-ipv4",
        re.compile(
            rb"(?<![0-9])(?:"
            rb"10(?:\.[0-9]{1,3}){3}"
            rb"|192\.168(?:\.[0-9]{1,3}){2}"
            rb"|172\.(?:1[6-9]|2[0-9]|3[01])"
            rb"(?:\.[0-9]{1,3}){2}"
            rb")(?![0-9])"
        ),
    ),
    Rule(
        "github-classic-token",
        re.compile(
            rb"(?<![A-Za-z0-9_])"
            rb"gh[pousr]_[A-Za-z0-9]{20,255}"
            rb"(?![A-Za-z0-9])"
        ),
    ),
    Rule(
        "github-fine-grained-token",
        re.compile(
            rb"(?<![A-Za-z0-9_])"
            rb"github_pat_[A-Za-z0-9_]{20,255}"
            rb"(?![A-Za-z0-9_])"
        ),
    ),
    Rule(
        "aws-access-key-id",
        re.compile(
            rb"(?<![A-Z0-9])"
            rb"(?:AKIA|ASIA)[A-Z0-9]{16}"
            rb"(?![A-Z0-9])"
        ),
    ),
    Rule(
        "private-key-material",
        re.compile(
            rb"-----BEGIN[ ]+"
            rb"(?:OPENSSH[ ]+|RSA[ ]+|EC[ ]+)?"
            rb"PRIVATE[ ]+KEY-----"
        ),
    ),
    Rule(
        "apple-pairing-private-key",
        re.compile(
            rb"(?i)"
            rb"(?:<key>|[\"'])"
            rb"(?:Host|Root)(?:Private)Key"
            rb"(?:</key>|[\"'])"
        ),
    ),
    Rule(
        "apple-device-identifier",
        re.compile(
            rb"(?is)"
            rb"(?:UniqueDeviceID|UDID)"
            # Pairing records commonly place XML/JSON syntax between the
            # field name and identifier. Bound the gap so this remains a
            # contextual identifier rule rather than a generic SHA-1 match.
            rb".{0,160}?"
            rb"(?:"
            rb"[0-9A-Fa-f]{40}"
            rb"|[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}"
            rb")"
            rb"(?![0-9A-Fa-f])"
        ),
    ),

    # Project-specific fingerprints from private development and migration
    # history. Build these from fragments so the scanner does not match its
    # own source code when the repository itself is scanned.
    exact_rule(
        "legacy-private-nas-user",
        b"syn_" + b"admin",
        flags=re.IGNORECASE,
    ),
    exact_rule(
        "legacy-private-test-path",
        b"ipod-" + b"test-add",
        flags=re.IGNORECASE,
    ),
    exact_rule(
        "legacy-private-rename-plan",
        b"rename-" + b"601",
        flags=re.IGNORECASE,
    ),
    exact_rule(
        "legacy-frozen-preimage",
        b"FROZEN_" + b"PREIMAGE",
    ),
    exact_rule(
        "legacy-frozen-artifact",
        b"FROZEN_" + b"ARTIFACT",
    ),
    exact_rule(
        "legacy-template-fallback",
        b"TEMPLATE_" + b"FALLBACK_PID",
    ),
    exact_rule(
        "private-release-preparation-marker",
        b"public release " + b"preparation kit",
        flags=re.IGNORECASE,
    ),
    exact_rule(
        "private-do-not-upload-marker",
        b"Do not " + b"upload it",
        flags=re.IGNORECASE,
    ),
]


PATH_RULES = [
    Rule(
        "apple-pairing-record-filename",
        re.compile(
            rb"(?i)(?:^|/)[0-9a-f]{40}\.plist$"
        ),
    ),
]


TAR_SUFFIXES = (
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)


def redact_text(value: str) -> str:
    data = value.encode(
        "utf-8",
        errors="surrogateescape",
    )

    for rule in RULES:
        data = rule.pattern.sub(
            b"<redacted>",
            data,
        )

    for rule in PATH_RULES:
        data = rule.pattern.sub(
            b"<redacted-path>",
            data,
        )

    return data.decode(
        "utf-8",
        errors="replace",
    )


class PrivacyScanner:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.files_scanned = 0
        self.archives_scanned = 0

    def add_finding(
        self,
        location: str,
        rule: str,
    ) -> None:
        finding = Finding(
            location=redact_text(location),
            rule=rule,
        )

        if finding not in self.findings:
            self.findings.append(finding)

    def scan_blob(
        self,
        data: bytes,
        location: str,
    ) -> None:
        for rule in RULES:
            if rule.pattern.search(data):
                self.add_finding(
                    location,
                    rule.name,
                )

    def scan_label(
        self,
        label: str,
    ) -> None:
        data = label.encode(
            "utf-8",
            errors="surrogateescape",
        )

        self.scan_blob(
            data,
            f"{label} [path]",
        )

        for rule in PATH_RULES:
            if rule.pattern.search(data):
                self.add_finding(
                    f"{label} [path]",
                    rule.name,
                )

    def scan_regular_file(
        self,
        path: Path,
        label: str,
        *,
        expand_archives: bool = True,
    ) -> None:
        self.scan_label(label)

        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ScanError(
                f"could not read {label}: {exc}"
            ) from exc

        self.files_scanned += 1

        self.scan_blob(
            data,
            label,
        )

        if not expand_archives:
            return

        lower_name = path.name.lower()

        if lower_name.endswith(".deb"):
            self.scan_deb(
                path,
                label,
            )
            return

        if lower_name.endswith(TAR_SUFFIXES):
            self.scan_tar(
                path,
                label,
            )
            return

        if lower_name.endswith(".zip"):
            self.scan_zip(
                path,
                label,
            )

    def scan_node(
        self,
        path: Path,
        label: str,
        *,
        expand_archives: bool = True,
    ) -> None:
        try:
            st = path.lstat()
        except OSError as exc:
            raise ScanError(
                f"could not stat {label}: {exc}"
            ) from exc

        self.scan_label(label)

        if stat.S_ISLNK(st.st_mode):
            try:
                target = os.readlink(path)
            except OSError as exc:
                raise ScanError(
                    f"could not read symlink {label}: {exc}"
                ) from exc

            self.scan_blob(
                target.encode(
                    "utf-8",
                    errors="surrogateescape",
                ),
                f"{label} [symlink-target]",
            )
            return

        if stat.S_ISDIR(st.st_mode):
            try:
                children = sorted(
                    path.iterdir(),
                    key=lambda item: item.name,
                )
            except OSError as exc:
                raise ScanError(
                    f"could not list directory {label}: {exc}"
                ) from exc

            for child in children:
                if child.name in SKIP_DIRECTORY_NAMES:
                    continue

                child_label = (
                    child.name
                    if label == "."
                    else f"{label}/{child.name}"
                )

                self.scan_node(
                    child,
                    child_label,
                    expand_archives=expand_archives,
                )

            return

        if stat.S_ISREG(st.st_mode):
            self.scan_regular_file(
                path,
                label,
                expand_archives=expand_archives,
            )
            return

        # FIFOs, sockets and device nodes contain no normal file payload to
        # inspect. Their path itself has already been scanned above.

    def scan_deb(
        self,
        path: Path,
        label: str,
    ) -> None:
        dpkg_deb = shutil.which("dpkg-deb")

        if dpkg_deb is None:
            raise ScanError(
                "dpkg-deb is required to inspect Debian package contents"
            )

        self.archives_scanned += 1

        with tempfile.TemporaryDirectory(
            prefix="open-ipod-sync-privacy-deb-"
        ) as td:
            root = Path(td)
            payload = root / "payload"
            control = root / "control"

            payload.mkdir()
            control.mkdir()

            for args in (
                [
                    dpkg_deb,
                    "-x",
                    str(path),
                    str(payload),
                ],
                [
                    dpkg_deb,
                    "-e",
                    str(path),
                    str(control),
                ],
            ):
                result = subprocess.run(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                if result.returncode != 0:
                    raise ScanError(
                        f"dpkg-deb inspection failed for {label}"
                    )

            self.scan_node(
                payload,
                f"{label}::payload",
                expand_archives=False,
            )

            self.scan_node(
                control,
                f"{label}::control",
                expand_archives=False,
            )

    def scan_tar(
        self,
        path: Path,
        label: str,
    ) -> None:
        self.archives_scanned += 1
        total = 0

        try:
            archive = tarfile.open(
                path,
                mode="r:*",
            )
        except (OSError, tarfile.TarError) as exc:
            raise ScanError(
                f"could not inspect archive {label}: {exc}"
            ) from exc

        with archive:
            for member in archive:
                member_label = (
                    f"{label}::{member.name}"
                )

                self.scan_label(member_label)

                if member.issym() or member.islnk():
                    self.scan_blob(
                        member.linkname.encode(
                            "utf-8",
                            errors="surrogateescape",
                        ),
                        f"{member_label} [link-target]",
                    )
                    continue

                if not member.isfile():
                    continue

                if member.size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ScanError(
                        f"archive member exceeds privacy-scan "
                        f"size limit in {label}"
                    )

                total += member.size

                if total > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ScanError(
                        f"archive expanded content exceeds "
                        f"privacy-scan size limit in {label}"
                    )

                stream = archive.extractfile(member)

                if stream is None:
                    raise ScanError(
                        f"could not read archive member in {label}"
                    )

                data = stream.read()

                self.files_scanned += 1

                self.scan_blob(
                    data,
                    member_label,
                )

    def scan_zip(
        self,
        path: Path,
        label: str,
    ) -> None:
        self.archives_scanned += 1
        total = 0

        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise ScanError(
                f"could not inspect archive {label}: {exc}"
            ) from exc

        with archive:
            for info in archive.infolist():
                member_label = (
                    f"{label}::{info.filename}"
                )

                self.scan_label(member_label)

                if info.is_dir():
                    continue

                if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ScanError(
                        f"archive member exceeds privacy-scan "
                        f"size limit in {label}"
                    )

                total += info.file_size

                if total > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ScanError(
                        f"archive expanded content exceeds "
                        f"privacy-scan size limit in {label}"
                    )

                try:
                    data = archive.read(info)
                except (
                    OSError,
                    RuntimeError,
                    zipfile.BadZipFile,
                ) as exc:
                    raise ScanError(
                        f"could not read archive member in {label}"
                    ) from exc

                self.files_scanned += 1

                self.scan_blob(
                    data,
                    member_label,
                )

    def scan_input(
        self,
        raw: str,
    ) -> None:
        path = Path(raw)

        if not path.exists() and not path.is_symlink():
            raise ScanError(
                f"scan input does not exist: {raw}"
            )

        label = (
            "."
            if raw == "."
            else path.name
        )

        self.scan_node(
            path,
            label,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fail closed when public source or generated artifacts contain "
            "private/development fingerprints, credentials, device identity "
            "material, or other prohibited data."
        )
    )

    parser.add_argument(
        "paths",
        nargs="+",
        help=(
            "Files or directories to scan. Debian packages and supported "
            "tar/zip archives are inspected both as raw bytes and by member."
        ),
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scanner = PrivacyScanner()

    try:
        for raw in args.paths:
            scanner.scan_input(raw)
    except ScanError as exc:
        print(
            "ERROR: privacy scan could not complete: "
            + redact_text(str(exc)),
            file=sys.stderr,
        )
        return 2

    if scanner.findings:
        print(
            "privacy scan: FAIL",
            file=sys.stderr,
        )

        for finding in sorted(
            scanner.findings,
            key=lambda item: (
                item.location,
                item.rule,
            ),
        ):
            print(
                f"  - {finding.location}: "
                f"rule={finding.rule}",
                file=sys.stderr,
            )

        print(
            "ERROR: prohibited private/development data found",
            file=sys.stderr,
        )

        return 1

    print(
        "privacy scan: PASS "
        f"(files={scanner.files_scanned}, "
        f"archives={scanner.archives_scanned})"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
