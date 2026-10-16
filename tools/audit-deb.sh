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
echo "===== CHECKSUM SIDECAR ====="

SIDECAR="${DEB}.sha256"

[[ -f "$SIDECAR" ]] || {
  echo "FAIL: checksum sidecar missing: $SIDECAR" >&2
  exit 1
}

EXPECTED_HASH="$(
  sha256sum "$DEB" |
  awk '{print $1}'
)"

EXPECTED_NAME="$(basename "$DEB")"
EXPECTED_LINE="${EXPECTED_HASH}  ${EXPECTED_NAME}"

ACTUAL_LINE="$(
  cat "$SIDECAR"
)"

[[ "$ACTUAL_LINE" == "$EXPECTED_LINE" ]] || {
  echo "FAIL: checksum sidecar is not canonical" >&2
  echo "expected basename-only checksum entry" >&2
  exit 1
}

(
  cd "$(dirname "$DEB")"
  sha256sum -c "$(basename "$SIDECAR")"
)

echo "checksum sidecar: PASS (basename-only, verified)"

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
WRAPPER="$PAYLOAD/usr/bin/ipod-sync"

[[ -f "$APP" ]] || {
  echo "FAIL: packaged application missing: $APP" >&2
  exit 1
}

[[ -x "$WRAPPER" ]] || {
  echo "FAIL: packaged wrapper missing or not executable: $WRAPPER" >&2
  exit 1
}

grep -Fq   'unsafe ifuse version detected: 1.2.0'   "$APP" || {
    echo "FAIL: Python ifuse 1.2.0 safety gate missing" >&2
    exit 1
  }

grep -Fq   'require_stable_file_read'   "$APP" || {
    echo "FAIL: live-file stability gate missing" >&2
    exit 1
  }

grep -Fq   'require_safe_ifuse() {'   "$WRAPPER" || {
    echo "FAIL: wrapper ifuse safety gate missing" >&2
    exit 1
  }

grep -Fq   'unsafe ifuse version detected: 1.2.0'   "$WRAPPER" || {
    echo "FAIL: wrapper ifuse 1.2.0 refusal missing" >&2
    exit 1
  }

grep -Fq \
  '_debian_ifuse_known_unsafe_version' \
  "$APP" || {
    echo "FAIL: Debian ifuse unsafe-version fallback missing" >&2
    exit 1
  }

grep -Fq \
  'dpkg-query' \
  "$WRAPPER" || {
    echo "FAIL: wrapper Debian ifuse fallback missing" >&2
    exit 1
  }

echo "ifuse runtime safety contract: PASS"

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

IFUSE_POLICY="$(
  dpkg-deb -f "$DEB" X-Ipod-Sync-Ifuse-Policy 2>/dev/null || true
)"
PACKAGE_DEPENDS="$(dpkg-deb -f "$DEB" Depends)"
IFUSE_ELF="$PAYLOAD/usr/lib/ipod-sync/bin/ifuse"
IFUSE_MARKER="$PAYLOAD/usr/lib/ipod-sync/ifuse-bundled-required"
IFUSE_LICENSE="$PAYLOAD/usr/share/doc/ipod-sync/ifuse-COPYING"

AUDIT_ELFS=("$SYNC_ELF" "$LIBGPOD_ELF")

echo "===== EMBEDDED IFUSE POLICY ====="

EXPECTED_WRAPPER_STAMP=""
EXPECTED_APP_STAMP=""

case "$IFUSE_POLICY" in
  bundled-1.2.1)
    EXPECTED_WRAPPER_STAMP="IFUSE_BUNDLED_BUILD=1"
    EXPECTED_APP_STAMP="BUNDLED_IFUSE_BUILD = True"
    ;;
  system)
    EXPECTED_WRAPPER_STAMP="IFUSE_BUNDLED_BUILD=0"
    EXPECTED_APP_STAMP="BUNDLED_IFUSE_BUILD = False"
    ;;
  "")
    # Legacy Debian artifacts may lack the policy field.
    # They must also lack the new embedded-policy stamps.
    if grep -Eq '^IFUSE_BUNDLED_BUILD=' "$WRAPPER" ||
       grep -Eq '^BUNDLED_IFUSE_BUILD =' "$APP"; then
      echo "FAIL: embedded ifuse policy lacks package metadata" >&2
      exit 1
    fi
    ;;
  *)
    echo "FAIL: unrecognized embedded ifuse package policy" >&2
    exit 1
    ;;
esac

