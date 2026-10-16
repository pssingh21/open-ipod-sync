#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_REPOSITORY = "https://github.com/pssingh21/open-ipod-sync"
SPDX_VERSION = "SPDX-2.3"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_text(cmd: list[str]) -> str:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def deb_field(deb: Path, field: str) -> str:
    return run_text(["dpkg-deb", "-f", str(deb), field])


def parse_dependencies(value: str) -> list[str]:
    """Return deterministic Debian dependency package names.

    Current package metadata contains simple comma-separated dependencies.
    Version constraints and architecture qualifiers are stripped. Alternatives
    are represented by each alternative package name.
    """
    names: set[str] = set()

    for relation in value.split(","):
        for alternative in relation.split("|"):
            item = alternative.strip()

            match = re.match(
                r"^([A-Za-z0-9][A-Za-z0-9+.-]*)(?::[A-Za-z0-9-]+)?",
                item,
            )

            if match:
                names.add(match.group(1))

    return sorted(names)


def read_vendor_provenance(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    for raw in path.read_text().splitlines():
        raw = raw.strip()

        if not raw or raw.startswith("#") or "=" not in raw:
            continue

        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()

    return values


def spdx_id_for_dependency(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-")
    return f"SPDXRef-Dependency-{safe}"


def timestamp_utc(epoch: int) -> str:
    return dt.datetime.fromtimestamp(
        epoch,
        tz=dt.timezone.utc,
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def package_stub(
    *,
    name: str,
    spdx_id: str,
    version: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "name": name,
        "SPDXID": spdx_id,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "supplier": "NOASSERTION",
    }

    if version:
        obj["versionInfo"] = version

    if comment:
        obj["comment"] = comment

    return obj


def make_spdx_document(
    *,
    package: str,
    version: str,
    architecture: str,
    deb_name: str,
    deb_sha256: str,
    dependencies: list[str],
    git_commit: str,
    source_date_epoch: int,
    repository: str,
    vendor_provenance: dict[str, str],
) -> dict[str, Any]:
    root_id = "SPDXRef-Package-ipod-sync"
    libgpod_id = "SPDXRef-Package-libgpod"

    namespace = (
        f"{repository}/spdx/"
        f"{git_commit}/"
        f"{deb_sha256}"
    )

    patch_sha = vendor_provenance.get(
        "source_patch_sha256",
        "NOASSERTION",
    )
    base_tree = vendor_provenance.get(
        "base_tree",
        "libgpod-0.8.3",
    )

    packages: list[dict[str, Any]] = [
        {
            "name": package,
            "SPDXID": root_id,
            "versionInfo": version,
            "packageFileName": deb_name,
            "supplier": "NOASSERTION",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "checksums": [
                {
                    "algorithm": "SHA256",
                    "checksumValue": deb_sha256,
                }
            ],
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "primaryPackagePurpose": "APPLICATION",
            "comment": (
                "Debian binary package for open-ipod-sync; "
                f"architecture={architecture}"
            ),
        },
        package_stub(
            name="libgpod",
            spdx_id=libgpod_id,
            version="0.8.3",
            comment=(
                "Bundled modified libgpod source is rebuilt into the Debian "
                f"artifact. Base tree={base_tree}; "
                f"reviewable patch SHA256={patch_sha}."
            ),
        ),
    ]

    relationships: list[dict[str, str]] = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": root_id,
        },
        {
            "spdxElementId": root_id,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": libgpod_id,
        },
    ]

    for dep in dependencies:
        dep_id = spdx_id_for_dependency(dep)

        packages.append(
            package_stub(
                name=dep,
                spdx_id=dep_id,
                comment=(
                    "Runtime dependency declared by the Debian package. "
                    "The package metadata does not pin an exact version."
                ),
            )
        )

        relationships.append(
            {
                "spdxElementId": root_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": dep_id,
            }
        )

    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{package}-{version}-{architecture}",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": timestamp_utc(source_date_epoch),
            "creators": [
                "Tool: open-ipod-sync-generate-supply-chain-metadata-1"
            ],
            "comment": "SBOM Generation Context: Build",
        },
        "packages": packages,
        "relationships": relationships,
    }


