#!/usr/bin/env python3

import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]

VERIFY_PATH = (
    ROOT
    / "tools"
    / "verify-release.py"
)

spec = importlib.util.spec_from_file_location(
    "verify_release_tool",
    VERIFY_PATH,
)

assert spec is not None
assert spec.loader is not None

verify = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    verify
)


COMMIT = "12" * 20
EPOCH = 1700000000
REPOSITORY = (
    "https://github.com/"
    "pssingh21/open-ipod-sync"
)

CI_DEB = (
    "ipod-sync_0.2.0~alpha7_amd64.deb"
)

CI_SPDX = (
    "ipod-sync_0.2.0~alpha7_amd64.spdx.json"
)

PUBLIC_DEB = (
    "ipod-sync_0.2.0.alpha7_amd64.deb"
)

PUBLIC_SPDX = (
    "ipod-sync_0.2.0.alpha7_amd64.spdx.json"
)

SOURCE = (
    f"open-ipod-sync-{COMMIT}-source.tar"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def write_json(
    path: Path,
    value,
) -> None:
    path.write_text(
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def write_checksums(
    path: Path,
    entries,
) -> None:
    path.write_text(
        "".join(
            f"{digest}  {name}\n"
            for name, digest in entries
        )
    )


def make_source_archive(
    path: Path,
    *,
    commit: str = COMMIT,
    epoch: int = EPOCH,
    unsafe: bool = False,
) -> None:
    prefix = (
        f"open-ipod-sync-{commit}/"
    )

    with tarfile.open(
        path,
        mode="w",
        format=tarfile.PAX_FORMAT,
        pax_headers={
            "comment": commit,
        },
    ) as tf:
        directory = tarfile.TarInfo(
            prefix
        )

        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        directory.mtime = epoch

        tf.addfile(
            directory
        )

        name = (
            prefix
            + (
                "../escape"
                if unsafe
                else "README.md"
            )
        )

        payload = b"consumer verification test\n"

        item = tarfile.TarInfo(
            name
        )

        item.size = len(payload)
        item.mode = 0o644
        item.mtime = epoch

        tf.addfile(
            item,
            io.BytesIO(payload),
        )


def make_deb(
    path: Path,
) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "pkg"

        control = (
            pkg
            / "DEBIAN"
            / "control"
        )

        control.parent.mkdir(
            parents=True
        )

        control.write_text(
            "\n".join(
                [
                    "Package: ipod-sync",
                    "Version: 0.2.0~alpha7",
                    "Architecture: amd64",
                    "Maintainer: Test <test@example.invalid>",
                    "Description: verifier test package",
                    "",
                ]
            )
        )

        first = (
            pkg
            / "usr/lib/ipod-sync/ipod_sync.py"
        )

        second = (
            pkg
            / "usr/lib/ipod-sync/native/sync-envelope"
        )

        first.parent.mkdir(
            parents=True
        )

        second.parent.mkdir(
            parents=True
        )

        first.write_text(
            "print('test')\n"
        )

        second.write_bytes(
            b"test-native\n"
        )

        subprocess.run(
            [
                "dpkg-deb",
                "--build",
                "--root-owner-group",
                str(pkg),
                str(path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )

        return {
            "/usr/lib/ipod-sync/ipod_sync.py": (
                hashlib.sha256(
                    first.read_bytes()
                ).hexdigest()
            ),
            "/usr/lib/ipod-sync/native/sync-envelope": (
                hashlib.sha256(
                    second.read_bytes()
                ).hexdigest()
            ),
        }


def refresh_manifests(
    root: Path,
) -> None:
    provenance = json.loads(
        (
            root
            / "PROVENANCE.json"
        ).read_text()
    )

    ci_entries = [
        (
            provenance["subject"]["name"],
            sha256(
                root
                / PUBLIC_DEB
            ),
        ),
        (
            provenance["sbom"]["name"],
            sha256(
                root
                / PUBLIC_SPDX
            ),
        ),
        (
            "PROVENANCE.json",
            sha256(
                root
                / "PROVENANCE.json"
            ),
        ),
        (
            SOURCE,
            sha256(
                root
                / SOURCE
            ),
        ),
        (
            "BUILD-MATERIALS.json",
            sha256(
                root
                / "BUILD-MATERIALS.json"
            ),
        ),
        (
            "TOOLCHAIN.json",
            sha256(
                root
                / "TOOLCHAIN.json"
            ),
        ),
    ]

    write_checksums(
        root / "CI-SHA256SUMS",
        sorted(ci_entries),
    )

    release_entries = [
        (
            PUBLIC_DEB,
            sha256(
                root
                / PUBLIC_DEB
            ),
        ),
        (
            PUBLIC_SPDX,
            sha256(
                root
                / PUBLIC_SPDX
            ),
        ),
        (
            "PROVENANCE.json",
            sha256(
                root
                / "PROVENANCE.json"
            ),
        ),
        (
            "CI-SHA256SUMS",
            sha256(
                root
                / "CI-SHA256SUMS"
            ),
        ),
        (
            SOURCE,
            sha256(
                root
                / SOURCE
            ),
        ),
        (
            "BUILD-MATERIALS.json",
            sha256(
                root
                / "BUILD-MATERIALS.json"
            ),
        ),
        (
            "TOOLCHAIN.json",
            sha256(
                root
                / "TOOLCHAIN.json"
            ),
        ),
    ]

    write_checksums(
        root / "SHA256SUMS",
        release_entries,
    )


def make_bundle(
    root: Path,
) -> None:
    make_source_archive(
        root / SOURCE
    )

    packaged = make_deb(
        root / PUBLIC_DEB
    )

    deb_sha = sha256(
        root / PUBLIC_DEB
    )

    timestamp = dt.datetime.fromtimestamp(
        EPOCH,
        tz=dt.timezone.utc,
    ).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    spdx = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "created": timestamp,
            "creators": [
                "Tool: test",
            ],
        },
        "dataLicense": "CC0-1.0",
        "documentNamespace": (
            f"{REPOSITORY}/spdx/"
            f"{COMMIT}/"
            f"{deb_sha}"
        ),
        "name": "test-sbom",
        "packages": [
            {
                "SPDXID": (
                    "SPDXRef-Package-ipod-sync"
                ),
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": deb_sha,
                    }
                ],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "name": "ipod-sync",
                "packageFileName": CI_DEB,
                "supplier": "NOASSERTION",
                "versionInfo": "0.2.0~alpha7",
            }
        ],
        "relationships": [
            {
                "relatedSpdxElement": (
                    "SPDXRef-Package-ipod-sync"
                ),
                "relationshipType": "DESCRIBES",
                "spdxElementId": "SPDXRef-DOCUMENT",
            }
        ],
        "spdxVersion": "SPDX-2.3",
    }

    write_json(
        root / PUBLIC_SPDX,
        spdx,
    )

    sbom_sha = sha256(
        root / PUBLIC_SPDX
    )

    provenance = {
        "build": {
            "builder": (
                "open-ipod-sync/build-deb.sh"
            ),
            "environment": (
                "debian-11-amd64-"
                "snapshot-20260830T235959Z"
            ),
            "reproducibility_gate": (
                "test"
            ),
        },
        "bundled_libgpod": {
            "base_tree": "libgpod-0.8.3",
            "compiled_runtime_copied": "yes",
            "patched_tree": "test",
            "source_patch_sha256": "34" * 32,
        },
        "package": {
            "architecture": "amd64",
            "name": "ipod-sync",
            "version": "0.2.0~alpha7",
        },
        "packaged_artifacts": [
            {
                "path": path,
                "sha256": digest,
            }
            for path, digest in sorted(
                packaged.items()
            )
        ],
        "sbom": {
            "format": "SPDX-2.3-JSON",
            "name": CI_SPDX,
            "sha256": sbom_sha,
        },
        "schema": (
            "open-ipod-sync-provenance-v1"
        ),
        "source": {
            "git_commit": COMMIT,
            "repository": REPOSITORY,
            "source_date_epoch": EPOCH,
            "timestamp_utc": timestamp,
        },
        "subject": {
            "name": CI_DEB,
            "sha256": deb_sha,
        },
    }

    write_json(
        root / "PROVENANCE.json",
        provenance,
    )

    materials = {
        "declared_environment": {
            "base_image_identity": (
                "debian:11@sha256:"
                + "56" * 32
            ),
            "snapshot_identity": (
                "debian-11-amd64-"
                "snapshot-20260830T235959Z"
            ),
        },
        "observed_environment": {
            "architecture": "amd64",
            "build_packages": [
                {
                    "architecture": "amd64",
                    "name": "python3",
                    "version": "3.9.2-3",
                }
            ],
            "debian_version": "11.11",
            "pkg_config_modules": [
                {
                    "module": "glib-2.0",
                    "version": "2.66.8",
                }
            ],
            "tools": {
                "python3": "Python 3.9.2",
            },
        },
        "schema": (
            "open-ipod-sync-build-materials-v1"
        ),
        "source": {
            "archive_sha256": sha256(
                root / SOURCE
            ),
            "commit": COMMIT,
            "source_date_epoch": EPOCH,
        },
    }

    write_json(
        root / "BUILD-MATERIALS.json",
        materials,
    )

    toolchain = {
        "commands": [
            {
                "command": "python3",
                "package": "python3-minimal",
                "package_version": "3.9.2-3",
                "target": "/usr/bin/python3",
            }
        ],
        "policy": {
            "allowed_real_roots": [
                "/usr/bin",
            ],
            "ambient_path_used": False,
            "developer_local_roots_allowed": False,
        },
        "schema": (
            "open-ipod-sync-toolchain-view-v1"
        ),
    }

    write_json(
        root / "TOOLCHAIN.json",
        toolchain,
    )

    refresh_manifests(
        root
    )


