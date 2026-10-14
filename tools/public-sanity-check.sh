#!/bin/bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Never create Python bytecode in the public source tree.
export PYTHONDONTWRITEBYTECODE=1

# Remove any bytecode left by previous test runs.
find "$ROOT" \
  -path "$ROOT/.git" -prune -o \
  -type d -name '__pycache__' -exec rm -rf {} +

find "$ROOT" \
  -type f \( -name '*.pyc' -o -name '*.pyo' \) \
  ! -path "$ROOT/.git/*" \
  -delete

# Syntax check without generating .pyc files.
python3 - "$ROOT/src/ipod_sync.py" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
compile(p.read_text(), str(p), "exec")
PY

# Public-alpha regression tests.
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_public_alpha.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_mock_planner_integration.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_transaction_safety.py"

# Old private migration implementation must not exist in public sources.
if grep -R -a -nE \
  --exclude='public-sanity-check.sh' \
  --exclude-dir='.git' \
  'FROZEN_(PREIMAGE|ARTIFACT_HASHES)|TEMPLATE_FALLBACK_PID|audited-frozen-v4|--no-frozen-v4' \
  "$ROOT"
then
  echo "ERROR: private migration machinery found" >&2
  exit 1
fi

# Reject known/private development-machine fingerprints.
python3 - "$ROOT" <<'PYSCAN'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])

patterns = [
    re.compile(rb'(?<![A-Za-z0-9_./-])/home/[A-Za-z0-9_.-]+/'),
    re.compile(rb'(?<![A-Za-z0-9_./-])/Users/[A-Za-z0-9_.-]+/'),
    re.compile(rb'syn_admin'),
    re.compile(rb'192\.168\.1\.161'),
    re.compile(rb'ipod-test-add'),
    re.compile(rb'rename-601'),
]

skip_names = {"public-sanity-check.sh"}

failed = False

for path in root.rglob("*"):
    if not path.is_file():
        continue

    try:
        rel = path.relative_to(root)
    except ValueError:
        continue

    if ".git" in rel.parts:
        continue

    if path.name in skip_names:
        continue

    try:
        data = path.read_bytes()
    except OSError:
        continue

    for pattern in patterns:
        if pattern.search(data):
            print(f"{path}: private/development fingerprint matched: {pattern.pattern!r}")
            failed = True

if failed:
    print("ERROR: private/development fingerprint found", file=sys.stderr)
    raise SystemExit(1)
PYSCAN

# Public source tree must not contain compiled libgpod artifacts.
if find "$ROOT" \
  -path "$ROOT/.git" -prune -o \
  -type f \( \
    -name '*.so' -o \
    -name '*.so.*' -o \
    -name '*.o' -o \
    -name '*.a' -o \
    -name '*.la' \
  \) -print -quit | grep -q .
then
  echo "ERROR: public source release unexpectedly contains compiled artifacts" >&2
  exit 1
fi

# Tests themselves must not have regenerated Python bytecode.
if find "$ROOT" \
  -path "$ROOT/.git" -prune -o \
  \( \
    -type d -name '__pycache__' -o \
    -type f \( -name '*.pyc' -o -name '*.pyo' \) \
  \) -print -quit | grep -q .
then
  echo "ERROR: Python bytecode/cache found in public source tree" >&2
  exit 1
fi

echo "public source sanity check: PASS"
