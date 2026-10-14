#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <ipod-sync.deb>" >&2
  exit 2
fi

DEB="$(readlink -f "$1")"

[[ -f "$DEB" ]] || {
  echo "ERROR: package not found: $DEB" >&2
  exit 1
}

CONFIG=/etc/ipod-sync/config.env
PACKAGE=ipod-sync

cleanup() {
  dpkg -r "$PACKAGE" >/dev/null 2>&1 || true
  rm -f "$CONFIG"
  rm -f /var/lib/ipod-sync/config.env.preupgrade
}
trap cleanup EXIT

echo "===== PACKAGE ====="
dpkg-deb -f "$DEB" Package Version Architecture

[[ "$(dpkg-deb -f "$DEB" Package)" == "$PACKAGE" ]] || {
  echo "ERROR: unexpected package name" >&2
  exit 1
}

echo
echo "===== CLEAN INSTALL ====="

rm -f "$CONFIG"
rm -f /var/lib/ipod-sync/config.env.preupgrade

dpkg -i "$DEB"

[[ -f "$CONFIG" ]] || {
  echo "ERROR: config was not created" >&2
  exit 1
}

grep -Fx 'IPOD_SYNC_SOURCE=/mnt/music' "$CONFIG"
grep -Fx 'IPOD_SYNC_MOUNT=$HOME/ipod' "$CONFIG"

echo "config creation: PASS"

echo
echo "===== INSTALLED VERSION ====="

ipod-sync version

EXPECTED_APP_VERSION="$(
  python3 - "$DEB" <<'PY'
import ast
from pathlib import Path
import subprocess
import sys
import tempfile

deb = sys.argv[1]

with tempfile.TemporaryDirectory() as td:
    subprocess.run(
        ["dpkg-deb", "-x", deb, td],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    p = Path(td) / "usr/lib/ipod-sync/ipod_sync.py"
    tree = ast.parse(p.read_text())

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "VERSION"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    print(node.value.value)
                    raise SystemExit(0)

raise SystemExit("VERSION not found")
PY
)"

ACTUAL_VERSION="$(ipod-sync version)"

[[ "$ACTUAL_VERSION" == *"$EXPECTED_APP_VERSION"* ]] || {
  echo "ERROR: installed CLI version mismatch" >&2
  echo "expected app version: $EXPECTED_APP_VERSION" >&2
  echo "actual output:        $ACTUAL_VERSION" >&2
  exit 1
}

echo "version check: PASS"

echo
echo "===== USER CONFIG EDIT ====="

cat > "$CONFIG" <<'CONF'
# lifecycle CI sentinel
IPOD_SYNC_SOURCE=/test/read-only-music
IPOD_SYNC_MOUNT=/test/ipod-mount
CONF

chmod 0644 "$CONFIG"

BEFORE_SHA="$(sha256sum "$CONFIG" | awk '{print $1}')"

cat "$CONFIG"

echo
echo "===== REINSTALL / UPGRADE PATH ====="

dpkg -i "$DEB"

AFTER_SHA="$(sha256sum "$CONFIG" | awk '{print $1}')"

if [[ "$BEFORE_SHA" != "$AFTER_SHA" ]]; then
  echo "ERROR: user-edited config changed during reinstall" >&2
  diff -u \
    <(printf '%s\n' \
      '# lifecycle CI sentinel' \
      'IPOD_SYNC_SOURCE=/test/read-only-music' \
      'IPOD_SYNC_MOUNT=/test/ipod-mount') \
    "$CONFIG" || true
  exit 1
fi

grep -Fx '# lifecycle CI sentinel' "$CONFIG"
grep -Fx 'IPOD_SYNC_SOURCE=/test/read-only-music' "$CONFIG"
grep -Fx 'IPOD_SYNC_MOUNT=/test/ipod-mount' "$CONFIG"

[[ ! -e /var/lib/ipod-sync/config.env.preupgrade ]] || {
  echo "ERROR: preupgrade backup was not cleared" >&2
  exit 1
}

echo "config preservation: PASS"

echo
echo "===== PACKAGE REMOVE ====="

dpkg -r "$PACKAGE"

if dpkg-query -W "$PACKAGE" >/dev/null 2>&1; then
  status="$(dpkg-query -W -f='${db:Status-Status}' "$PACKAGE" 2>/dev/null || true)"
  [[ "$status" != "installed" ]] || {
    echo "ERROR: package still installed after removal" >&2
    exit 1
  }
fi

[[ -f "$CONFIG" ]] || {
  echo "ERROR: remove destroyed user configuration" >&2
  exit 1
}

grep -Fx 'IPOD_SYNC_SOURCE=/test/read-only-music' "$CONFIG"
grep -Fx 'IPOD_SYNC_MOUNT=/test/ipod-mount' "$CONFIG"

echo "remove preserves user config: PASS"

echo
echo "PACKAGE LIFECYCLE: PASS"
