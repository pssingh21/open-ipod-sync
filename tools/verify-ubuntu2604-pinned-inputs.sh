#!/usr/bin/env bash
set -euo pipefail

IMAGE="docker.io/library/ubuntu@sha256:88a381d5b5eeb2b35d3ad70925a362c37ce569daf43ede89ff818ec20e4d3794"
SNAPSHOT="20261015T000000Z"

# Bootstrap TLS trust from the CI runner.
# This is a preflight dependency, not yet a hermetically
# pinned component of the eventual build environment.
HOST_CA="/etc/ssl/certs/ca-certificates.crt"
CONTAINER_CA="/tmp/bootstrap-ca-certificates.crt"

command -v docker >/dev/null
test -s "$HOST_CA"

echo "===== VERIFY PINNED OCI IMAGE ====="
echo "image: $IMAGE"
echo "snapshot: $SNAPSHOT"

echo "===== BOOTSTRAP CA IDENTITY ====="
sha256sum "$HOST_CA"

docker run \
  --rm \
  --pull=always \
  --platform linux/amd64 \
  --network bridge \
  --mount "type=bind,source=${HOST_CA},target=${CONTAINER_CA},readonly" \
  -i \
  "$IMAGE" \
  bash -s -- "$SNAPSHOT" <<'CONTAINER'
set -euo pipefail

snapshot="$1"
ca="/tmp/bootstrap-ca-certificates.crt"

echo "===== VERIFY IMAGE IDENTITY ====="

. /etc/os-release

test "$ID" = ubuntu
test "$VERSION_ID" = 26.04
test "$(dpkg --print-architecture)" = amd64
test "$(id -u)" = 0
test -s "$ca"

echo "Ubuntu 26.04 amd64: PASS"

echo "===== CONFIGURE EXCLUSIVE SNAPSHOT SOURCE ====="

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

# Prevent stale package indexes from masking a failure.
rm -rf /var/lib/apt/lists/*
mkdir -p /var/lib/apt/lists/partial

echo "===== VALIDATE SNAPSHOT INDEXES ====="

# Strict mode turns partial index failures into nonzero exits.
# TLS verification and signed Release checks remain enabled.
apt-get \
  -o Acquire::Retries=3 \
  -o Acquire::https::CaInfo="$ca" \
  -o APT::Update::Error-Mode=any \
  update 2>&1 | tee /tmp/apt-snapshot-update.log

# Explicitly reject any index acquisition error or warning.
if grep -Eq '^(Err:|W:|E:)' \
  /tmp/apt-snapshot-update.log
then
  echo "ERROR: APT reported a snapshot failure" >&2
  exit 1
fi

# Reject unintended successful live-mirror fetches.
if grep -Eq \
  '^(Get|Hit):[0-9]+ https?://(archive|security)[.]ubuntu[.]com/' \
  /tmp/apt-snapshot-update.log
then
  echo "ERROR: live Ubuntu repository used" >&2
  exit 1
fi

# A successful Get or Hit is required for every pocket.
# Ign and Err entries must never count as success.
for suite in \
  resolute \
  resolute-updates \
  resolute-security
do
  if ! grep -Eq \
    "^(Get|Hit):[0-9]+ https://snapshot[.]ubuntu[.]com/ubuntu/${snapshot}[[:space:]]+${suite}[[:space:]]+InRelease([[:space:]]|$)" \
    /tmp/apt-snapshot-update.log
  then
    echo "ERROR: verified InRelease missing: $suite" >&2
    exit 1
  fi

  echo "$suite snapshot InRelease: PASS"
done

# Confirm that the selected package indexes are sourced
# from the requested snapshot.
apt-cache policy > /tmp/apt-snapshot-policy.log

grep -F \
  "https://snapshot.ubuntu.com/ubuntu/${snapshot}" \
  /tmp/apt-snapshot-policy.log >/dev/null

echo "all three snapshot pockets: PASS"

echo "===== INSTALL BUILD DEPENDENCIES ====="

export DEBIAN_FRONTEND=noninteractive

apt-get \
  -o Acquire::Retries=3 \
  -o Acquire::https::CaInfo="$ca" \
  install -y --no-install-recommends \
    ca-certificates \
    git \
    bash \
    python3 \
    build-essential \
    dpkg-dev \
    pkg-config \
    intltool \
    gettext \
    libglib2.0-dev \
    libsqlite3-dev \
    libimobiledevice-dev \
    libplist-dev \
    libxml2-dev \
    zlib1g-dev \
    libusb-1.0-0-dev \
    file \
    tar \
    xz-utils

echo "===== CAPTURE OBSERVED TOOLCHAIN ====="

dpkg-query -W \
  -f='${binary:Package} ${Version}\n' \
  | LC_ALL=C sort \
  > /tmp/installed-packages.txt

sha256sum /tmp/installed-packages.txt

python3 --version
gcc --version | head -n 1
dpkg-deb --version | head -n 1

echo "===== SNAPSHOT PREFLIGHT ====="
echo "Pinned OCI image: PASS"
echo "Signed APT snapshot: PASS"
echo "Build dependency installation: PASS"
CONTAINER

echo "===== PINNED BUILD INPUTS VERIFIED ====="
