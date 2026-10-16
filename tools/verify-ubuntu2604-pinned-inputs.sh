#!/usr/bin/env bash
set -euo pipefail

IMAGE="docker.io/library/ubuntu@sha256:88a381d5b5eeb2b35d3ad70925a362c37ce569daf43ede89ff818ec20e4d3794"
SNAPSHOT="20261015T000000Z"

command -v docker >/dev/null

echo "===== VERIFY PINNED OCI IMAGE ====="
echo "image: $IMAGE"
echo "snapshot: $SNAPSHOT"

docker run \
  --rm \
  --pull=always \
  --platform linux/amd64 \
  --network bridge \
  -i \
  "$IMAGE" \
  bash -s -- "$SNAPSHOT" <<'CONTAINER'
set -euo pipefail

snapshot="$1"

echo "===== VERIFY IMAGE IDENTITY ====="

. /etc/os-release

test "$ID" = ubuntu
test "$VERSION_ID" = 26.04
test "$(dpkg --print-architecture)" = amd64
test "$(id -u)" = 0

echo "Ubuntu 26.04 amd64: PASS"

echo "===== CONFIGURE PINNED APT SNAPSHOT ====="

test -f /usr/share/keyrings/ubuntu-archive-keyring.gpg

# All changes are confined to this disposable container.
rm -f /etc/apt/sources.list
find /etc/apt/sources.list.d \
  -maxdepth 1 \
  -type f \
  \( -name '*.list' -o -name '*.sources' \) \
  -delete

cat > /etc/apt/sources.list.d/ubuntu.sources <<APT
Types: deb
URIs: http://archive.ubuntu.com/ubuntu
Suites: resolute resolute-updates
Components: main universe restricted multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
Snapshot: ${snapshot}

Types: deb
URIs: http://security.ubuntu.com/ubuntu
Suites: resolute-security
Components: main universe restricted multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
Snapshot: ${snapshot}
APT

echo "===== VALIDATE SNAPSHOT INDEXES ====="

apt-get \
  -o Acquire::Retries=5 \
  update 2>&1 | tee /tmp/apt-snapshot-update.log

# Require each configured pocket to resolve through the
# actual Ubuntu snapshot service, not a live repository.
for suite in \
  resolute \
  resolute-updates \
  resolute-security
do
  if ! grep -E \
    "snapshot[.]ubuntu[.]com/ubuntu/${snapshot}[[:space:]]+${suite}[[:space:]]" \
    /tmp/apt-snapshot-update.log
  then
    echo "ERROR: snapshot not verified for $suite" >&2
    exit 1
  fi
done

echo "all three snapshot pockets: PASS"

echo "===== INSTALL BUILD DEPENDENCIES ====="

export DEBIAN_FRONTEND=noninteractive

apt-get install -y --no-install-recommends \
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
echo "Pinned image: PASS"
echo "Signed APT snapshot: PASS"
echo "Build dependency installation: PASS"
CONTAINER

echo "===== PINNED BUILD INPUTS VERIFIED ====="
