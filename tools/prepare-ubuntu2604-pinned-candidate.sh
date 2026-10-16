#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP required}"
: "${GITHUB_SHA:?GITHUB_SHA required}"

IMAGE="docker.io/library/ubuntu@sha256:88a381d5b5eeb2b35d3ad70925a362c37ce569daf43ede89ff818ec20e4d3794"
SNAPSHOT="20261015T000000Z"

root="$RUNNER_TEMP/ubuntu2604-pinned-matrix"
matrix="$root/matrix/results"
a="$matrix/builder-a"
b="$matrix/builder-b"
materials="$matrix/materials"
archive="$root/input/source.tar"
out="$RUNNER_TEMP/ubuntu2604-pinned-candidate"

test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
test ! -e "$out"
test -f "$archive"

echo "===== VERIFY TWO PINNED BUILD BUNDLES ====="

for bundle in "$a" "$b"; do
  test -d "$bundle"
  (
    cd "$bundle"
    sha256sum -c SHA256SUMS
  )

  mapfile -t files < <(
    find "$bundle" -maxdepth 1 -type f \
      -printf '%f\n' | sort
  )

  test "${#files[@]}" -eq 4
done

mapfile -t packages < <(
  find "$a" -maxdepth 1 -type f \
    -name 'ipod-sync_*_amd64.deb' -print | sort
)

test "${#packages[@]}" -eq 1

package="$(basename "${packages[0]}")"
sbom="${package%.deb}.spdx.json"

test -f "$a/$sbom"
test -f "$a/PROVENANCE.json"

for name in \
  "$package" \
  "$sbom" \
  PROVENANCE.json \
  SHA256SUMS
do
  cmp -s "$a/$name" "$b/$name" || {
    echo "ERROR: A/B mismatch: $name" >&2
    exit 1
  }
done

echo "Pinned A/B package bundles: BYTE-IDENTICAL"

echo "===== VERIFY BUILD MATERIALS ====="

cmp -s \
  "$materials/builder-a.json" \
  "$materials/builder-b.json"

cmp -s \
  "$materials/toolchain-a.json" \
  "$materials/toolchain-b.json"

python3 - \
  "$materials/builder-a.json" \
  "$archive" \
  "$GITHUB_SHA" \
  "$(git log -1 --format=%ct)" \
  "$IMAGE" \
  "$SNAPSHOT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

manifest_path, archive_path, commit, epoch, image, snapshot = (
    sys.argv[1:]
)

manifest = json.loads(Path(manifest_path).read_text())

assert manifest["schema"] == "open-ipod-sync-build-materials-v1"

actual_sha = hashlib.sha256(
    Path(archive_path).read_bytes()
).hexdigest()

assert manifest["source"] == {
    "archive_sha256": actual_sha,
    "commit": commit,
    "source_date_epoch": int(epoch),
}

environment = manifest["declared_environment"]

assert environment["base_image_identity"] == image
assert environment["snapshot_identity"] == (
    "ubuntu-26.04-snapshot-" + snapshot
)

observed = manifest["observed_environment"]
assert observed["architecture"] == "amd64"
assert len(observed["build_packages"]) >= 20

print("Source archive identity: PASS")
print("Pinned OCI identity: PASS")
print("Pinned APT snapshot identity: PASS")
print("Observed build package materials: PASS")
PY

echo "===== VERIFY DEBIAN PACKAGE ARCHITECTURE ====="

test "$(
  dpkg-deb -f "$a/$package" Architecture
)" = amd64

echo "===== ASSEMBLE CANONICAL CANDIDATE ====="

mkdir -p "$out"

cp -- "$a/$package" "$out/"
cp -- "$a/$sbom" "$out/"
cp -- "$a/PROVENANCE.json" "$out/"

cp -- "$archive" \
  "$out/open-ipod-sync-${GITHUB_SHA}-source.tar"

cp -- "$materials/builder-a.json" \
  "$out/BUILD-MATERIALS.json"

cp -- "$materials/toolchain-a.json" \
  "$out/TOOLCHAIN.json"

(
  cd "$out"

  mapfile -t names < <(
    find . -maxdepth 1 -type f \
      -printf '%f\n' | sort
  )

  test "${#names[@]}" -eq 6

  sha256sum "${names[@]}" > SHA256SUMS
  sha256sum -c SHA256SUMS

  test "$(
    find . -maxdepth 1 -type f | wc -l
  )" -eq 7
)

echo "===== PRIVACY SCAN ====="

python3 tools/privacy-scan.py "$out"

echo "===== VERIFIED PINNED CANDIDATE ====="
echo "Pinned A/B comparison: PASS"
echo "Build materials: PASS"
echo "Toolchain evidence: PASS"
echo "Source identity: PASS"
echo "Checksum integrity: PASS"
echo "Privacy boundary: PASS"
echo "Candidate prepared: $out"