def validate_spdx_document(doc: dict[str, Any]) -> None:
    required = {
        "spdxVersion",
        "dataLicense",
        "SPDXID",
        "name",
        "documentNamespace",
        "creationInfo",
        "packages",
        "relationships",
    }

    missing = sorted(required - set(doc))

    if missing:
        raise ValueError(
            f"SPDX document missing required fields: {missing}"
        )

    if doc["spdxVersion"] != SPDX_VERSION:
        raise ValueError(
            f"unexpected SPDX version: {doc['spdxVersion']}"
        )

    packages = doc["packages"]

    if not isinstance(packages, list) or not packages:
        raise ValueError("SPDX document has no packages")

    ids = {
        package["SPDXID"]
        for package in packages
    }

    if len(ids) != len(packages):
        raise ValueError("duplicate package SPDX identifiers")

    valid_ids = ids | {"SPDXRef-DOCUMENT"}

    for relationship in doc["relationships"]:
        left = relationship["spdxElementId"]
        right = relationship["relatedSpdxElement"]

        if left not in valid_ids:
            raise ValueError(
                f"relationship references unknown element: {left}"
            )

        if (
            right.startswith("SPDXRef-")
            and right not in valid_ids
        ):
            raise ValueError(
                f"relationship references unknown element: {right}"
            )

    if not any(
        relationship["spdxElementId"] == "SPDXRef-DOCUMENT"
        and relationship["relationshipType"] == "DESCRIBES"
        for relationship in doc["relationships"]
    ):
        raise ValueError(
            "SPDX document does not DESCRIBE a package"
        )


def extracted_artifacts(deb: Path) -> list[dict[str, str]]:
    wanted_exact = {
        "usr/lib/ipod-sync/ipod_sync.py",
        "usr/lib/ipod-sync/ipodctl/cdb.py",
        "usr/lib/ipod-sync/native/sync-envelope",
        "usr/lib/ipod-sync/native/sign-cdb.c",
        "usr/lib/ipod-sync/native/rijndael.c",
    }

    results: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        subprocess.run(
            ["dpkg-deb", "-x", str(deb), str(root)],
            check=True,
            stdout=subprocess.DEVNULL,
        )

        for rel in sorted(wanted_exact):
            path = root / rel

            if not path.is_file():
                raise RuntimeError(
                    f"expected packaged artifact missing: /{rel}"
                )

            results.append({
                "path": f"/{rel}",
                "sha256": sha256_file(path),
            })

        libdir = (
            root
            / "usr/lib/ipod-sync/vendor/libgpod/lib"
        )

        libgpod_files = sorted(
            path
            for path in libdir.glob("libgpod.so*")
            if path.is_file() and not path.is_symlink()
        )

        if not libgpod_files:
            raise RuntimeError(
                "packaged libgpod shared object missing"
            )

        for path in libgpod_files:
            rel = path.relative_to(root)

            results.append({
                "path": f"/{rel.as_posix()}",
                "sha256": sha256_file(path),
            })

    return results


def reproducibility_claim(build_environment: str) -> str:
    # Only the pinned Debian 11 build currently has the
    # independent reproducibility verification gate.
    if build_environment == (
        "debian-11-amd64-snapshot-20260830T235959Z"
    ):
        return (
            "CI independently rebuilds and byte-compares "
            "the Debian package and generated metadata."
        )

    # Fail closed for Ubuntu and other unverified environments.
    return (
        "Independent reproducibility verification has not been "
        "established for this build environment."
    )


