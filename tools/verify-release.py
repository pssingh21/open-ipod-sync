#!/usr/bin/env python3

"""
Offline verifier for an open-ipod-sync GitHub Release directory.

This verifier intentionally does not trust the CI workspace that produced the
release. It verifies only the bytes supplied in a downloaded release directory
and the cross-links encoded by those bytes.

GitHub release / attestation authenticity is a separate verification layer and
can be performed after this local verification succeeds.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


BUILD_MATERIALS_SCHEMA = (
    "open-ipod-sync-build-materials-v1"
)

TOOLCHAIN_SCHEMA = (
    "open-ipod-sync-toolchain-view-v1"
)

PROVENANCE_SCHEMA = (
    "open-ipod-sync-provenance-v1"
)

SOURCE_RE = re.compile(
    r"^open-ipod-sync-"
    r"([0-9a-f]{40})"
    r"-source\.tar$"
)

DEB_RE = re.compile(
    r"^ipod-sync_.+_amd64\.deb$"
)

SPDX_RE = re.compile(
    r"^ipod-sync_.+_amd64\.spdx\.json$"
)

SHA256_RE = re.compile(
    r"^[0-9a-f]{64}$"
)

CHECKSUM_LINE_RE = re.compile(
    r"^([0-9a-f]{64})  "
    r"([A-Za-z0-9][A-Za-z0-9._+~:-]*)$"
)

REPOSITORY_SLUG_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/"
    r"[A-Za-z0-9_.-]+$"
)

RELEASE_TAG_RE = re.compile(
    r"^[A-Za-z0-9]"
    r"[A-Za-z0-9._+-]{0,127}$"
)


class VerifyError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise VerifyError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def read_json(path: Path) -> Any:
    def reject_duplicates(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}

        for key, value in pairs:
            if key in result:
                fail(
                    f"{path.name}: duplicate JSON key: {key}"
                )

            result[key] = value

        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )

    except VerifyError:
        raise

    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        fail(
            f"{path.name}: invalid JSON: {exc}"
        )


def require_dict(
    value: Any,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label}: expected object")

    return value


def require_list(
    value: Any,
    label: str,
) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{label}: expected array")

    return value


def require_string(
    value: Any,
    label: str,
) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{label}: expected non-empty string")

    return value


def require_sha256(
    value: Any,
    label: str,
) -> str:
    text = require_string(
        value,
        label,
    )

    if not SHA256_RE.fullmatch(text):
        fail(
            f"{label}: invalid SHA-256"
        )

    return text


def require_keys(
    obj: dict[str, Any],
    keys: set[str],
    label: str,
) -> None:
    missing = keys - set(obj)

    if missing:
        fail(
            f"{label}: missing keys: "
            f"{sorted(missing)}"
        )


def exact_keys(
    obj: dict[str, Any],
    keys: set[str],
    label: str,
) -> None:
    actual = set(obj)

    if actual != keys:
        fail(
            f"{label}: unexpected object shape; "
            f"expected={sorted(keys)} "
            f"actual={sorted(actual)}"
        )


def parse_checksums(
    path: Path,
) -> dict[str, str]:
    try:
        lines = path.read_text(
            encoding="utf-8"
        ).splitlines()

    except (
        OSError,
        UnicodeDecodeError,
    ) as exc:
        fail(
            f"{path.name}: cannot read checksum manifest: {exc}"
        )

    if not lines:
        fail(
            f"{path.name}: empty checksum manifest"
        )

    result: dict[str, str] = {}

    for lineno, line in enumerate(
        lines,
        1,
    ):
        match = CHECKSUM_LINE_RE.fullmatch(
            line
        )

        if not match:
            fail(
                f"{path.name}:{lineno}: "
                "non-canonical checksum line"
            )

        digest, name = match.groups()

        if (
            name in {".", ".."}
            or "/" in name
            or "\\" in name
        ):
            fail(
                f"{path.name}:{lineno}: "
                f"unsafe filename: {name!r}"
            )

        if name in result:
            fail(
                f"{path.name}:{lineno}: "
                f"duplicate filename: {name}"
            )

        result[name] = digest

    return result


def discover_assets(
    root: Path,
) -> dict[str, Any]:
    if not root.is_dir():
        fail(
            f"release directory does not exist: {root}"
        )

    names: list[str] = []

    for entry in root.iterdir():
        if entry.is_symlink():
            fail(
                f"release asset must not be a symlink: "
                f"{entry.name}"
            )

        if not entry.is_file():
            fail(
                f"unexpected non-file in release directory: "
                f"{entry.name}"
            )

        names.append(entry.name)

    names.sort()

    sources = [
        name
        for name in names
        if SOURCE_RE.fullmatch(name)
    ]

    debs = [
        name
        for name in names
        if DEB_RE.fullmatch(name)
    ]

    spdxs = [
        name
        for name in names
        if SPDX_RE.fullmatch(name)
    ]

    if len(sources) != 1:
        fail(
            "expected exactly one deterministic "
            f"source archive; found {sources}"
        )

    if len(debs) != 1:
        fail(
            "expected exactly one Debian package; "
            f"found {debs}"
        )

    if len(spdxs) != 1:
        fail(
            "expected exactly one SPDX SBOM; "
            f"found {spdxs}"
        )

    source_name = sources[0]
    deb_name = debs[0]
    spdx_name = spdxs[0]

    expected_spdx = (
        deb_name.removesuffix(".deb")
        + ".spdx.json"
    )

    if spdx_name != expected_spdx:
        fail(
            "public Debian/SBOM filenames disagree: "
            f"{deb_name} vs {spdx_name}"
        )

    source_match = SOURCE_RE.fullmatch(
        source_name
    )

    assert source_match is not None

    commit = source_match.group(1)

    fixed = {
        "BUILD-MATERIALS.json",
        "CI-SHA256SUMS",
        "PROVENANCE.json",
        "SHA256SUMS",
        "TOOLCHAIN.json",
    }

    expected = (
        fixed
        | {
            source_name,
            deb_name,
            spdx_name,
        }
    )

    actual = set(names)

    if actual != expected:
        fail(
            "release asset set mismatch; "
            f"expected={sorted(expected)} "
            f"actual={sorted(actual)}"
        )

    if len(actual) != 8:
        fail(
            "release must contain exactly eight files"
        )

    return {
        "commit": commit,
        "deb": root / deb_name,
        "deb_name": deb_name,
        "spdx": root / spdx_name,
        "spdx_name": spdx_name,
        "source": root / source_name,
        "source_name": source_name,
    }


def verify_release_checksums(
    root: Path,
    assets: dict[str, Any],
) -> dict[str, str]:
    manifest = parse_checksums(
        root / "SHA256SUMS"
    )

    expected = {
        name
        for name in (
            "BUILD-MATERIALS.json",
            "CI-SHA256SUMS",
            "PROVENANCE.json",
            "TOOLCHAIN.json",
            assets["source_name"],
            assets["deb_name"],
            assets["spdx_name"],
        )
    }

    if set(manifest) != expected:
        fail(
            "SHA256SUMS payload set mismatch; "
            f"expected={sorted(expected)} "
            f"actual={sorted(manifest)}"
        )

    if len(manifest) != 7:
        fail(
            "SHA256SUMS must contain exactly "
            "seven payload entries"
        )

    for name, expected_digest in manifest.items():
        actual_digest = sha256_file(
            root / name
        )

        if actual_digest != expected_digest:
            fail(
                f"SHA256SUMS mismatch for {name}: "
                f"expected={expected_digest} "
                f"actual={actual_digest}"
            )

    return manifest


def verify_source_archive(
    path: Path,
    *,
    expected_commit: str,
    expected_epoch: int,
) -> None:
    try:
        with tarfile.open(
            path,
            mode="r:*",
        ) as tf:
            embedded = tf.pax_headers.get(
                "comment"
            )

            if embedded != expected_commit:
                fail(
                    "source archive embedded commit mismatch; "
                    f"expected={expected_commit} "
                    f"actual={embedded!r}"
                )

            members = tf.getmembers()

    except (
        tarfile.TarError,
        OSError,
    ) as exc:
        fail(
            f"invalid source archive: {exc}"
        )

    if not members:
        fail(
            "source archive contains no members"
        )

    prefix = (
        f"open-ipod-sync-{expected_commit}/"
    )

    root_name = prefix.rstrip("/")

    for member in members:
        name = member.name

        if name == root_name:
            if not member.isdir():
                fail(
                    "source archive canonical root "
                    "must be a directory"
                )

            rel = ""

        elif name.startswith(prefix):
            rel = name[len(prefix):]

        else:
            fail(
                "source archive member outside "
                f"canonical prefix: {name}"
            )

        if rel:
            pure = PurePosixPath(rel)

            if (
                pure.is_absolute()
                or ".." in pure.parts
                or ".git" in pure.parts
            ):
                fail(
                    "unsafe source archive member: "
                    f"{name}"
                )

        if member.mtime != expected_epoch:
            fail(
                "source archive member timestamp mismatch: "
                f"{name}: expected={expected_epoch} "
                f"actual={member.mtime}"
            )

        if member.issym() or member.islnk():
            target = PurePosixPath(
                member.linkname
            )

            if (
                target.is_absolute()
                or ".." in target.parts
            ):
                fail(
                    "unsafe source archive link target: "
                    f"{name} -> {member.linkname}"
                )


def verify_build_materials(
    root: Path,
    assets: dict[str, Any],
) -> dict[str, Any]:
    path = root / "BUILD-MATERIALS.json"

    doc = require_dict(
        read_json(path),
        "BUILD-MATERIALS.json",
    )

    exact_keys(
        doc,
        {
            "declared_environment",
            "observed_environment",
            "schema",
            "source",
        },
        "BUILD-MATERIALS.json",
    )

    if doc["schema"] != BUILD_MATERIALS_SCHEMA:
        fail(
            "unsupported BUILD-MATERIALS schema: "
            f"{doc['schema']!r}"
        )

    declared = require_dict(
        doc["declared_environment"],
        "BUILD-MATERIALS.declared_environment",
    )

    exact_keys(
        declared,
        {
            "base_image_identity",
            "snapshot_identity",
        },
        "BUILD-MATERIALS.declared_environment",
    )

    snapshot = require_string(
        declared["snapshot_identity"],
        "snapshot identity",
    )

    base_image = require_string(
        declared["base_image_identity"],
        "base-image identity",
    )

    if not re.fullmatch(
        r"debian:11@sha256:[0-9a-f]{64}",
        base_image,
    ):
        fail(
            "unexpected Debian base-image identity: "
            f"{base_image}"
        )

    source = require_dict(
        doc["source"],
        "BUILD-MATERIALS.source",
    )

    exact_keys(
        source,
        {
            "archive_sha256",
            "commit",
            "source_date_epoch",
        },
        "BUILD-MATERIALS.source",
    )

    source_commit = require_string(
        source["commit"],
        "BUILD-MATERIALS source commit",
    )

    if source_commit != assets["commit"]:
        fail(
            "build-material source commit mismatch; "
            f"filename={assets['commit']} "
            f"materials={source_commit}"
        )

    epoch = source["source_date_epoch"]

    if (
        not isinstance(epoch, int)
        or isinstance(epoch, bool)
        or epoch < 0
    ):
        fail(
            "BUILD-MATERIALS source_date_epoch "
            "must be a non-negative integer"
        )

    archive_digest = require_sha256(
        source["archive_sha256"],
        "BUILD-MATERIALS source archive SHA-256",
    )

    actual_archive_digest = sha256_file(
        assets["source"]
    )

    if archive_digest != actual_archive_digest:
        fail(
            "BUILD-MATERIALS source archive digest mismatch"
        )

    observed = require_dict(
        doc["observed_environment"],
        "BUILD-MATERIALS.observed_environment",
    )

    exact_keys(
        observed,
        {
            "architecture",
            "build_packages",
            "debian_version",
            "pkg_config_modules",
            "tools",
        },
        "BUILD-MATERIALS.observed_environment",
    )

    architecture = require_string(
        observed["architecture"],
        "observed architecture",
    )

    if architecture != "amd64":
        fail(
            "unexpected observed build architecture: "
            f"{architecture}"
        )

    require_string(
        observed["debian_version"],
        "observed Debian version",
    )

    packages = require_list(
        observed["build_packages"],
        "observed build packages",
    )

    if not packages:
        fail(
            "observed build package set is empty"
        )

    seen_packages: set[tuple[str, str]] = set()

    for index, item in enumerate(packages):
        record = require_dict(
            item,
            f"build_packages[{index}]",
        )

        exact_keys(
            record,
            {
                "architecture",
                "name",
                "version",
            },
            f"build_packages[{index}]",
        )

        name = require_string(
            record["name"],
            f"build_packages[{index}].name",
        )

        arch = require_string(
            record["architecture"],
            f"build_packages[{index}].architecture",
        )

        require_string(
            record["version"],
            f"build_packages[{index}].version",
        )

        identity = (
            name,
            arch,
        )

        if identity in seen_packages:
            fail(
                "duplicate build package identity: "
                f"{identity}"
            )

        seen_packages.add(identity)

    modules = require_list(
        observed["pkg_config_modules"],
        "pkg-config modules",
    )

    if not modules:
        fail(
            "pkg-config module evidence is empty"
        )

    for index, item in enumerate(modules):
        record = require_dict(
            item,
            f"pkg_config_modules[{index}]",
        )

        exact_keys(
            record,
            {
                "module",
                "version",
            },
            f"pkg_config_modules[{index}]",
        )

        require_string(
            record["module"],
            f"pkg_config_modules[{index}].module",
        )

        require_string(
            record["version"],
            f"pkg_config_modules[{index}].version",
        )

    tools = require_dict(
        observed["tools"],
        "observed tools",
    )

    if not tools:
        fail(
            "observed tool evidence is empty"
        )

    for command, version in tools.items():
        require_string(
            command,
            "observed tool command",
        )

        require_string(
            version,
            f"observed tool {command}",
        )

    verify_source_archive(
        assets["source"],
        expected_commit=source_commit,
        expected_epoch=epoch,
    )

    return doc


def path_under_root(
    path: str,
    root: str,
) -> bool:
    path_obj = PurePosixPath(path)
    root_obj = PurePosixPath(root)

    try:
        path_obj.relative_to(root_obj)
        return True

    except ValueError:
        return False


def verify_toolchain(
    root: Path,
    materials: dict[str, Any],
) -> dict[str, Any]:
    doc = require_dict(
        read_json(
            root / "TOOLCHAIN.json"
        ),
        "TOOLCHAIN.json",
    )

    exact_keys(
        doc,
        {
            "commands",
            "policy",
            "schema",
        },
        "TOOLCHAIN.json",
    )

    if doc["schema"] != TOOLCHAIN_SCHEMA:
        fail(
            "unsupported TOOLCHAIN schema: "
            f"{doc['schema']!r}"
        )

    policy = require_dict(
        doc["policy"],
        "TOOLCHAIN.policy",
    )

    exact_keys(
        policy,
        {
            "allowed_real_roots",
            "ambient_path_used",
            "developer_local_roots_allowed",
        },
        "TOOLCHAIN.policy",
    )

    if policy["ambient_path_used"] is not False:
        fail(
            "TOOLCHAIN policy permits ambient PATH"
        )

    if (
        policy["developer_local_roots_allowed"]
        is not False
    ):
        fail(
            "TOOLCHAIN policy permits developer-local roots"
        )

    roots = require_list(
        policy["allowed_real_roots"],
        "TOOLCHAIN allowed roots",
    )

    if not roots:
        fail(
            "TOOLCHAIN allowed root set is empty"
        )

    allowed_roots: list[str] = []

    for index, value in enumerate(roots):
        root_path = require_string(
            value,
            f"allowed_real_roots[{index}]",
        )

        pure = PurePosixPath(
            root_path
        )

        if (
            not pure.is_absolute()
            or ".." in pure.parts
        ):
            fail(
                "unsafe toolchain allowed root: "
                f"{root_path}"
            )

        allowed_roots.append(
            str(pure)
        )

    if len(set(allowed_roots)) != len(
        allowed_roots
    ):
        fail(
            "duplicate toolchain allowed roots"
        )

    commands = require_list(
        doc["commands"],
        "TOOLCHAIN commands",
    )

    if not commands:
        fail(
            "TOOLCHAIN command set is empty"
        )

    command_names: list[str] = []

    for index, item in enumerate(commands):
        record = require_dict(
            item,
            f"TOOLCHAIN.commands[{index}]",
        )

        exact_keys(
            record,
            {
                "command",
                "package",
                "package_version",
                "target",
            },
            f"TOOLCHAIN.commands[{index}]",
        )

        command = require_string(
            record["command"],
            f"TOOLCHAIN.commands[{index}].command",
        )

        require_string(
            record["package"],
            f"TOOLCHAIN.commands[{index}].package",
        )

        require_string(
            record["package_version"],
            f"TOOLCHAIN.commands[{index}].package_version",
        )

        target = require_string(
            record["target"],
            f"TOOLCHAIN.commands[{index}].target",
        )

        target_path = PurePosixPath(
            target
        )

        if (
            not target_path.is_absolute()
            or ".." in target_path.parts
        ):
            fail(
                f"unsafe toolchain target: {target}"
            )

        if not any(
            path_under_root(
                target,
                allowed,
            )
            for allowed in allowed_roots
        ):
            fail(
                "toolchain target outside declared roots: "
                f"{target}"
            )

        command_names.append(
            command
        )

    if len(set(command_names)) != len(
        command_names
    ):
        fail(
            "duplicate command in TOOLCHAIN.json"
        )

    if command_names != sorted(
        command_names
    ):
        fail(
            "TOOLCHAIN commands are not canonical/sorted"
        )

    observed_tools = set(
        require_dict(
            materials["observed_environment"]["tools"],
            "BUILD-MATERIALS observed tools",
        )
    )

    missing = (
        observed_tools
        - set(command_names)
    )

    if missing:
        fail(
            "BUILD-MATERIALS tools absent from "
            f"TOOLCHAIN.json: {sorted(missing)}"
        )

    return doc


def deb_field(
    deb: Path,
    field: str,
) -> str:
    if shutil.which(
        "dpkg-deb"
    ) is None:
        fail(
            "required command is unavailable: dpkg-deb"
        )

    proc = subprocess.run(
        [
            "dpkg-deb",
            "-f",
            str(deb),
            field,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if proc.returncode != 0:
        fail(
            f"dpkg-deb failed reading {field}: "
            f"{proc.stderr.strip()}"
        )

    value = proc.stdout.strip()

    if not value:
        fail(
            f"Debian package field is empty: {field}"
        )

    return value


def verify_packaged_artifacts(
    deb: Path,
    records: Any,
) -> None:
    artifacts = require_list(
        records,
        "PROVENANCE.packaged_artifacts",
    )

    if not artifacts:
        fail(
            "PROVENANCE packaged-artifact set is empty"
        )

    seen: set[str] = set()

    with tempfile.TemporaryDirectory() as td:
        extract_root = Path(td)

        proc = subprocess.run(
            [
                "dpkg-deb",
                "-x",
                str(deb),
                str(extract_root),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if proc.returncode != 0:
            fail(
                "failed to extract Debian package: "
                f"{proc.stderr.strip()}"
            )

        for index, item in enumerate(
            artifacts
        ):
            record = require_dict(
                item,
                f"packaged_artifacts[{index}]",
            )

            exact_keys(
                record,
                {
                    "path",
                    "sha256",
                },
                f"packaged_artifacts[{index}]",
            )

            packaged_path = require_string(
                record["path"],
                f"packaged_artifacts[{index}].path",
            )

            digest = require_sha256(
                record["sha256"],
                f"packaged_artifacts[{index}].sha256",
            )

            pure = PurePosixPath(
                packaged_path
            )

            if (
                not pure.is_absolute()
                or ".." in pure.parts
                or packaged_path == "/"
            ):
                fail(
                    "unsafe packaged-artifact path: "
                    f"{packaged_path}"
                )

            if packaged_path in seen:
                fail(
                    "duplicate packaged-artifact path: "
                    f"{packaged_path}"
                )

            seen.add(
                packaged_path
            )

            local = (
                extract_root
                / packaged_path.lstrip("/")
            )

            if (
                local.is_symlink()
                or not local.is_file()
            ):
                fail(
                    "packaged artifact missing or not a "
                    f"regular file: {packaged_path}"
                )

            actual = sha256_file(
                local
            )

            if actual != digest:
                fail(
                    "packaged-artifact digest mismatch: "
                    f"{packaged_path}"
                )


def verify_provenance(
    root: Path,
    assets: dict[str, Any],
    materials: dict[str, Any],
) -> dict[str, Any]:
    doc = require_dict(
        read_json(
            root / "PROVENANCE.json"
        ),
        "PROVENANCE.json",
    )

    require_keys(
        doc,
        {
            "build",
            "package",
            "packaged_artifacts",
            "sbom",
            "schema",
            "source",
            "subject",
        },
        "PROVENANCE.json",
    )

    if doc["schema"] != PROVENANCE_SCHEMA:
        fail(
            "unsupported provenance schema: "
            f"{doc['schema']!r}"
        )

    subject = require_dict(
        doc["subject"],
        "PROVENANCE.subject",
    )

    source = require_dict(
        doc["source"],
        "PROVENANCE.source",
    )

    package = require_dict(
        doc["package"],
        "PROVENANCE.package",
    )

    sbom = require_dict(
        doc["sbom"],
        "PROVENANCE.sbom",
    )

    build = require_dict(
        doc["build"],
        "PROVENANCE.build",
    )

    deb_digest = sha256_file(
        assets["deb"]
    )

    sbom_digest = sha256_file(
        assets["spdx"]
    )

    if require_sha256(
        subject.get("sha256"),
        "PROVENANCE subject SHA-256",
    ) != deb_digest:
        fail(
            "PROVENANCE subject digest does not "
            "match released Debian package"
        )

    subject_name = require_string(
        subject.get("name"),
        "PROVENANCE subject name",
    )

    sbom_name = require_string(
        sbom.get("name"),
        "PROVENANCE SBOM name",
    )

    if require_sha256(
        sbom.get("sha256"),
        "PROVENANCE SBOM SHA-256",
    ) != sbom_digest:
        fail(
            "PROVENANCE SBOM digest does not "
            "match released SPDX document"
        )

    if sbom.get("format") != "SPDX-2.3-JSON":
        fail(
            "unexpected provenance SBOM format"
        )

    expected_ci_sbom_name = (
        subject_name.removesuffix(".deb")
        + ".spdx.json"
    )

    if sbom_name != expected_ci_sbom_name:
        fail(
            "PROVENANCE subject/SBOM names disagree"
        )

    expected_public_deb = (
        subject_name.replace(
            "~",
            ".",
        )
    )

    expected_public_spdx = (
        sbom_name.replace(
            "~",
            ".",
        )
    )

    if assets["deb_name"] != expected_public_deb:
        fail(
            "public Debian filename does not match "
            "canonical release normalization; "
            f"expected={expected_public_deb} "
            f"actual={assets['deb_name']}"
        )

    if assets["spdx_name"] != expected_public_spdx:
        fail(
            "public SPDX filename does not match "
            "canonical release normalization"
        )

    material_source = require_dict(
        materials["source"],
        "BUILD-MATERIALS.source",
    )

    if source.get(
        "git_commit"
    ) != material_source["commit"]:
        fail(
            "PROVENANCE source commit differs from "
            "BUILD-MATERIALS"
        )

    if source.get(
        "source_date_epoch"
    ) != material_source["source_date_epoch"]:
        fail(
            "PROVENANCE source epoch differs from "
            "BUILD-MATERIALS"
        )

    epoch = material_source[
        "source_date_epoch"
    ]

    expected_timestamp = dt.datetime.fromtimestamp(
        epoch,
        tz=dt.timezone.utc,
    ).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    if source.get(
        "timestamp_utc"
    ) != expected_timestamp:
        fail(
            "PROVENANCE UTC timestamp does not match "
            "SOURCE_DATE_EPOCH"
        )

    declared = materials[
        "declared_environment"
    ]

    if build.get(
        "environment"
    ) != declared[
        "snapshot_identity"
    ]:
        fail(
            "PROVENANCE build environment differs from "
            "BUILD-MATERIALS snapshot identity"
        )

    if build.get(
        "builder"
    ) != "open-ipod-sync/build-deb.sh":
        fail(
            "unexpected provenance builder identity"
        )

    package_name = deb_field(
        assets["deb"],
        "Package",
    )

    package_version = deb_field(
        assets["deb"],
        "Version",
    )

    package_arch = deb_field(
        assets["deb"],
        "Architecture",
    )

    if package.get(
        "name"
    ) != package_name:
        fail(
            "PROVENANCE package name differs from .deb"
        )

    if package.get(
        "version"
    ) != package_version:
        fail(
            "PROVENANCE package version differs from .deb"
        )

    if package.get(
        "architecture"
    ) != package_arch:
        fail(
            "PROVENANCE package architecture differs from .deb"
        )

    if package_arch != materials[
        "observed_environment"
    ]["architecture"]:
        fail(
            "Debian package architecture differs from "
            "BUILD-MATERIALS"
        )

    verify_packaged_artifacts(
        assets["deb"],
        doc["packaged_artifacts"],
    )

    return doc


def verify_spdx(
    root: Path,
    assets: dict[str, Any],
    provenance: dict[str, Any],
) -> None:
    doc = require_dict(
        read_json(
            assets["spdx"]
        ),
        "SPDX document",
    )

    if doc.get(
        "spdxVersion"
    ) != "SPDX-2.3":
        fail(
            "unexpected SPDX version"
        )

    if doc.get(
        "dataLicense"
    ) != "CC0-1.0":
        fail(
            "unexpected SPDX data license"
        )

    if doc.get(
        "SPDXID"
    ) != "SPDXRef-DOCUMENT":
        fail(
            "unexpected SPDX document identifier"
        )

    packages = require_list(
        doc.get("packages"),
        "SPDX packages",
    )

    relationships = require_list(
        doc.get("relationships"),
        "SPDX relationships",
    )

    ids: list[str] = []

    for index, package in enumerate(
        packages
    ):
        item = require_dict(
            package,
            f"SPDX packages[{index}]",
        )

        identifier = require_string(
            item.get("SPDXID"),
            f"SPDX packages[{index}].SPDXID",
        )

        ids.append(
            identifier
        )

    if len(set(ids)) != len(ids):
        fail(
            "duplicate SPDX package identifiers"
        )

    roots = [
        package
        for package in packages
        if package.get("SPDXID")
        == "SPDXRef-Package-ipod-sync"
    ]

    if len(roots) != 1:
        fail(
            "expected exactly one ipod-sync SPDX root package"
        )

    root_package = roots[0]

    prov_package = provenance[
        "package"
    ]

    prov_subject = provenance[
        "subject"
    ]

    if root_package.get(
        "name"
    ) != prov_package["name"]:
        fail(
            "SPDX root package name differs from provenance"
        )

    if root_package.get(
        "versionInfo"
    ) != prov_package["version"]:
        fail(
            "SPDX root package version differs from provenance"
        )

    if root_package.get(
        "packageFileName"
    ) != prov_subject["name"]:
        fail(
            "SPDX package filename differs from provenance subject"
        )

    checksums = require_list(
        root_package.get("checksums"),
        "SPDX root checksums",
    )

    expected_deb_sha = sha256_file(
        assets["deb"]
    )

    matching = [
        item
        for item in checksums
        if isinstance(item, dict)
        and item.get("algorithm") == "SHA256"
        and item.get("checksumValue")
        == expected_deb_sha
    ]

    if len(matching) != 1:
        fail(
            "SPDX root package does not contain "
            "exact released Debian SHA-256"
        )

    describes_root = any(
        isinstance(rel, dict)
        and rel.get("spdxElementId")
        == "SPDXRef-DOCUMENT"
        and rel.get("relationshipType")
        == "DESCRIBES"
        and rel.get("relatedSpdxElement")
        == "SPDXRef-Package-ipod-sync"
        for rel in relationships
    )

    if not describes_root:
        fail(
            "SPDX document does not DESCRIBE "
            "the ipod-sync root package"
        )

    namespace = require_string(
        doc.get("documentNamespace"),
        "SPDX document namespace",
    )

    suffix = (
        f"/{assets['commit']}/"
        f"{expected_deb_sha}"
    )

    if not namespace.endswith(
        suffix
    ):
        fail(
            "SPDX document namespace does not bind "
            "source commit and Debian digest"
        )

    creation = require_dict(
        doc.get("creationInfo"),
        "SPDX creationInfo",
    )

    if creation.get(
        "created"
    ) != provenance[
        "source"
    ]["timestamp_utc"]:
        fail(
            "SPDX creation timestamp differs from provenance"
        )


def verify_ci_checksum_identity(
    root: Path,
    assets: dict[str, Any],
    provenance: dict[str, Any],
) -> None:
    manifest = parse_checksums(
        root / "CI-SHA256SUMS"
    )

    subject_name = provenance[
        "subject"
    ]["name"]

    sbom_name = provenance[
        "sbom"
    ]["name"]

    expected = {
        subject_name,
        sbom_name,
        "PROVENANCE.json",
        assets["source_name"],
        "BUILD-MATERIALS.json",
        "TOOLCHAIN.json",
    }

    if set(manifest) != expected:
        fail(
            "CI-SHA256SUMS payload set mismatch; "
            f"expected={sorted(expected)} "
            f"actual={sorted(manifest)}"
        )

    if len(manifest) != 6:
        fail(
            "CI-SHA256SUMS must contain exactly "
            "six CI payload entries"
        )

    actual_mapping = {
        subject_name: assets["deb"],
        sbom_name: assets["spdx"],
        "PROVENANCE.json": (
            root / "PROVENANCE.json"
        ),
        assets["source_name"]: (
            assets["source"]
        ),
        "BUILD-MATERIALS.json": (
            root / "BUILD-MATERIALS.json"
        ),
        "TOOLCHAIN.json": (
            root / "TOOLCHAIN.json"
        ),
    }

    for name, file_path in actual_mapping.items():
        actual = sha256_file(
            file_path
        )

        if manifest[name] != actual:
            fail(
                "CI-SHA256SUMS no longer identifies "
                f"released bytes for {name}"
            )


def verify_release(
    root: Path,
    *,
    expected_commit: str | None = None,
    expected_repository: str | None = None,
) -> dict[str, str]:
    root = root.resolve()

    assets = discover_assets(
        root
    )

    if (
        expected_commit is not None
        and assets["commit"] != expected_commit
    ):
        fail(
            "release commit differs from explicitly "
            f"expected commit: expected={expected_commit} "
            f"actual={assets['commit']}"
        )

    verify_release_checksums(
        root,
        assets,
    )

    materials = verify_build_materials(
        root,
        assets,
    )

    verify_toolchain(
        root,
        materials,
    )

    provenance = verify_provenance(
        root,
        assets,
        materials,
    )

    repository = require_string(
        provenance[
            "source"
        ].get("repository"),
        "PROVENANCE source repository",
    )

    if (
        expected_repository is not None
        and repository.rstrip("/")
        != expected_repository.rstrip("/")
    ):
        fail(
            "release repository identity mismatch; "
            f"expected={expected_repository.rstrip('/')} "
            f"actual={repository.rstrip('/')}"
        )

    verify_spdx(
        root,
        assets,
        provenance,
    )

    verify_ci_checksum_identity(
        root,
        assets,
        provenance,
    )

    return {
        "commit": assets["commit"],
        "repository": repository,
        "deb": assets["deb_name"],
        "spdx": assets["spdx_name"],
        "source": assets["source_name"],
    }



def run_gh(
    args: list[str],
) -> str:
    if shutil.which("gh") is None:
        fail(
            "GitHub authenticity verification requires "
            "the GitHub CLI command: gh"
        )

    proc = subprocess.run(
        [
            "gh",
            *args,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if proc.returncode != 0:
        rendered = " ".join(
            [
                "gh",
                *args,
            ]
        )

        detail = proc.stderr.strip()

        if detail:
            fail(
                "GitHub command failed: "
                f"{rendered}: {detail}"
            )

        fail(
            "GitHub command failed: "
            f"{rendered}"
        )

    return proc.stdout


def run_gh_json(
    args: list[str],
    label: str,
) -> Any:
    raw = run_gh(
        args
    )

    try:
        return json.loads(
            raw
        )

    except json.JSONDecodeError as exc:
        fail(
            f"{label}: GitHub CLI returned invalid JSON: "
            f"{exc}"
        )


def resolve_github_tag_commit(
    *,
    repo: str,
    tag: str,
) -> str:
    ref = require_dict(
        run_gh_json(
            [
                "api",
                f"repos/{repo}/git/ref/tags/{tag}",
            ],
            "GitHub tag reference",
        ),
        "GitHub tag reference",
    )

    obj = require_dict(
        ref.get("object"),
        "GitHub tag reference object",
    )

    for _ in range(8):
        kind = require_string(
            obj.get("type"),
            "GitHub tag object type",
        )

        sha = require_string(
            obj.get("sha"),
            "GitHub tag object SHA",
        )

        if not re.fullmatch(
            r"[0-9a-f]{40}",
            sha,
        ):
            fail(
                "GitHub tag object has invalid SHA: "
                f"{sha!r}"
            )

        if kind == "commit":
            return sha

        if kind != "tag":
            fail(
                "GitHub tag resolves to unsupported "
                f"object type: {kind}"
            )

        tag_doc = require_dict(
            run_gh_json(
                [
                    "api",
                    f"repos/{repo}/git/tags/{sha}",
                ],
                "GitHub annotated tag",
            ),
            "GitHub annotated tag",
        )

        obj = require_dict(
            tag_doc.get("object"),
            "GitHub annotated tag object",
        )

    fail(
        "GitHub tag indirection exceeds verification limit"
    )


def verify_github_authenticity(
    root: Path,
    *,
    commit: str,
    provenance_repository: str,
    repo: str,
    tag: str,
) -> None:
    if not REPOSITORY_SLUG_RE.fullmatch(
        repo
    ):
        fail(
            "invalid GitHub repository slug; "
            "expected OWNER/REPO"
        )

    if not RELEASE_TAG_RE.fullmatch(
        tag
    ):
        fail(
            "unsupported GitHub release tag syntax"
        )

    expected_repository = (
        f"https://github.com/{repo}"
    )

    if (
        provenance_repository.rstrip("/")
        != expected_repository
    ):
        fail(
            "PROVENANCE repository does not match "
            "requested GitHub repository; "
            f"expected={expected_repository} "
            f"actual={provenance_repository.rstrip('/')}"
        )

    release = require_dict(
        run_gh_json(
            [
                "release",
                "view",
                tag,
                "--repo",
                repo,
                "--json",
                (
                    "tagName,isDraft,isPrerelease,"
                    "isImmutable,assets"
                ),
            ],
            "GitHub release",
        ),
        "GitHub release",
    )

    if release.get(
        "tagName"
    ) != tag:
        fail(
            "GitHub release tag identity mismatch"
        )

    if release.get(
        "isDraft"
    ) is not False:
        fail(
            "GitHub release is still a draft"
        )

    if release.get(
        "isImmutable"
    ) is not True:
        fail(
            "GitHub release is not immutable"
        )

    remote_assets_raw = require_list(
        release.get("assets"),
        "GitHub release assets",
    )

    remote_names: list[str] = []

    for index, item in enumerate(
        remote_assets_raw
    ):
        asset = require_dict(
            item,
            f"GitHub release assets[{index}]",
        )

        remote_names.append(
            require_string(
                asset.get("name"),
                (
                    "GitHub release "
                    f"assets[{index}].name"
                ),
            )
        )

    if len(set(remote_names)) != len(
        remote_names
    ):
        fail(
            "GitHub release contains duplicate asset names"
        )

    local_names = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_file()
        and not entry.is_symlink()
    )

    if set(remote_names) != set(
        local_names
    ):
        fail(
            "remote release asset set mismatch; "
            f"expected={local_names} "
            f"actual={sorted(remote_names)}"
        )

    tag_commit = resolve_github_tag_commit(
        repo=repo,
        tag=tag,
    )

    if tag_commit != commit:
        fail(
            "GitHub release tag does not resolve to "
            "verified source commit; "
            f"expected={commit} "
            f"actual={tag_commit}"
        )

    run_gh(
        [
            "release",
            "verify",
            tag,
            "--repo",
            repo,
        ]
    )

    for name in local_names:
        run_gh(
            [
                "release",
                "verify-asset",
                tag,
                str(root / name),
                "--repo",
                repo,
            ]
        )

    signer_workflow = (
        f"{repo}/.github/workflows/ci.yml"
    )

    source_ref = (
        "refs/heads/main"
    )

    ci_attested = [
        root
        / name
        for name in (
            next(
                entry.name
                for entry in root.iterdir()
                if entry.is_file()
                and DEB_RE.fullmatch(
                    entry.name
                )
            ),
            next(
                entry.name
                for entry in root.iterdir()
                if entry.is_file()
                and SPDX_RE.fullmatch(
                    entry.name
                )
            ),
            "PROVENANCE.json",
            "CI-SHA256SUMS",
            next(
                entry.name
                for entry in root.iterdir()
                if entry.is_file()
                and SOURCE_RE.fullmatch(
                    entry.name
                )
            ),
            "BUILD-MATERIALS.json",
            "TOOLCHAIN.json",
        )
    ]

    for artifact in ci_attested:
        run_gh(
            [
                "attestation",
                "verify",
                str(artifact),
                "--repo",
                repo,
                "--signer-workflow",
                signer_workflow,
                "--source-digest",
                commit,
                "--source-ref",
                source_ref,
                "--deny-self-hosted-runners",
            ]
        )

    deb = next(
        artifact
        for artifact in ci_attested
        if DEB_RE.fullmatch(
            artifact.name
        )
    )

    run_gh(
        [
            "attestation",
            "verify",
            str(deb),
            "--repo",
            repo,
            "--predicate-type",
            "https://spdx.dev/Document/v2.3",
            "--signer-workflow",
            signer_workflow,
            "--source-digest",
            commit,
            "--source-ref",
            source_ref,
            "--deny-self-hosted-runners",
        ]
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Verify an open-ipod-sync release directory "
            "without trusting the producing CI workspace."
        )
    )

    ap.add_argument(
        "release_dir",
        type=Path,
    )

    ap.add_argument(
        "--expected-commit",
        help=(
            "Require the release to bind to this exact "
            "40-character source commit."
        ),
    )

    ap.add_argument(
        "--expected-repository",
        help=(
            "Require PROVENANCE.json to name this "
            "repository URL."
        ),
    )

    ap.add_argument(
        "--github",
        action="store_true",
        help=(
            "After offline verification, verify the "
            "immutable GitHub Release, tag binding, "
            "release assets, and CI artifact attestations."
        ),
    )

    ap.add_argument(
        "--repo",
        help=(
            "GitHub repository slug OWNER/REPO. "
            "Required with --github."
        ),
    )

    ap.add_argument(
        "--tag",
        help=(
            "GitHub release tag. Required with --github."
        ),
    )

    args = ap.parse_args()

    if args.github:
        if not args.repo or not args.tag:
            ap.error(
                "--github requires both --repo and --tag"
            )

        if not REPOSITORY_SLUG_RE.fullmatch(
            args.repo
        ):
            ap.error(
                "--repo must use OWNER/REPO syntax"
            )

        if not RELEASE_TAG_RE.fullmatch(
            args.tag
        ):
            ap.error(
                "--tag contains unsupported characters"
            )

    elif args.repo or args.tag:
        ap.error(
            "--repo and --tag are only valid with --github"
        )

    return args


def main() -> int:
    args = parse_args()

    if (
        args.expected_commit is not None
        and not re.fullmatch(
            r"[0-9a-f]{40}",
            args.expected_commit,
        )
    ):
        print(
            "ERROR: --expected-commit must be a full "
            "lowercase 40-character commit",
            file=sys.stderr,
        )

        return 2

    expected_repository = (
        args.expected_repository
    )

    if args.github:
        github_repository = (
            f"https://github.com/{args.repo}"
        )

        if (
            expected_repository is not None
            and expected_repository.rstrip("/")
            != github_repository
        ):
            print(
                "ERROR: --expected-repository conflicts "
                "with --repo",
                file=sys.stderr,
            )

            return 2

        expected_repository = (
            github_repository
        )

    try:
        result = verify_release(
            args.release_dir,
            expected_commit=(
                args.expected_commit
            ),
            expected_repository=(
                expected_repository
            ),
        )

        if args.github:
            verify_github_authenticity(
                args.release_dir.resolve(),
                commit=result["commit"],
                provenance_repository=(
                    result["repository"]
                ),
                repo=args.repo,
                tag=args.tag,
            )

    except VerifyError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 1

    print(
        "release asset set: PASS"
    )
    print(
        "release SHA256SUMS: PASS"
    )
    print(
        "CI artifact identity: PASS"
    )
    print(
        "source archive identity: PASS"
    )
    print(
        "build-material linkage: PASS"
    )
    print(
        "declared toolchain policy: PASS"
    )
    print(
        "Debian package/provenance linkage: PASS"
    )
    print(
        "packaged-artifact provenance: PASS"
    )
    print(
        "SPDX/package linkage: PASS"
    )
    print(
        f"source commit: {result['commit']}"
    )
    print(
        f"repository:    {result['repository']}"
    )
    print(
        "offline consumer release verification: PASS"
    )

    if args.github:
        print(
            "GitHub immutable release: PASS"
        )
        print(
            "GitHub tag/source binding: PASS"
        )
        print(
            "GitHub release asset attestations: PASS"
        )
        print(
            "GitHub CI provenance attestations: PASS"
        )
        print(
            "GitHub SPDX attestation: PASS"
        )
        print(
            "GitHub authenticity verification: PASS"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
