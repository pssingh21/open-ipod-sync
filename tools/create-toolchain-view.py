#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any


SCHEMA = "open-ipod-sync-toolchain-view-v1"

SYSTEM_PATH = (
    "/usr/bin:"
    "/bin:"
    "/usr/sbin:"
    "/sbin"
)

ALLOWED_COMMANDS = (
    "ar",
    "as",
    "awk",
    "basename",
    "bash",
    "cat",
    "cc",
    "chmod",
    "cmp",
    "cp",
    "cpp",
    "cut",
    "date",
    "diff",
    "dirname",
    "dpkg",
    "dpkg-deb",
    "dpkg-query",
    "dpkg-shlibdeps",
    "env",
    "expr",
    "file",
    "find",
    "g++",
    "gcc",
    "gcc-ar",
    "gcc-nm",
    "gcc-ranlib",
    "getconf",
    "gettext",
    "grep",
    "gzip",
    "head",
    "id",
    "install",
    "intltool-update",
    "intltool-extract",
    "intltool-merge",
    "ld",
    "locale",
    "ln",
    "ls",
    "m4",
    "make",
    "mkdir",
    "mktemp",
    "msgattrib",
    "msgcat",
    "msgfmt",
    "msgmerge",
    "mv",
    "nm",
    "objcopy",
    "objdump",
    "od",
    "perl",
    "pkg-config",
    "printf",
    "python3",
    "ranlib",
    "readelf",
    "readlink",
    "realpath",
    "rm",
    "rmdir",
    "sed",
    "sha256sum",
    "sh",
    "sleep",
    "sort",
    "stat",
    "strings",
    "strip",
    "tail",
    "tar",
    "tee",
    "test",
    "touch",
    "tr",
    "uname",
    "uniq",
    "wc",
    "xargs",
    "xgettext",
    "xz",
)

REQUIRED_COMMANDS = {
    "ar",
    "as",
    "awk",
    "basename",
    "bash",
    "cat",
    "chmod",
    "cp",
    "date",
    "dirname",
    "dpkg",
    "dpkg-deb",
    "dpkg-query",
    "dpkg-shlibdeps",
    "env",
    "file",
    "find",
    "g++",
    "gcc",
    "grep",
    "install",
    "intltool-update",
    "intltool-extract",
    "intltool-merge",
    "ld",
    "ln",
    "make",
    "mkdir",
    "mktemp",
    "msgfmt",
    "mv",
    "perl",
    "pkg-config",
    "python3",
    "ranlib",
    "readelf",
    "readlink",
    "rm",
    "rmdir",
    "sed",
    "sha256sum",
    "sh",
    "sleep",
    "sort",
    "stat",
    "strip",
    "tar",
    "touch",
    "tr",
    "uname",
}

ALLOWED_REAL_ROOTS = (
    Path("/usr/bin"),
    Path("/usr/sbin"),
    Path("/bin"),
    Path("/sbin"),
)


def clean_env() -> dict[str, str]:
    return {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": SYSTEM_PATH,
        "TZ": "UTC",
    }


def run_text(argv: list[str]) -> str:
    proc = subprocess.run(
        argv,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=clean_env(),
    )

    text = proc.stdout.strip()

    if proc.returncode != 0:
        raise RuntimeError(
            "command failed "
            f"(rc={proc.returncode}): {argv!r}\n{text}"
        )

    return text


def under_allowed_root(path: Path) -> bool:
    for root in ALLOWED_REAL_ROOTS:
        try:
            path.relative_to(
                root.resolve()
            )
        except ValueError:
            continue

        return True

    return False


def debian_path_aliases(
    path: Path,
) -> list[Path]:
    """
    Return package-database path aliases for merged-/usr layouts.

    Debian package metadata may record /bin/foo while runtime resolution on a
    usr-merged filesystem produces /usr/bin/foo, or vice versa. The same
    applies to /sbin and /usr/sbin.

    These are filesystem-layout aliases only. They do not broaden the allowed
    executable roots.
    """

    text = str(path)

    aliases = [path]

    mappings = (
        ("/usr/bin/", "/bin/"),
        ("/bin/", "/usr/bin/"),
        ("/usr/sbin/", "/sbin/"),
        ("/sbin/", "/usr/sbin/"),
    )

    for source, target in mappings:
        if text.startswith(source):
            aliases.append(
                Path(
                    target
                    + text[len(source):]
                )
            )

    result: list[Path] = []

    for candidate in aliases:
        if candidate not in result:
            result.append(candidate)

    return result


