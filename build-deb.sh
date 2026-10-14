#!/bin/bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Reproducible package timestamp.
#
# Respect an externally supplied SOURCE_DATE_EPOCH first.
#
# In a Git checkout, the commit timestamp is authoritative. Never silently
# fall back to checkout/file mtimes if Git metadata is present, because those
# mtimes depend on when the checkout happened.
#
# A source archive has no .git metadata, so in that case use the archived
# build script's mtime. git archive preserves commit timestamps.
if [[ -z "${SOURCE_DATE_EPOCH:-}" ]]; then
  if [[ -e "$ROOT/.git" ]]; then
    command -v git >/dev/null 2>&1 || {
      echo "ERROR: Git checkout present but git is unavailable" >&2
      exit 1
    }

    if ! SOURCE_DATE_EPOCH="$(git -C "$ROOT" log -1 --format=%ct)"; then
      echo "ERROR: Git checkout present but commit timestamp could not be read" >&2
      exit 1
    fi
  else
    SOURCE_DATE_EPOCH="$(stat -c '%Y' "$ROOT/build-deb.sh")"
  fi
fi

[[ "$SOURCE_DATE_EPOCH" =~ ^[0-9]+$ ]] || {
  echo "ERROR: invalid SOURCE_DATE_EPOCH: $SOURCE_DATE_EPOCH" >&2
  exit 1
}

export SOURCE_DATE_EPOCH

echo "Build SOURCE_DATE_EPOCH: $SOURCE_DATE_EPOCH"
echo "Build timestamp UTC: $(date -u --date="@${SOURCE_DATE_EPOCH}" '+%Y-%m-%dT%H:%M:%SZ')"
[[ -f "$ROOT/vendor/ipodctl/cdb.py" ]] || { echo "ERROR: capture components first" >&2; exit 1; }
[[ -d "$ROOT/third_party/libgpod-patched-source/src" ]] || { echo "ERROR: captured patched libgpod source missing" >&2; exit 1; }
[[ -f "$ROOT/native/rijndael.c" && -f "$ROOT/native/rijndael.h" ]] || { echo "ERROR: captured rijndael sources missing" >&2; exit 1; }

for cmd in dpkg-deb gcc g++ make pkg-config python3 intltool-update msgfmt strip; do
  command -v "$cmd" >/dev/null || {
    echo "ERROR: missing build command: $cmd" >&2
    echo "Debian/Ubuntu build prerequisites include: build-essential dpkg-dev pkg-config intltool gettext" >&2
    exit 1
  }
done
for mod in glib-2.0 gobject-2.0 sqlite3 libimobiledevice-1.0 libxml-2.0; do
  pkg-config --exists "$mod" || { echo "ERROR: missing development module: $mod" >&2; exit 1; }
done
if ! pkg-config --exists libplist && ! pkg-config --exists libplist-2.0; then
  echo "ERROR: missing libplist development pkg-config module" >&2
  exit 1
fi
printf '#include <zlib.h>\nint main(void){return 0;}\n' | gcc -x c - -lz -o /tmp/ipod-sync-zlib-check
rm -f /tmp/ipod-sync-zlib-check

ARCH="$(dpkg --print-architecture)"
[[ "$ARCH" == "amd64" ]] || echo "WARNING: only Debian 11 amd64 has been validated so far; building for $ARCH"
VER="0.2.0~alpha4"
PKG="ipod-sync_${VER}_${ARCH}"
BUILD="$ROOT/build/$PKG"
LIBSRC="$ROOT/build/libgpod-src"
RUNTIME_PREFIX="/usr/lib/ipod-sync/vendor/libgpod"
rm -rf "$ROOT/build" "$ROOT/dist"
mkdir -p "$BUILD/DEBIAN" "$BUILD/usr/bin" "$BUILD/usr/lib/ipod-sync/native" \
         "$BUILD/usr/lib/ipod-sync/ipodctl" "$BUILD/usr/share/doc/ipod-sync" "$ROOT/dist" "$LIBSRC"

