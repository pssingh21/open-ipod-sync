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
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_apply_transaction_orchestration.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_recovery_state_machine.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_cli_safety_routing.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_supply_chain_metadata.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_privacy_scan.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_privacy_boundary_workflows.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/tests/test_source_path_security.py"

# Legacy private-development and migration fingerprints are enforced by
# tools/privacy-scan.py below so there is one canonical privacy policy.
# Enforce the same canonical privacy boundary used for generated
# CI and release artifacts. The scanner never follows symlinks and
# skips only Git metadata.
python3 "$ROOT/tools/privacy-scan.py" "$ROOT"

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

echo
echo "===== REPRODUCIBILITY CLAIM SCOPE ====="
PYTHONDONTWRITEBYTECODE=1 \
    python3 "$ROOT/tests/test_reproducibility_claims.py"

echo
echo "===== SOURCE ARCHIVE REPRODUCIBILITY ====="
"$ROOT/tests/test_source_archive.sh"

echo
echo "===== OFFLINE RELEASE VERIFIER ====="
PYTHONDONTWRITEBYTECODE=1 \
    python3 "$ROOT/tests/test_verify_release.py"

echo "public source sanity check: PASS"
