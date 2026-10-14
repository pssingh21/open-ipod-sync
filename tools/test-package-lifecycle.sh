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
echo "===== INSTALLED DOCTOR READ-ONLY PATH ====="

DOCTOR_SOURCE=/mnt/music
DOCTOR_MOUNT="$HOME/ipod"
DOCTOR_STATE="$HOME/doctor-state-must-not-be-created"

[[ ! -e "$DOCTOR_SOURCE" ]] || {
  echo "ERROR: doctor test source unexpectedly exists: $DOCTOR_SOURCE" >&2
  exit 1
}

[[ ! -e "$DOCTOR_MOUNT" ]] || {
  echo "ERROR: doctor test mount unexpectedly exists before doctor: $DOCTOR_MOUNT" >&2
  exit 1
}

[[ ! -e "$DOCTOR_STATE" ]] || {
  echo "ERROR: isolated doctor state path unexpectedly exists before doctor: $DOCTOR_STATE" >&2
  exit 1
}

if DOCTOR_OUTPUT="$(
  IPOD_SYNC_STATE_DIR="$DOCTOR_STATE" \
    ipod-sync doctor 2>&1
)"; then
  DOCTOR_RC=0
else
  DOCTOR_RC=$?
fi

printf '%s\n' "$DOCTOR_OUTPUT"

[[ "$DOCTOR_RC" -eq 1 ]] || {
  echo "ERROR: expected doctor exit 1 for absent source/device, got $DOCTOR_RC" >&2
  exit 1
}

grep -F "ipod-sync $EXPECTED_APP_VERSION doctor" <<<"$DOCTOR_OUTPUT"
grep -F "source: $DOCTOR_SOURCE" <<<"$DOCTOR_OUTPUT"
grep -F "mount:  $DOCTOR_MOUNT" <<<"$DOCTOR_OUTPUT"
grep -F "Overall" <<<"$DOCTOR_OUTPUT"
grep -F "readiness:" <<<"$DOCTOR_OUTPUT"
grep -F "NOT READY" <<<"$DOCTOR_OUTPUT"

if grep -F "iPod mounted read-only:" <<<"$DOCTOR_OUTPUT"; then
  echo "ERROR: doctor appears to have mounted the iPod" >&2
  exit 1
fi

[[ ! -e "$DOCTOR_MOUNT" ]] || {
  echo "ERROR: doctor created or mounted the configured iPod path" >&2
  exit 1
}

[[ ! -e "$DOCTOR_STATE" ]] || {
  echo "ERROR: doctor created transaction/state storage" >&2
  exit 1
}

echo "installed doctor read-only path: PASS"

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