def package_owner(path: Path) -> tuple[str, str]:
    owners: set[str] = set()

    for candidate in debian_path_aliases(
        path
    ):
        proc = subprocess.run(
            [
                "dpkg-query",
                "-S",
                str(candidate),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=clean_env(),
        )

        if proc.returncode != 0:
            continue

        for raw in proc.stdout.splitlines():
            if ": " not in raw:
                continue

            package, owned_path = raw.rsplit(
                ": ",
                1,
            )

            if Path(owned_path) != candidate:
                continue

            package = package.strip()

            if package:
                owners.add(package)

    candidates = sorted(
        owners
    )

    if len(candidates) != 1:
        aliases = ", ".join(
            str(candidate)
            for candidate in debian_path_aliases(path)
        )

        raise RuntimeError(
            "expected exactly one Debian package "
            f"owner for {path}; "
            f"aliases=[{aliases}]; "
            f"owners={candidates!r}"
        )

    package = candidates[0]

    version = run_text(
        [
            "dpkg-query",
            "-W",
            "-f=${Version}",
            package,
        ]
    )

    if not version:
        raise RuntimeError(
            f"empty package version for {package}"
        )

    return package, version


def resolve_command(
    command: str,
) -> dict[str, str] | None:
    found = shutil.which(
        command,
        path=SYSTEM_PATH,
    )

    if found is None:
        if command in REQUIRED_COMMANDS:
            raise RuntimeError(
                f"required tool is unavailable: {command}"
            )

        return None

    lexical = Path(found)

    try:
        resolved = lexical.resolve(
            strict=True
        )
    except OSError as exc:
        raise RuntimeError(
            f"could not resolve tool {command}: {exc}"
        )

    if not under_allowed_root(resolved):
        raise RuntimeError(
            f"tool {command} resolves outside declared "
            f"system executable roots: {resolved}"
        )

    st = resolved.stat()

    if not stat.S_ISREG(st.st_mode):
        raise RuntimeError(
            f"tool is not a regular file: "
            f"{command} -> {resolved}"
        )

    if not os.access(
        resolved,
        os.X_OK,
    ):
        raise RuntimeError(
            f"tool is not executable: "
            f"{command} -> {resolved}"
        )

    package, version = package_owner(
        resolved
    )

    return {
        "command": command,
        "package": package,
        "package_version": version,
        "target": str(resolved),
    }


def create_view(
    output_dir: Path,
) -> list[dict[str, str]]:
    output_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    records: list[dict[str, str]] = []

    for command in sorted(
        ALLOWED_COMMANDS
    ):
        record = resolve_command(
            command
        )

        if record is None:
            continue

        link = output_dir / command

        link.symlink_to(
            record["target"]
        )

        records.append(
            record
        )

    commands = {
        record["command"]
        for record in records
    }

    missing = sorted(
        REQUIRED_COMMANDS - commands
    )

    if missing:
        raise RuntimeError(
            "required commands missing from toolchain view: "
            f"{missing}"
        )

    return records


def write_manifest(
    path: Path,
    records: list[dict[str, str]],
) -> None:
    document: dict[str, Any] = {
        "commands": records,
        "policy": {
            "ambient_path_used": False,
            "allowed_real_roots": [
                "/bin",
                "/sbin",
                "/usr/bin",
                "/usr/sbin",
            ],
            "developer_local_roots_allowed": False,
        },
        "schema": SCHEMA,
    }

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
        "--output-dir",
        type=Path,
        required=True,
    )

    ap.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )

    args = ap.parse_args()

    output_dir = (
        args.output_dir.resolve()
    )

    if output_dir.exists():
        raise SystemExit(
            "ERROR: toolchain output directory "
            f"already exists: {output_dir}"
        )

    try:
        records = create_view(
            output_dir
        )

        write_manifest(
            args.manifest,
            records,
        )
    except (
        OSError,
        RuntimeError,
    ) as exc:
        shutil.rmtree(
            output_dir,
            ignore_errors=True,
        )

        raise SystemExit(
            f"ERROR: could not create "
            f"declared toolchain view: {exc}"
        )

    print(
        "toolchain view: "
        f"{output_dir}"
    )

    print(
        "toolchain manifest: "
        f"{args.manifest}"
    )

    print(
        "declared commands: "
        f"{len(records)}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
