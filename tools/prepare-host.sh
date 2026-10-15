#!/bin/bash
set -euo pipefail

ROOT="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &&
    pwd
)"

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

IFUSE_TAG="1.2.1"
IFUSE_RELEASE_COMMIT_SHORT="f7eac74"
IFUSE_REPOSITORY="https://github.com/libimobiledevice/ifuse.git"


die() {
    echo "ERROR: $*" >&2
    exit 2
}


if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "run this host-preparation step as root: sudo ./tools/prepare-host.sh"
fi


command -v apt-get >/dev/null 2>&1 ||
    die "apt-get is required; this helper supports Debian/Ubuntu hosts"

command -v dpkg-query >/dev/null 2>&1 ||
    die "dpkg-query is required; this helper supports Debian/Ubuntu hosts"


echo "========================================================================"
echo "open-ipod-sync host preparation"
echo "========================================================================"


echo
echo "===== SAFETY: NO ACTIVE IFUSE MOUNT ====="

if command -v findmnt >/dev/null 2>&1 &&
   findmnt -rn -t fuse.ifuse 2>/dev/null |
       grep -q .
then
    echo "REFUSED: an ifuse filesystem is currently mounted." >&2
    echo "Unmount the iPod before replacing or changing ifuse." >&2
    exit 2
fi

echo "active ifuse mounts: NONE"


echo
echo "===== INSTALL DEBIAN / UBUNTU DEPENDENCIES ====="

export DEBIAN_FRONTEND=noninteractive

apt-get update

apt-get install \
    -y \
    --no-install-recommends \
    ca-certificates \
    git \
    bash \
    python3 \
    build-essential \
    dpkg-dev \
    pkg-config \
    intltool \
    gettext \
    autoconf \
    automake \
    libtool-bin \
    libglib2.0-dev \
    libsqlite3-dev \
    libimobiledevice-dev \
    libplist-dev \
    libxml2-dev \
    zlib1g-dev \
    libusb-1.0-0-dev \
    libfuse3-dev \
    ifuse \
    libimobiledevice-utils \
    usbmuxd \
    ffmpeg \
    util-linux


echo
echo "===== INSPECT ACTIVE IFUSE ====="

ACTIVE_IFUSE="$(
    command -v ifuse ||
    true
)"

[[ -n "$ACTIVE_IFUSE" ]] ||
    die "ifuse is unavailable after dependency installation"

ACTIVE_IFUSE_REAL="$(
    readlink -f "$ACTIVE_IFUSE"
)"

echo "active binary: $ACTIVE_IFUSE"
echo "resolved:      $ACTIVE_IFUSE_REAL"

SELF_OUTPUT="$(
    "$ACTIVE_IFUSE" --version 2>&1 ||
    true
)"

echo "self report:"
printf '%s\n' "$SELF_OUTPUT"

SELF_VERSION=""

if [[ "$SELF_OUTPUT" =~ ([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    SELF_VERSION="${BASH_REMATCH[1]}"
fi


NEEDS_SAFE_IFUSE=0
REASON=""


if [[ "$SELF_VERSION" == "1.2.0" ]]; then
    NEEDS_SAFE_IFUSE=1
    REASON="active binary reports known-unsafe ifuse 1.2.0"

elif [[ -n "$SELF_VERSION" ]]; then
    echo
    echo "active ifuse version: $SELF_VERSION"
    echo "known-unsafe 1.2.0:   ABSENT"
    echo
    echo "HOST PREPARATION: PASS"
    exit 0

elif [[ "$ACTIVE_IFUSE_REAL" == "/usr/bin/ifuse" ]]; then
    PACKAGE_VERSION="$(
        dpkg-query \
            -W \
            -f='${Version}' \
            ifuse \
            2>/dev/null ||
        true
    )"

    echo
    echo "Debian package version: $PACKAGE_VERSION"

    UPSTREAM_PACKAGE_VERSION="${PACKAGE_VERSION#*:}"

    case "$UPSTREAM_PACKAGE_VERSION" in
        1.2.0|1.2.0-*|1.2.0+*|1.2.0~*)
            NEEDS_SAFE_IFUSE=1
            REASON="Debian/Ubuntu package is known-unsafe ifuse 1.2.0"
            ;;
        *)
            die \
                "ifuse version output is not parseable and package metadata " \
                "does not identify the known-unsafe 1.2.0 release"
            ;;
    esac

else
    die \
        "ifuse version output is not parseable for non-distro binary: " \
        "$ACTIVE_IFUSE_REAL"
fi


[[ "$NEEDS_SAFE_IFUSE" -eq 1 ]] ||
    die "internal host-preparation state error"


echo
echo "===== REMEDIATE KNOWN-UNSAFE IFUSE ====="

echo "$REASON"
echo "Installing pinned upstream ifuse $IFUSE_TAG into /usr/local."


WORK="$(
    mktemp \
        -d \
        /tmp/open-ipod-sync-ifuse.XXXXXX
)"

cleanup() {
    rm -rf -- "$WORK"
}

trap cleanup EXIT


git clone \
    --depth 1 \
    --branch "$IFUSE_TAG" \
    "$IFUSE_REPOSITORY" \
    "$WORK/ifuse"


ACTUAL_COMMIT="$(
    git \
        -C "$WORK/ifuse" \
        rev-parse \
        --short=7 \
        HEAD
)"

echo "expected release commit: $IFUSE_RELEASE_COMMIT_SHORT"
echo "actual release commit:   $ACTUAL_COMMIT"

[[ "$ACTUAL_COMMIT" == "$IFUSE_RELEASE_COMMIT_SHORT" ]] ||
    die \
        "upstream ifuse $IFUSE_TAG resolved to unexpected commit: " \
        "$ACTUAL_COMMIT"


echo
echo "===== BUILD PINNED IFUSE ====="

cd "$WORK/ifuse"

./autogen.sh \
    --prefix=/usr/local

make \
    -j"$(nproc)"

make install

ldconfig

hash -r


echo
echo "===== VERIFY SAFE IFUSE ====="

[[ -x /usr/local/bin/ifuse ]] ||
    die "/usr/local/bin/ifuse was not installed"

FINAL_OUTPUT="$(
    /usr/local/bin/ifuse \
        --version \
        2>&1
)"

printf '%s\n' "$FINAL_OUTPUT"

if ! grep -Eq \
    '(^|[^0-9])1\.2\.1([^0-9]|$)' \
    <<<"$FINAL_OUTPUT"
then
    die "installed /usr/local/bin/ifuse does not report 1.2.1"
fi


FINAL_ACTIVE="$(
    command -v ifuse
)"

FINAL_ACTIVE_REAL="$(
    readlink -f "$FINAL_ACTIVE"
)"

echo
echo "active binary after remediation: $FINAL_ACTIVE"
echo "resolved binary:                 $FINAL_ACTIVE_REAL"

[[ "$FINAL_ACTIVE_REAL" == "/usr/local/bin/ifuse" ]] ||
    die \
        "safe /usr/local/bin/ifuse is not first in the active PATH"


DISTRO_VERSION="$(
    dpkg-query \
        -W \
        -f='${Version}' \
        ifuse \
        2>/dev/null ||
    true
)"

echo "distro ifuse package retained:  $DISTRO_VERSION"


echo
echo "========================================================================"
echo "HOST PREPARATION: PASS"
echo "========================================================================"

echo
echo "Safe active runtime:"
echo "  /usr/local/bin/ifuse"
echo "  version 1.2.1"
echo
echo "The distro ifuse package remains installed for normal package dependency"
echo "resolution, but /usr/local/bin/ifuse takes precedence at runtime."