# Build libgpod from the captured modified source. Nothing from the historical
# compiled prefix is reused, preventing development-home paths from leaking.
tar -C "$ROOT/third_party/libgpod-patched-source" -cf - . | tar -C "$LIBSRC" -xf -
(
  cd "$LIBSRC"
  args=(
    "--prefix=$RUNTIME_PREFIX"
    --enable-shared --disable-static
    --disable-gdk-pixbuf --disable-pygobject
    --disable-udev --without-hal --with-libimobiledevice
    --disable-more-warnings --disable-gtk-doc
  )
  help="$(./configure --help 2>/dev/null || true)"
  grep -q -- '--without-python' <<<"$help" && args+=(--without-python)
  grep -q -- '--without-mono' <<<"$help" && args+=(--without-mono)
  # Prevent development-machine source/build paths from entering DWARF,
  # __FILE__ strings, or other compiler metadata in the public ELF.
  MAP_TO=/usr/src/ipod-sync/libgpod
  COMMON_MAP_FLAGS="-ffile-prefix-map=$ROOT=/usr/src/ipod-sync -fdebug-prefix-map=$ROOT=/usr/src/ipod-sync -fmacro-prefix-map=$ROOT=/usr/src/ipod-sync"
  CFLAGS="-O2 -g0 $COMMON_MAP_FLAGS" \
  CXXFLAGS="-O2 -g0 $COMMON_MAP_FLAGS" \
    ./configure "${args[@]}"
  make -C src -j"${IPOD_SYNC_BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}"
  make -C src DESTDIR="$BUILD" install
)

LIBP="$BUILD$RUNTIME_PREFIX"
[[ -f "$LIBP/include/gpod-1.0/gpod/itdb.h" ]] || { echo "ERROR: source-built libgpod header missing" >&2; exit 1; }
compgen -G "$LIBP/lib/libgpod.so*" >/dev/null || { echo "ERROR: source-built libgpod shared library missing" >&2; exit 1; }
find "$LIBP" -name '*.la' -delete
# Strip public shared objects after installation. Symlinks remain intact.
while IFS= read -r -d '' so; do
  strip --strip-unneeded "$so"
done < <(find "$LIBP/lib" -type f -name 'libgpod.so*' -print0)

install -m0755 "$ROOT/src/ipod_sync.py" "$BUILD/usr/lib/ipod-sync/ipod_sync.py"
install -m0644 "$ROOT/vendor/ipodctl/cdb.py" "$BUILD/usr/lib/ipod-sync/ipodctl/cdb.py"
install -m0644 "$ROOT/vendor/ipodctl/__init__.py" "$BUILD/usr/lib/ipod-sync/ipodctl/__init__.py"
install -m0644 "$ROOT/native/sign-cdb.c" "$BUILD/usr/lib/ipod-sync/native/sign-cdb.c"
install -m0644 "$ROOT/native/rijndael.c" "$BUILD/usr/lib/ipod-sync/native/rijndael.c"
install -m0644 "$ROOT/native/rijndael.h" "$BUILD/usr/lib/ipod-sync/native/rijndael.h"

# Device-generic sync envelope.
gcc -O2 -g0 -Wall -Wextra \
  -ffile-prefix-map="$ROOT"=/usr/src/ipod-sync \
  -fdebug-prefix-map="$ROOT"=/usr/src/ipod-sync \
  -fmacro-prefix-map="$ROOT"=/usr/src/ipod-sync \
  "$ROOT/native/sync-envelope.c" \
  $(pkg-config --cflags --libs libimobiledevice-1.0) \
  -o "$BUILD/usr/lib/ipod-sync/native/sync-envelope"
strip --strip-unneeded "$BUILD/usr/lib/ipod-sync/native/sync-envelope"
chmod 0755 "$BUILD/usr/lib/ipod-sync/native/sync-envelope"

cat > "$BUILD/usr/bin/ipod-sync" <<'WRAP'
#!/bin/bash
set -euo pipefail
CONFIG=/etc/ipod-sync/config.env
[[ -r "$CONFIG" ]] && source "$CONFIG"
: "${IPOD_SYNC_SOURCE:=/mnt/music}"
: "${IPOD_SYNC_MOUNT:=$HOME/ipod}"
APP=/usr/lib/ipod-sync/ipod_sync.py

