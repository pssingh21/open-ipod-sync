#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_WORKSPACE:?CI workspace required}"
: "${RUNNER_TEMP:?CI temporary directory required}"
: "${GITHUB_SHA:?CI commit required}"

IMAGE="docker.io/library/ubuntu@sha256:88a381d5b5eeb2b35d3ad70925a362c37ce569daf43ede89ff818ec20e4d3794"
SNAPSHOT="20261015T000000Z"
CA="/etc/ssl/certs/ca-certificates.crt"

[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
test -s "$CA"
test -d "$GITHUB_WORKSPACE"

cd "$GITHUB_WORKSPACE"

test "$(git rev-parse HEAD)" = "$GITHUB_SHA"

epoch="$(git log -1 --format=%ct)"
root="$RUNNER_TEMP/ubuntu2604-pinned-matrix"

test ! -e "$root"
mkdir -p "$root/input" "$root/matrix"

echo "===== PREPARE IMMUTABLE SOURCE ARCHIVE ====="

./tools/make-source-archive.sh \
  "$root/input/source.tar" "$GITHUB_SHA"

sha256sum "$root/input/source.tar"

echo "===== BUILD INPUT IDENTITIES ====="

printf 'OCI image: %s\n' "$IMAGE"
printf 'APT snapshot: %s\n' "$SNAPSHOT"
printf 'commit: %s\n' "$GITHUB_SHA"
printf 'source epoch: %s\n' "$epoch"

echo "Runner CA bundle:"
sha256sum "$CA"

echo "===== START PINNED UBUNTU BUILDER ====="

docker run \
  --rm \
  --pull=always \
  --platform linux/amd64 \
  --network bridge \
  --mount "type=bind,source=${GITHUB_WORKSPACE},target=/repo,readonly" \
  --mount "type=bind,source=${root},target=/work" \
  --mount "type=bind,source=${CA},target=/tmp/bootstrap-ca.crt,readonly" \
  -i \
  "$IMAGE" \
  bash -s -- "$SNAPSHOT" "$GITHUB_SHA" "$epoch" "$IMAGE" <<'CONTAINER'
set -euo pipefail

snapshot="$1"
commit="$2"
epoch="$3"
image="$4"
ca="/tmp/bootstrap-ca.crt"

. /etc/os-release
test "$ID" = ubuntu
test "$VERSION_ID" = 26.04
test "$(dpkg --print-architecture)" = amd64
test -s "$ca"

echo "===== EXCLUSIVE SIGNED SNAPSHOT SOURCES ====="

test -f /usr/share/keyrings/ubuntu-archive-keyring.gpg

rm -f /etc/apt/sources.list

find /etc/apt/sources.list.d \
  -maxdepth 1 -type f \
  \( -name '*.list' -o -name '*.sources' \) \
  -delete

cat > /etc/apt/sources.list.d/ubuntu.sources <<APT
Types: deb
URIs: https://snapshot.ubuntu.com/ubuntu/${snapshot}
Suites: resolute resolute-updates resolute-security
Components: main universe restricted multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
APT

rm -rf /var/lib/apt/lists/*
mkdir -p /var/lib/apt/lists/partial

echo "===== STRICT SNAPSHOT UPDATE ====="

apt-get \
  -o Acquire::Retries=3 \
  -o Acquire::https::CaInfo="$ca" \
  -o APT::Update::Error-Mode=any \
  update 2>&1 | tee /tmp/apt-update.log

if grep -Eq '^(Err:|W:|E:)' /tmp/apt-update.log
then
  echo "ERROR: APT snapshot update failed" >&2
  exit 1
fi

for suite in resolute resolute-updates resolute-security
do
  grep -Eq \
    "^(Get|Hit):[0-9]+ https://snapshot[.]ubuntu[.]com/ubuntu/${snapshot}[[:space:]]+${suite}[[:space:]]+InRelease([[:space:]]|$)" \
    /tmp/apt-update.log || {
      echo "ERROR: missing verified snapshot: $suite" >&2
      exit 1
    }
done

apt-cache policy > /tmp/apt-policy.log

grep -F \
  "https://snapshot.ubuntu.com/ubuntu/${snapshot}" \
  /tmp/apt-policy.log >/dev/null

echo "APT snapshot verification: PASS"

echo "===== INSTALL SNAPSHOT BUILD DEPENDENCIES ====="

export DEBIAN_FRONTEND=noninteractive

apt-get \
  -o Acquire::Retries=3 \
  -o Acquire::https::CaInfo="$ca" \
  install -y --no-install-recommends \
    ca-certificates git bash python3 \
    build-essential dpkg-dev pkg-config \
    intltool gettext libglib2.0-dev \
    libsqlite3-dev libimobiledevice-dev \
    libplist-dev libxml2-dev zlib1g-dev \
    libusb-1.0-0-dev file tar xz-utils

echo "===== OBSERVED PACKAGE VERSIONS ====="

dpkg-query -W \
  -f='${binary:Package} ${Version}\n' \
  | LC_ALL=C sort \
  > /work/matrix/installed-packages.txt

sha256sum /work/matrix/installed-packages.txt

echo "===== EXECUTE ISOLATED A/B BUILDS ====="

# Existing matrix enforces kernel-level socket denial,
# toolchain allowlisting, no-.git builds, package audits,
# and byte-for-byte comparison.
#
# The repository is mounted read-only; build output is
# confined to the temporary work directory.

bash /repo/tools/run-reproducibility-matrix.sh \
  /work/input/source.tar \
  "$commit" \
  "$epoch" \
  /work/matrix/results \
  "ubuntu-26.04-snapshot-${snapshot}" \
  "$image" \
  ubuntu-26.04-amd64

echo "===== PINNED A/B REPRODUCIBILITY: PASS ====="
CONTAINER

echo "===== SCAN PINNED BUILD EVIDENCE ====="

python3 tools/privacy-scan.py \
  "$root/matrix/results/builder-a" \
  "$root/matrix/results/builder-b" \
  "$root/matrix/results/materials"

echo "===== PINNED UBUNTU MATRIX ====="
echo "source archive: PASS"
echo "snapshot package installation: PASS"
echo "isolated A/B builds: PASS"
echo "supply-chain comparison: PASS"
echo "privacy boundary: PASS"
