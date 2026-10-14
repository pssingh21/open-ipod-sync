#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tools/generate-supply-chain-metadata.py"

spec = importlib.util.spec_from_file_location(
    "ipod_sync_supply_chain_test",
    GEN,
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


depends = (
    "python3 (>= 3.9), "
    "ifuse, "
    "libfoo:any | libfoo-alt, "
    "zlib1g"
)

assert m.parse_dependencies(depends) == [
    "ifuse",
    "libfoo",
    "libfoo-alt",
    "python3",
    "zlib1g",
]

vendor = {
    "base_tree": "libgpod-0.8.3",
    "patched_tree": "libgpod-test",
    "source_patch_sha256": "ab" * 32,
    "compiled_runtime_copied": "no",
}

doc = m.make_spdx_document(
    package="ipod-sync",
    version="0.2.0~alpha6",
    architecture="amd64",
    deb_name="ipod-sync_0.2.0~alpha6_amd64.deb",
    deb_sha256="cd" * 32,
    dependencies=[
        "ffmpeg",
        "python3",
    ],
    git_commit="12" * 20,
    source_date_epoch=1700000000,
    repository=(
        "https://github.com/pssingh21/open-ipod-sync"
    ),
    vendor_provenance=vendor,
)

m.validate_spdx_document(doc)

assert doc["spdxVersion"] == "SPDX-2.3"
assert doc["dataLicense"] == "CC0-1.0"
assert doc["SPDXID"] == "SPDXRef-DOCUMENT"

root = next(
    package
    for package in doc["packages"]
    if package["SPDXID"]
    == "SPDXRef-Package-ipod-sync"
)

assert root["checksums"] == [{
    "algorithm": "SHA256",
    "checksumValue": "cd" * 32,
}]

dependency_relationships = {
    relationship["relatedSpdxElement"]
    for relationship in doc["relationships"]
    if relationship["relationshipType"]
    == "DEPENDS_ON"
}

assert dependency_relationships == {
    "SPDXRef-Dependency-ffmpeg",
    "SPDXRef-Dependency-python3",
}

with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "sbom.json"

    m.write_json(
        path,
        doc,
    )

    first = path.read_bytes()

    m.write_json(
        path,
        doc,
    )

    second = path.read_bytes()

    assert first == second
    assert json.loads(
        first.decode("utf-8")
    ) == doc


provenance = m.make_provenance_document(
    package="ipod-sync",
    version="0.2.0~alpha6",
    architecture="amd64",
    deb_name="ipod-sync_0.2.0~alpha6_amd64.deb",
    deb_sha256="cd" * 32,
    sbom_name=(
        "ipod-sync_0.2.0~alpha6_amd64.spdx.json"
    ),
    sbom_sha256="ef" * 32,
    git_commit="12" * 20,
    source_date_epoch=1700000000,
    repository=(
        "https://github.com/pssingh21/open-ipod-sync"
    ),
    build_environment=(
        "debian-11-amd64-snapshot-20260830T235959Z"
    ),
    vendor_provenance=vendor,
    packaged_artifacts=[
        {
            "path": (
                "/usr/lib/ipod-sync/native/"
                "sync-envelope"
            ),
            "sha256": "34" * 32,
        }
    ],
)

assert provenance["schema"] == (
    "open-ipod-sync-provenance-v1"
)

assert provenance["subject"]["sha256"] == (
    "cd" * 32
)

assert provenance["sbom"]["sha256"] == (
    "ef" * 32
)

assert (
    provenance["bundled_libgpod"]
    ["source_patch_sha256"]
    == "ab" * 32
)

print("supply-chain metadata tests: PASS")