mount_info() { findmnt -n -M "$IPOD_SYNC_MOUNT" -o FSTYPE,OPTIONS 2>/dev/null || true; }
ensure_ro_mount() {
  mkdir -p "$IPOD_SYNC_MOUNT"
  if mountpoint -q "$IPOD_SYNC_MOUNT"; then
    local info fstype opts
    info="$(mount_info)"; fstype="${info%% *}"; opts="${info#* }"
    [[ "$fstype" == "fuse.ifuse" ]] || { echo "REFUSED: $IPOD_SYNC_MOUNT is mounted as $fstype, not fuse.ifuse" >&2; exit 2; }
    [[ ",$opts," == *,ro,* ]] || { echo "REFUSED: existing iPod mount is not read-only: $opts" >&2; exit 2; }
    return 0
  fi
  mapfile -t ids < <(idevice_id -l)
  [[ "${#ids[@]}" -eq 1 ]] || { echo "REFUSED: expected exactly one connected iOS device; found ${#ids[@]}" >&2; exit 2; }
  idevicepair validate >/dev/null
  ifuse "$IPOD_SYNC_MOUNT" -o ro
  local info fstype opts
  info="$(mount_info)"; fstype="${info%% *}"; opts="${info#* }"
  [[ "$fstype" == "fuse.ifuse" && ",$opts," == *,ro,* ]] || { echo "ERROR: failed to establish read-only ifuse mount" >&2; exit 2; }
  echo "iPod mounted read-only: $IPOD_SYNC_MOUNT"
}

cmd="${1:-plan}"; [[ $# -gt 0 ]] && shift || true
case "$cmd" in
  version|--version|-V) exec python3 "$APP" --version ;;
  mount-ro) ensure_ro_mount; findmnt -M "$IPOD_SYNC_MOUNT" -o TARGET,FSTYPE,OPTIONS ;;
  unmount)
    if mountpoint -q "$IPOD_SYNC_MOUNT"; then
      info="$(mount_info)"; [[ "${info%% *}" == "fuse.ifuse" ]] || { echo "REFUSED: not an ifuse mount" >&2; exit 2; }
      fusermount -u "$IPOD_SYNC_MOUNT"; echo "iPod unmounted: $IPOD_SYNC_MOUNT"
    else echo "iPod is not mounted."; fi ;;
  plan) ensure_ro_mount; exec python3 "$APP" --source "$IPOD_SYNC_SOURCE" --mount "$IPOD_SYNC_MOUNT" "$@" ;;
  sync)
    found=0; for x in "$@"; do [[ "$x" == "--apply" ]] && found=1; done
    [[ "$found" -eq 1 ]] || { echo "REFUSED: live sync requires explicit: ipod-sync sync --apply" >&2; exit 2; }
    ensure_ro_mount; exec python3 "$APP" --source "$IPOD_SYNC_SOURCE" --mount "$IPOD_SYNC_MOUNT" "$@" ;;
  recover-check) ensure_ro_mount; exec python3 "$APP" --mount "$IPOD_SYNC_MOUNT" --recover-check "$@" ;;
  recover) ensure_ro_mount; exec python3 "$APP" --mount "$IPOD_SYNC_MOUNT" --recover "$@" ;;
  doctor)
    echo "ipod-sync 0.2.0-alpha.4 doctor"; echo "source: $IPOD_SYNC_SOURCE"; echo "mount:  $IPOD_SYNC_MOUNT"
    fail=0
    for x in python3 ifuse fusermount mountpoint findmnt idevice_id idevicepair ffmpeg ffprobe gcc pkg-config; do
      command -v "$x" >/dev/null && echo "  $x: PASS" || { echo "  $x: MISSING"; fail=1; }
    done
    for p in /usr/lib/ipod-sync/native/sync-envelope /usr/lib/ipod-sync/native/sign-cdb.c \
             /usr/lib/ipod-sync/native/rijndael.c /usr/lib/ipod-sync/ipodctl/cdb.py \
             /usr/lib/ipod-sync/vendor/libgpod/include/gpod-1.0/gpod/itdb.h; do
      [[ -e "$p" ]] && echo "  $(basename "$p"): PASS" || { echo "  $p: MISSING"; fail=1; }
    done
    compgen -G '/usr/lib/ipod-sync/vendor/libgpod/lib/libgpod.so*' >/dev/null && echo "  patched libgpod: PASS" || { echo "  patched libgpod: MISSING"; fail=1; }
    exit "$fail" ;;
  raw) exec python3 "$APP" "$@" ;;
  *)
    cat >&2 <<'USAGE'
usage:
  ipod-sync version
  ipod-sync doctor
  ipod-sync mount-ro
  ipod-sync unmount
  ipod-sync plan
  ipod-sync sync --apply
  ipod-sync recover-check
  ipod-sync recover
USAGE
    exit 2 ;;
esac
WRAP
chmod 0755 "$BUILD/usr/bin/ipod-sync"

cat > "$BUILD/DEBIAN/preinst" <<'PREINST'
#!/bin/sh
set -e
if [ -f /etc/ipod-sync/config.env ]; then
  mkdir -p /var/lib/ipod-sync
  cp -p /etc/ipod-sync/config.env /var/lib/ipod-sync/config.env.preupgrade