if [[ -n "$EXPECTED_WRAPPER_STAMP" ]]; then
  [[ "$(grep -Ec '^IFUSE_BUNDLED_BUILD=[01]$' "$WRAPPER")" == 1 ]] || {
    echo "FAIL: invalid number of launcher policy stamps" >&2
    exit 1
  }

  [[ "$(grep -Ec '^BUNDLED_IFUSE_BUILD = (True|False)$' "$APP")" == 1 ]] || {
    echo "FAIL: invalid number of Python policy stamps" >&2
    exit 1
  }

  grep -Fxq "$EXPECTED_WRAPPER_STAMP" "$WRAPPER" || {
    echo "FAIL: embedded ifuse launcher policy mismatch" >&2
    exit 1
  }

  grep -Fxq "$EXPECTED_APP_STAMP" "$APP" || {
    echo "FAIL: embedded ifuse Python policy mismatch" >&2
    exit 1
  }

  grep -Fq 'if [[ "$IFUSE_BUNDLED_BUILD" == 1 ]]; then' "$WRAPPER" || {
    echo "FAIL: mandatory launcher policy guard missing" >&2
    exit 1
  }

  grep -Fq 'if BUNDLED_IFUSE_BUILD:' "$APP" || {
    echo "FAIL: mandatory Python policy guard missing" >&2
    exit 1
  }
fi

echo "embedded ifuse package policy: PASS"

case "$IFUSE_POLICY" in
  bundled-1.2.1)
    [[ -f "$IFUSE_ELF" && -x "$IFUSE_ELF" &&
       ! -L "$IFUSE_ELF" ]] || {
      echo "FAIL: bundled ifuse missing or non-executable" >&2
      exit 1
    }

    [[ -f "$IFUSE_MARKER" && ! -L "$IFUSE_MARKER" ]] || {
      echo "FAIL: bundled ifuse marker missing" >&2
      exit 1
    }

    [[ "$(cat "$IFUSE_MARKER")" == "1.2.1" ]] || {
      echo "FAIL: bundled ifuse marker is incorrect" >&2
      exit 1
    }

    [[ -s "$IFUSE_LICENSE" && ! -L "$IFUSE_LICENSE" ]] || {
      echo "FAIL: bundled ifuse license missing" >&2
      exit 1
    }

    for dep in fuse3 libfuse3-4; do
      if ! grep -Eq "(^|, )${dep}([ (,]|$)" \
        <<<"$PACKAGE_DEPENDS"; then
        echo "FAIL: missing runtime dependency: $dep" >&2
        exit 1
      fi
    done

    if grep -Eq '(^|, )ifuse([ (,]|$)' \
      <<<"$PACKAGE_DEPENDS"; then
      echo "FAIL: bundled package depends on system ifuse" >&2
      exit 1
    fi

    grep -Fq 'IFUSE_BIN="$PRIVATE_IFUSE"' "$WRAPPER" || {
      echo "FAIL: private ifuse launcher routing missing" >&2
      exit 1
    }

    grep -Fq '"$IFUSE_BIN" "$IPOD_SYNC_MOUNT" -o ro' \
      "$WRAPPER" || {
      echo "FAIL: read-only mount is not using selected ifuse" >&2
      exit 1
    }

    grep -Fq 'required bundled ifuse 1.2.1 is missing' \
      "$APP" || {
      echo "FAIL: Python bundled-ifuse refusal missing" >&2
      exit 1
    }

    IFUSE_VERSION="$("$IFUSE_ELF" --version 2>&1)" || {
      echo "FAIL: bundled ifuse failed to execute" >&2
      exit 1
    }

    [[ "$IFUSE_VERSION" == "ifuse 1.2.1" ]] || {
      echo "FAIL: incorrect bundled ifuse: $IFUSE_VERSION" >&2
      exit 1
    }

    "$ROOT/tools/check-elf-hardening.sh" "$IFUSE_ELF"

    AUDIT_ELFS+=("$IFUSE_ELF")
    echo "bundled ifuse package policy: PASS"
    ;;
  system|"")
    # Empty policy supports older Debian-only packages.
    # It never permits unexpected private ifuse artifacts.
    [[ ! -e "$IFUSE_ELF" && ! -L "$IFUSE_ELF" &&
       ! -e "$IFUSE_MARKER" && ! -L "$IFUSE_MARKER" &&
       ! -e "$IFUSE_LICENSE" ]] || {
      echo "FAIL: unexpected private ifuse in system package" >&2
      exit 1
    }

    grep -Eq '(^|, )ifuse([ (,]|$)' \
      <<<"$PACKAGE_DEPENDS" || {
      echo "FAIL: Debian ifuse dependency missing" >&2
      exit 1
    }

    echo "system ifuse package policy: PASS"
    ;;
  *)
    echo "FAIL: unknown ifuse package policy" >&2
    exit 1
    ;;
esac


for elf in "${AUDIT_ELFS[@]}"; do
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
echo "===== NATIVE ELF HARDENING ====="
"$ROOT/tools/check-elf-hardening.sh" "$SYNC_ELF"

echo
echo "===== RUNTIME LINKAGE ====="

for elf in "${AUDIT_ELFS[@]}"; do
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
echo "===== PRIVACY BOUNDARY ====="

# Scan both the raw Debian artifact and its payload/control archive members.
# privacy-scan.py performs Debian extraction in a temporary directory and
# never mutates the source tree or the package.
python3 "$ROOT/tools/privacy-scan.py" "$DEB"

echo

echo "===== PACKAGE AUDIT ====="
echo "AUDIT PASS"