def make_provenance_document(
    *,
    package: str,
    version: str,
    architecture: str,
    deb_name: str,
    deb_sha256: str,
    sbom_name: str,
    sbom_sha256: str,
    git_commit: str,
    source_date_epoch: int,
    repository: str,
    build_environment: str,
    vendor_provenance: dict[str, str],
    packaged_artifacts: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schema": "open-ipod-sync-provenance-v1",
        "subject": {
            "name": deb_name,
            "sha256": deb_sha256,
        },
        "source": {
            "repository": repository,
            "git_commit": git_commit,
            "source_date_epoch": source_date_epoch,
            "timestamp_utc": timestamp_utc(source_date_epoch),
        },
        "package": {
            "name": package,
            "version": version,
            "architecture": architecture,
        },
        "sbom": {
            "name": sbom_name,
            "format": "SPDX-2.3-JSON",
            "sha256": sbom_sha256,
        },
        "build": {
            "environment": build_environment,
            "builder": "open-ipod-sync/build-deb.sh",
            "reproducibility_gate": reproducibility_claim(
                build_environment
            ),
        },
        "bundled_libgpod": {
            "base_tree": vendor_provenance.get(
                "base_tree",
                "NOASSERTION",
            ),
            "patched_tree": vendor_provenance.get(
                "patched_tree",
                "NOASSERTION",
            ),
            "source_patch_sha256": vendor_provenance.get(
                "source_patch_sha256",
                "NOASSERTION",
            ),
            "compiled_runtime_copied": vendor_provenance.get(
                "compiled_runtime_copied",
                "NOASSERTION",
            ),
        },
        "packaged_artifacts": packaged_artifacts,
    }


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            obj,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()

    ap.add_argument("deb", type=Path)
    ap.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    ap.add_argument(
        "--git-commit",
        required=True,
    )
    ap.add_argument(
        "--source-date-epoch",
        required=True,
        type=int,
    )
    ap.add_argument(
        "--repository",
        default=DEFAULT_REPOSITORY,
    )
    ap.add_argument(
        "--build-environment",
        required=True,
    )

    args = ap.parse_args()

    deb = args.deb.resolve()

    if not deb.is_file():
        raise SystemExit(
            f"Debian package not found: {deb}"
        )

    if not re.fullmatch(
        r"[0-9a-f]{40}",
        args.git_commit,
    ):
        raise SystemExit(
            "git commit must be a full lowercase 40-character SHA-1"
        )

    if args.source_date_epoch < 0:
        raise SystemExit(
            "SOURCE_DATE_EPOCH must be non-negative"
        )

    package = deb_field(deb, "Package")
    version = deb_field(deb, "Version")
    architecture = deb_field(deb, "Architecture")
    depends = deb_field(deb, "Depends")

    dependencies = parse_dependencies(depends)
    deb_sha = sha256_file(deb)

    vendor = read_vendor_provenance(
        ROOT / "vendor/PROVENANCE.txt"
    )

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    sbom_name = (
        deb.name.removesuffix(".deb")
        + ".spdx.json"
    )
    sbom_path = args.output_dir / sbom_name

    sbom = make_spdx_document(
        package=package,
        version=version,
        architecture=architecture,
        deb_name=deb.name,
        deb_sha256=deb_sha,
        dependencies=dependencies,
        git_commit=args.git_commit,
        source_date_epoch=args.source_date_epoch,
        repository=args.repository.rstrip("/"),
        vendor_provenance=vendor,
    )

    validate_spdx_document(sbom)
    write_json(sbom_path, sbom)

    sbom_sha = sha256_file(sbom_path)

    provenance = make_provenance_document(
        package=package,
        version=version,
        architecture=architecture,
        deb_name=deb.name,
        deb_sha256=deb_sha,
        sbom_name=sbom_name,
        sbom_sha256=sbom_sha,
        git_commit=args.git_commit,
        source_date_epoch=args.source_date_epoch,
        repository=args.repository.rstrip("/"),
        build_environment=args.build_environment,
        vendor_provenance=vendor,
        packaged_artifacts=extracted_artifacts(deb),
    )

    provenance_path = (
        args.output_dir / "PROVENANCE.json"
    )
    write_json(
        provenance_path,
        provenance,
    )

    print(f"SBOM:       {sbom_path}")
    print(
        f"SBOM SHA256: {sbom_sha}"
    )
    print(
        f"Provenance: {provenance_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
