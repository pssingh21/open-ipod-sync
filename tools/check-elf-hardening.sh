#!/bin/bash
set -euo pipefail

ELF="${1:-}"

if [[ -z "$ELF" || ! -f "$ELF" ]]; then
    echo "usage: $0 /path/to/elf" >&2
    exit 2
fi

command -v readelf >/dev/null || {
    echo "ERROR: readelf is required" >&2
    exit 1
}

HEADER="$(
    readelf -h "$ELF"
)"

PROGRAM_HEADERS="$(
    readelf -lW "$ELF"
)"

DYNAMIC="$(
    readelf -dW "$ELF"
)"

printf '%s\n' "$HEADER" |
grep -Eq 'Type:[[:space:]]+DYN' || {
    echo "FAIL: ELF is not PIE (Type != DYN): $ELF" >&2
    exit 1
}

printf '%s\n' "$PROGRAM_HEADERS" |
grep -q 'GNU_RELRO' || {
    echo "FAIL: GNU_RELRO missing: $ELF" >&2
    exit 1
}

printf '%s\n' "$DYNAMIC" |
grep -q 'BIND_NOW' || {
    echo "FAIL: BIND_NOW missing: $ELF" >&2
    exit 1
}

STACK_LINE="$(
    printf '%s\n' "$PROGRAM_HEADERS" |
    grep 'GNU_STACK' |
    head -n 1
)"

[[ -n "$STACK_LINE" ]] || {
    echo "FAIL: GNU_STACK header missing: $ELF" >&2
    exit 1
}

if grep -q 'RWE' <<<"$STACK_LINE"; then
    echo "FAIL: executable stack requested: $ELF" >&2
    exit 1
fi

echo "PIE:             PASS"
echo "RELRO:           PASS"
echo "BIND_NOW:        PASS"
echo "non-exec stack:  PASS"
echo "ELF hardening:   PASS"
