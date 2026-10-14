#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


SCHEMA = "open-ipod-sync-build-materials-v1"

BUILD_PACKAGES = (
    "bash",
    "binutils",
    "build-essential",
    "ca-certificates",
    "dpkg-dev",
    "g++",
    "gcc",
    "gettext",
    "git",
    "intltool",
    "libc6",
    "libc6-dev",
    "libglib2.0-dev",
    "libimobiledevice-dev",
    "libplist-dev",
    "libsqlite3-dev",
    "libusb-1.0-0-dev",
    "libxml2-dev",
    "make",
    "pkg-config",
    "python3",
    "zlib1g-dev",
)

REQUIRED_PKG_CONFIG_MODULES = (
    "glib-2.0",
    "gobject-2.0",
    "sqlite3",
    "libimobiledevice-1.0",
    "libxml-2.0",
)

TOOL_COMMANDS = {
    "ar": ("ar", "--version"),
    "dpkg-deb": ("dpkg-deb", "--version"),
    "g++": ("g++", "-dumpfullversion", "-dumpversion"),
    "gcc": ("gcc", "-dumpfullversion", "-dumpversion"),
    "intltool-update": ("intltool-update", "--version"),
    "ld": ("ld", "--version"),
    "make": ("make", "--version"),
    "msgfmt": ("msgfmt", "--version"),
    "pkg-config": ("pkg-config", "--version"),
    "python3": ("python3", "--version"),
    "strip": ("strip", "--version"),
}


def canonical_env() -> dict[str, str]:
    env = dict(os.environ)

    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["TZ"] = "UTC"

    return env


def run_text(argv: list[str]) -> str:
    proc = subprocess.run(
        argv,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=canonical_env(),
    )

    text = proc.stdout.strip()

    if proc.returncode != 0:
        raise RuntimeError(
            "command failed "
            f"(rc={proc.returncode}): {argv!r}\n{text}"
        )

    if not text:
        raise RuntimeError(
            f"command returned empty output: {argv!r}"
        )

    return text


def first_line(argv: list[str]) -> str:
    return run_text(argv).splitlines()[0].strip()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def package_materials() -> list[dict[str, str]]:
    fmt = (
        "${binary:Package}"
        "\t${Version}"
        "\t${Architecture}"
        "\n"
    )

    output = run_text(
        [
            "dpkg-query",
            "-W",
            f"-f={fmt}",
            *BUILD_PACKAGES,
        ]
    )

    records: list[dict[str, str]] = []

    for line in output.splitlines():
        parts = line.split("\t")

        if len(parts) != 3:
            raise RuntimeError(
                f"unexpected dpkg-query record: {line!r}"
            )

        name, version, architecture = (
            item.strip()
            for item in parts
        )

        if not name or not version or not architecture:
            raise RuntimeError(
                f"incomplete dpkg-query record: {line!r}"
            )

        records.append(
            {
                "architecture": architecture,
                "name": name,
                "version": version,
            }
        )

    records.sort(
        key=lambda record: (
            record["name"],
            record["architecture"],
            record["version"],
        )
    )

    if len(records) != len(BUILD_PACKAGES):
        raise RuntimeError(
            "unexpected build-package count: "
            f"expected={len(BUILD_PACKAGES)} "
            f"actual={len(records)}"
        )

    return records


def pkg_config_materials() -> list[dict[str, str]]:
    modules = list(
        REQUIRED_PKG_CONFIG_MODULES
    )

    if subprocess.run(
        ["pkg-config", "--exists", "libplist"],
        check=False,
        env=canonical_env(),
    ).returncode == 0:
        plist_module = "libplist"
    elif subprocess.run(
        ["pkg-config", "--exists", "libplist-2.0"],
        check=False,
        env=canonical_env(),
    ).returncode == 0:
        plist_module = "libplist-2.0"
    else:
        raise RuntimeError(
            "no supported libplist pkg-config module"
        )

    modules.append(plist_module)

    result: list[dict[str, str]] = []

    for module in sorted(modules):
        version = run_text(
            [
                "pkg-config",
                "--modversion",
                module,
            ]
        )

        result.append(
            {
                "module": module,
                "version": version,
            }
        )

    return result


def tool_materials() -> dict[str, str]:
    result: dict[str, str] = {}

    for name in sorted(TOOL_COMMANDS):
        result[name] = first_line(
            list(TOOL_COMMANDS[name])
        )

    return result


def validate_sha256(
    value: str,
    label: str,
) -> None:
    if not re.fullmatch(
        r"[0-9a-f]{64}",
        value,
    ):
        raise ValueError(
            f"{label} must be a lowercase SHA-256 digest"
        )


def validate_commit(value: str) -> None:
    if not re.fullmatch(
        r"[0-9a-f]{40}",
        value,
    ):
        raise ValueError(
            "source commit must be a full lowercase "
            "40-character SHA-1"
        )


def build_document(
    *,
    source_archive: Path,
    source_commit: str,
    source_date_epoch: int,
    snapshot_identity: str,
    base_image_identity: str,
) -> dict[str, Any]:
    validate_commit(source_commit)

    if source_date_epoch < 0:
        raise ValueError(
            "source date epoch must be non-negative"
        )

    if not snapshot_identity.strip():
        raise ValueError(
            "snapshot identity must not be empty"
        )

    if not base_image_identity.strip():
        raise ValueError(
            "base-image identity must not be empty"
        )

    archive_digest = file_sha256(
        source_archive
    )

    validate_sha256(
        archive_digest,
        "source archive digest",
    )

    architecture = run_text(
        ["dpkg", "--print-architecture"]
    )

    debian_version = (
        Path("/etc/debian_version")
        .read_text()
        .strip()
    )

    if not debian_version:
        raise RuntimeError(
            "/etc/debian_version is empty"
        )

    return {
        "declared_environment": {
            "base_image_identity": (
                base_image_identity
            ),
            "snapshot_identity": (
                snapshot_identity
            ),
        },
        "observed_environment": {
            "architecture": architecture,
            "build_packages": (
                package_materials()
            ),
            "debian_version": debian_version,
            "pkg_config_modules": (
                pkg_config_materials()
            ),
            "tools": tool_materials(),
        },
        "schema": SCHEMA,
        "source": {
            "archive_sha256": (
                archive_digest
            ),
            "commit": source_commit,
            "source_date_epoch": (
                source_date_epoch
            ),
        },
    }


def write_document(
    path: Path,
    document: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            document,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--source-archive",
        type=Path,
        required=True,
    )

    ap.add_argument(
        "--source-commit",
        required=True,
    )

    ap.add_argument(
        "--source-date-epoch",
        type=int,
        required=True,
    )

    ap.add_argument(
        "--snapshot-identity",
        required=True,
    )

    ap.add_argument(
        "--base-image-identity",
        required=True,
    )

    ap.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    args = ap.parse_args()

    source_archive = (
        args.source_archive.resolve()
    )

    if not source_archive.is_file():
        raise SystemExit(
            "ERROR: source archive does not exist: "
            f"{source_archive}"
        )

    try:
        document = build_document(
            source_archive=source_archive,
            source_commit=args.source_commit,
            source_date_epoch=(
                args.source_date_epoch
            ),
            snapshot_identity=(
                args.snapshot_identity
            ),
            base_image_identity=(
                args.base_image_identity
            ),
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise SystemExit(
            f"ERROR: could not generate "
            f"build-materials manifest: {exc}"
        )

    write_document(
        args.output,
        document,
    )

    print(
        "build materials: "
        f"{args.output}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