def expect_failure(
    root: Path,
    contains: str,
) -> None:
    try:
        verify.verify_release(
            root,
            expected_repository=REPOSITORY,
        )

    except verify.VerifyError as exc:
        message = str(exc)

        if contains not in message:
            raise AssertionError(
                "wrong verifier failure\n"
                f"expected substring: {contains!r}\n"
                f"actual: {message!r}"
            )

        return

    raise AssertionError(
        "verifier unexpectedly accepted tampered release"
    )


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    result = verify.verify_release(
        root,
        expected_commit=COMMIT,
        expected_repository=REPOSITORY,
    )

    assert result["commit"] == COMMIT

    print("valid synthetic release: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    (
        root
        / "unexpected.txt"
    ).write_text(
        "unexpected\n"
    )

    expect_failure(
        root,
        "release asset set mismatch",
    )

    print("unexpected asset rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    (
        root
        / "TOOLCHAIN.json"
    ).unlink()

    expect_failure(
        root,
        "release asset set mismatch",
    )

    print("missing asset rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    with (
        root
        / PUBLIC_DEB
    ).open("ab") as f:
        f.write(
            b"tamper"
        )

    expect_failure(
        root,
        "SHA256SUMS mismatch",
    )

    print("payload tamper rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    materials_path = (
        root
        / "BUILD-MATERIALS.json"
    )

    materials = json.loads(
        materials_path.read_text()
    )

    materials["source"][
        "archive_sha256"
    ] = "ab" * 32

    write_json(
        materials_path,
        materials,
    )

    refresh_manifests(
        root
    )

    expect_failure(
        root,
        "source archive digest mismatch",
    )

    print("source digest-link rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    materials_path = (
        root
        / "BUILD-MATERIALS.json"
    )

    materials = json.loads(
        materials_path.read_text()
    )

    materials["source"][
        "commit"
    ] = "34" * 20

    write_json(
        materials_path,
        materials,
    )

    refresh_manifests(
        root
    )

    expect_failure(
        root,
        "source commit mismatch",
    )

    print("source commit-link rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    toolchain_path = (
        root
        / "TOOLCHAIN.json"
    )

    toolchain = json.loads(
        toolchain_path.read_text()
    )

    toolchain["policy"][
        "ambient_path_used"
    ] = True

    write_json(
        toolchain_path,
        toolchain,
    )

    refresh_manifests(
        root
    )

    expect_failure(
        root,
        "permits ambient PATH",
    )

    print("ambient PATH policy rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    provenance_path = (
        root
        / "PROVENANCE.json"
    )

    provenance = json.loads(
        provenance_path.read_text()
    )

    provenance["subject"][
        "sha256"
    ] = "cd" * 32

    write_json(
        provenance_path,
        provenance,
    )

    refresh_manifests(
        root
    )

    expect_failure(
        root,
        "subject digest",
    )

    print("provenance/package rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    spdx_path = (
        root
        / PUBLIC_SPDX
    )

    spdx = json.loads(
        spdx_path.read_text()
    )

    spdx["packages"][0][
        "checksums"
    ][0][
        "checksumValue"
    ] = "ef" * 32

    write_json(
        spdx_path,
        spdx,
    )

    provenance_path = (
        root
        / "PROVENANCE.json"
    )

    provenance = json.loads(
        provenance_path.read_text()
    )

    provenance["sbom"][
        "sha256"
    ] = sha256(
        spdx_path
    )

    write_json(
        provenance_path,
        provenance,
    )

    refresh_manifests(
        root
    )

    expect_failure(
        root,
        "SPDX root package",
    )

    print("SPDX/package rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    ci_path = (
        root
        / "CI-SHA256SUMS"
    )

    entries = verify.parse_checksums(
        ci_path
    )

    entries.pop(
        "TOOLCHAIN.json"
    )

    write_checksums(
        ci_path,
        sorted(
            entries.items()
        ),
    )

    release_manifest = verify.parse_checksums(
        root
        / "SHA256SUMS"
    )

    release_manifest[
        "CI-SHA256SUMS"
    ] = sha256(
        ci_path
    )

    write_checksums(
        root
        / "SHA256SUMS",
        release_manifest.items(),
    )

    expect_failure(
        root,
        "CI-SHA256SUMS payload set mismatch",
    )

    print("CI identity truncation rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    make_source_archive(
        root / SOURCE,
        unsafe=True,
    )

    materials_path = (
        root
        / "BUILD-MATERIALS.json"
    )

    materials = json.loads(
        materials_path.read_text()
    )

    materials["source"][
        "archive_sha256"
    ] = sha256(
        root / SOURCE
    )

    write_json(
        materials_path,
        materials,
    )

    refresh_manifests(
        root
    )

    expect_failure(
        root,
        "unsafe source archive member",
    )

    print("unsafe source archive rejection: PASS")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    make_bundle(root)

    try:
        verify.verify_release(
            root,
            expected_commit="56" * 20,
            expected_repository=REPOSITORY,
        )

    except verify.VerifyError as exc:
        assert (
            "explicitly expected commit"
            in str(exc)
        )

    else:
        raise AssertionError(
            "expected-commit pin was not enforced"
        )

    print("external commit pinning: PASS")


print(
    "offline consumer verifier adversarial tests: PASS"
)