fi
exit 0
PREINST
chmod 0755 "$BUILD/DEBIAN/preinst"
cat > "$BUILD/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
mkdir -p /etc/ipod-sync /var/lib/ipod-sync
if [ -f /var/lib/ipod-sync/config.env.preupgrade ]; then
  cp -p /var/lib/ipod-sync/config.env.preupgrade /etc/ipod-sync/config.env
  rm -f /var/lib/ipod-sync/config.env.preupgrade
elif [ ! -e /etc/ipod-sync/config.env ]; then
  cat > /etc/ipod-sync/config.env <<'CONF'
# Source directory MUST itself be a dedicated filesystem mount, kernel-mounted read-only.
IPOD_SYNC_SOURCE=/mnt/music
# ifuse mount point. ipod-sync normally keeps it read-only.
IPOD_SYNC_MOUNT=$HOME/ipod
CONF
  chmod 0644 /etc/ipod-sync/config.env
fi
exit 0
POSTINST
chmod 0755 "$BUILD/DEBIAN/postinst"

cat > "$BUILD/DEBIAN/control" <<CONTROL
Package: ipod-sync
Version: $VER
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: ipod-sync project
Depends: python3, ifuse, libimobiledevice-utils, usbmuxd, ffmpeg, gcc, pkg-config, libglib2.0-dev, util-linux, libc6, libglib2.0-0, libimobiledevice6, libplist3, libsqlite3-0, libxml2, zlib1g, libusb-1.0-0
Description: Experimental ADD-only music sync for legacy iPod touch devices
 Streams music from a dedicated kernel-read-only source mount to a legacy iPod,
 commits Apple music databases inside an iTunes-style sync envelope, and
 validates or rolls back transactions fail-closed.
 .
 The generic incremental ADD path has been live-tested on an iPod touch 2nd gen
 running iOS 4.2.1. Other devices are experimental.
CONTROL

install -m0644 "$ROOT/README.md" "$BUILD/usr/share/doc/ipod-sync/README.md"
install -m0644 "$ROOT/THIRD_PARTY.md" "$BUILD/usr/share/doc/ipod-sync/THIRD_PARTY.md"
install -m0644 "$ROOT/LICENSE" "$BUILD/usr/share/doc/ipod-sync/copyright"
if [[ -f "$ROOT/third_party/libgpod-patched-source/COPYING" ]]; then
  install -m0644 "$ROOT/third_party/libgpod-patched-source/COPYING" "$BUILD/usr/share/doc/ipod-sync/libgpod-COPYING"
fi
if [[ -f "$ROOT/third_party/libgpod-patched-source/debian/copyright" ]]; then
  install -m0644 "$ROOT/third_party/libgpod-patched-source/debian/copyright" "$BUILD/usr/share/doc/ipod-sync/libgpod-debian-copyright"
fi

find "$BUILD" -type d -exec chmod 0755 {} +
find "$BUILD" -type f ! -path '*/DEBIAN/*' ! -path '*/usr/bin/*' ! -name sync-envelope -exec chmod 0644 {} +
chmod 0755 "$BUILD/usr/bin/ipod-sync" "$BUILD/usr/lib/ipod-sync/ipod_sync.py" "$BUILD/usr/lib/ipod-sync/native/sync-envelope" "$BUILD/DEBIAN/preinst" "$BUILD/DEBIAN/postinst"
# Python bytecode embeds build paths and is unnecessary in this package.
find "$BUILD" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$BUILD" -type f -name '*.pyc' -delete

# Normalize the complete package staging tree. This prevents filesystem/build
# time from leaking into control.tar and data.tar.
find "$BUILD" -exec   touch --no-dereference --date="@${SOURCE_DATE_EPOCH}" {} +

dpkg-deb --build --root-owner-group "$BUILD" "$ROOT/dist/${PKG}.deb"
sha256sum "$ROOT/dist/${PKG}.deb" > "$ROOT/dist/${PKG}.deb.sha256"

# Private preparation kit performs the full privacy audit and public source
# bundle generation. The generated public source tree can still run this build
# script standalone without those private tools.
if [[ -x "$ROOT/tools/audit-release.sh" ]]; then
  "$ROOT/tools/audit-release.sh" --all
fi
if [[ -x "$ROOT/tools/make-release-bundle.sh" ]]; then
  "$ROOT/tools/make-release-bundle.sh"
fi

echo "Built: $ROOT/dist/${PKG}.deb"
