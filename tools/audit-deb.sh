#!/bin/bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

DEB="${1:-}"
if [[ -z "$DEB" || ! -f "$DEB" ]]; then
  echo "usage: $0 /path/to/ipod-sync.deb" >&2
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PAYLOAD="$TMP/payload"
CONTROL="$TMP/control"

mkdir -p "$PAYLOAD" "$CONTROL"

echo "===== PACKAGE ====="
echo "$DEB"
sha256sum "$DEB"

echo
echo "===== METADATA ====="

PACKAGE="$(dpkg-deb -f "$DEB" Package)"
VERSION="$(dpkg-deb -f "$DEB" Version)"
ARCH="$(dpkg-deb -f "$DEB" Architecture)"

printf 'Package:      %s\n' "$PACKAGE"
printf 'Version:      %s\n' "$VERSION"
printf 'Architecture: %s\n' "$ARCH"

EXPECTED_APP_VERSION="$(
  python3 - "$ROOT/src/ipod_sync.py" <<'PY'
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text())

for node in tree.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "VERSION":
                value = ast.literal_eval(node.value)
                print(value)
                raise SystemExit

raise SystemExit("VERSION not found")
PY
)"

EXPECTED_DEB_VERSION="$(
  sed -n 's/^VER="\([^"]*\)"/\1/p' "$ROOT/build-deb.sh"
)"

[[ -n "$EXPECTED_APP_VERSION" ]] || {
  echo "FAIL: could not determine application version" >&2
  exit 1
}

[[ -n "$EXPECTED_DEB_VERSION" ]] || {
  echo "FAIL: could not determine Debian package version" >&2
  exit 1
}

[[ "$PACKAGE" == "ipod-sync" ]] || {
  echo "FAIL: unexpected package name: $PACKAGE" >&2
  exit 1
}

[[ "$VERSION" == "$EXPECTED_DEB_VERSION" ]] || {
  echo "FAIL: package version $VERSION != expected $EXPECTED_DEB_VERSION" >&2
  exit 1
}

[[ "$ARCH" == "amd64" ]] || {
  echo "FAIL: current validated package architecture is amd64, got: $ARCH" >&2
  exit 1
}

echo "metadata: PASS"

echo
echo "===== OWNERSHIP ====="

if dpkg-deb --contents "$DEB" | awk '
  $2 != "root/root" {
    print "unexpected owner:", $2, $6
    bad=1
  }
  END { exit bad }
'
then
  echo "ownership: PASS"
else
  echo "FAIL: unexpected package ownership" >&2
  exit 1
fi

dpkg-deb -x "$DEB" "$PAYLOAD"
dpkg-deb -e "$DEB" "$CONTROL"

echo
echo "===== APPLICATION VERSION ====="

APP="$PAYLOAD/usr/lib/ipod-sync/ipod_sync.py"

[[ -f "$APP" ]] || {
  echo "FAIL: packaged application missing: $APP" >&2
  exit 1
}

ACTUAL_APP_VERSION="$(python3 "$APP" --version)"

echo "$ACTUAL_APP_VERSION"

case "$ACTUAL_APP_VERSION" in
  *"$EXPECTED_APP_VERSION")
    echo "application version: PASS"
    ;;
  *)
    echo "FAIL: application version does not contain $EXPECTED_APP_VERSION" >&2
    exit 1
    ;;
esac

echo
echo "===== PYTHON BYTECODE ====="

if find "$PAYLOAD" \
  \( \
    -type d -name '__pycache__' -o \
    -type f \( -name '*.pyc' -o -name '*.pyo' \) \
  \) -print -quit | grep -q .
then
  echo "FAIL: Python bytecode/cache found" >&2
  exit 1
else
  echo "bytecode: PASS"
fi

echo
echo "===== EXPECTED ELF FILES ====="

SYNC_ELF="$PAYLOAD/usr/lib/ipod-sync/native/sync-envelope"
LIBGPOD_ELF="$PAYLOAD/usr/lib/ipod-sync/vendor/libgpod/lib/libgpod.so.4.3.2"

for elf in "$SYNC_ELF" "$LIBGPOD_ELF"; do
  [[ -f "$elf" ]] || {
    echo "FAIL: expected ELF missing: $elf" >&2
    exit 1
  }

  info="$(file "$elf")"
  echo "$info"

  grep -q 'ELF' <<<"$info" || {
    echo "FAIL: not recognized as ELF: $elf" >&2
    exit 1
  }

  grep -q 'stripped' <<<"$info" || {
    echo "FAIL: ELF is not stripped: $elf" >&2
    exit 1
  }
done

echo "ELF stripping: PASS"

echo
echo "===== RUNTIME LINKAGE ====="

for elf in "$SYNC_ELF" "$LIBGPOD_ELF"; do
  echo "--- $(basename "$elf") ---"

  linkage="$(ldd "$elf")"
  printf '%s\n' "$linkage"

  if grep -q 'not found' <<<"$linkage"; then
    echo "FAIL: unresolved runtime library in $elf" >&2
    exit 1
  fi
done

echo "runtime linkage: PASS"

echo
echo "===== CONFIGURATION MANAGEMENT ====="

CONFIG_MANAGED=0

if [[ -f "$CONTROL/conffiles" ]] &&
   grep -Fxq '/etc/ipod-sync/config.env' "$CONTROL/conffiles"
then
  echo "config.env is managed as a Debian conffile"
  CONFIG_MANAGED=1
fi

if [[ -f "$CONTROL/postinst" ]] &&
   grep -q '/etc/ipod-sync/config.env' "$CONTROL/postinst"
then
  echo "config.env is managed by postinst"
  CONFIG_MANAGED=1
fi

[[ "$CONFIG_MANAGED" -eq 1 ]] || {
  echo "FAIL: no package configuration management found for /etc/ipod-sync/config.env" >&2
  exit 1
}

echo "configuration management: PASS"

echo
echo "===== PRIVATE / DEVELOPMENT FINGERPRINTS ====="

python3 - "$PAYLOAD" "$CONTROL" <<'PY'
from pathlib import Path
import re
import sys

roots = [Path(p) for p in sys.argv[1:]]

patterns = [
    re.compile(rb'(?<![A-Za-z0-9_./-])/home/[A-Za-z0-9_.-]+/'),
    re.compile(rb'(?<![A-Za-z0-9_./-])/Users/[A-Za-z0-9_.-]+/'),
    re.compile(b'syn_' + b'admin'),
    re.compile(rb'192\.168\.1\.161'),
    re.compile(b'ipod-' + b'test-add'),
    re.compile(b'rename-' + b'601'),
    re.compile(b'FROZEN_' + b'PREIMAGE'),
    re.compile(b'FROZEN_' + b'ARTIFACT'),
    re.compile(b'TEMPLATE_' + b'FALLBACK_PID'),
    re.compile(rb'public release preparation kit'),
    re.compile(rb'Do not upload it'),
]

failed = False

for root in roots:
    for path in root.rglob("*"):
        if not path.is_file():
            continue

        try:
            data = path.read_bytes()
        except OSError:
            continue

        for pattern in patterns:
            if pattern.search(data):
                print(
                    f"FAIL: {path}: "
                    f"private/development fingerprint matched: {pattern.pattern!r}"
                )
                failed = True

if failed:
    raise SystemExit(1)

print("privacy scan: PASS")
PY

echo
echo "===== PACKAGE AUDIT ====="
echo "AUDIT PASS"
