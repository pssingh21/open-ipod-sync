#!/bin/bash
set -euo pipefail

ROOT="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &&
    pwd
)"

for cmd in gcc pkg-config; do
    command -v "$cmd" >/dev/null || {
        echo "ERROR: missing sanitizer dependency: $cmd" >&2
        exit 1
    }
done

for module in \
    glib-2.0 \
    libimobiledevice-1.0
do
    pkg-config --exists "$module" || {
        echo "ERROR: missing development module: $module" >&2
        exit 1
    }
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

SAN_FLAGS=(
    -O1
    -g3
    -Wall
    -Wextra
    -Wformat=2
    -Wformat-security
    -Werror=format-security
    -fno-omit-frame-pointer
    -fno-common
    -fsanitize=address,undefined
    -fno-sanitize-recover=all
)

read -r -a IMOBILE_CFLAGS <<<"$(
    pkg-config --cflags libimobiledevice-1.0
)"

read -r -a IMOBILE_LIBS <<<"$(
    pkg-config --libs libimobiledevice-1.0
)"

read -r -a GLIB_CFLAGS <<<"$(
    pkg-config --cflags glib-2.0
)"

read -r -a GLIB_LIBS <<<"$(
    pkg-config --libs glib-2.0
)"

export ASAN_OPTIONS="halt_on_error=1:detect_leaks=1"
export UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"


check_log()
{
    local log="$1"

    if grep -E \
        'AddressSanitizer|LeakSanitizer|UndefinedBehaviorSanitizer|runtime error:' \
        "$log"
    then
        echo "ERROR: sanitizer diagnostic detected: $log" >&2
        cat "$log" >&2
        exit 1
    fi
}


echo "===== SANITIZER COMPILER ====="

gcc --version |
head -n 1


echo
echo "===== BUILD sync-envelope WITH ASAN + UBSAN ====="

gcc \
    "${SAN_FLAGS[@]}" \
    "${IMOBILE_CFLAGS[@]}" \
    "$ROOT/native/sync-envelope.c" \
    "${IMOBILE_LIBS[@]}" \
    -o "$TMP/sync-envelope-san"

echo "sync-envelope sanitizer build: PASS"


echo
echo "===== sync-envelope RUNTIME SANITIZER POLICY ====="

# Do not execute sync-envelope in an automated sanitizer smoke test.
#
# The binary enters the real libimobiledevice sync protocol immediately and
# can communicate with a connected device before receiving application-level
# input. Building it with ASan/UBSan still gives compile/link instrumentation
# coverage, while runtime sanitizer coverage is exercised below on the native
# components that can run safely without touching an iPod.
echo "sync-envelope sanitizer runtime execution: SKIPPED (device-safety boundary)"


echo
echo "===== BUILD sign-cdb + rijndael WITH ASAN + UBSAN ====="

gcc \
    "${SAN_FLAGS[@]}" \
    "${GLIB_CFLAGS[@]}" \
    -I"$ROOT/native" \
    "$ROOT/native/sign-cdb.c" \
    "$ROOT/native/rijndael.c" \
    "${GLIB_LIBS[@]}" \
    -o "$TMP/sign-cdb-san"

echo "sign-cdb sanitizer build: PASS"


echo
echo "===== EXERCISE sign-cdb INVALID ARGUMENT PATH ====="

set +e

"$TMP/sign-cdb-san" \
    >"$TMP/sign-cdb.stdout" \
    2>"$TMP/sign-cdb.stderr"

SIGN_RC=$?

set -e

cat "$TMP/sign-cdb.stdout"
cat "$TMP/sign-cdb.stderr" >&2

check_log "$TMP/sign-cdb.stdout"
check_log "$TMP/sign-cdb.stderr"

[[ "$SIGN_RC" -ne 0 ]] || {
    echo "ERROR: sign-cdb accepted empty argv" >&2
    exit 1
}

echo "sign-cdb sanitizer execution: PASS (expected rc=$SIGN_RC)"


echo
echo "===== EXERCISE RIJNDAEL CORE WITH ASAN + UBSAN ====="

cat > "$TMP/rijndael-smoke.c" <<'C'
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rijndael.h"


int main(void)
{
    uint8_t key[16] = {
        0x61, 0x8c, 0xa1, 0x0d,
        0xc7, 0xf5, 0x7f, 0xd3,
        0xb4, 0x72, 0x3e, 0x08,
        0x15, 0x74, 0x63, 0xd7
    };

    uint8_t iv[16] = {
        0x24, 0xf5, 0x93, 0x31,
        0x77, 0x96, 0x32, 0x92,
        0xdf, 0xc9, 0xe3, 0xb4,
        0xff, 0x54, 0x65, 0x17
    };

    uint8_t input[32] = {0};
    uint8_t output[32] = {0};
    uint8_t zero[32] = {0};

    size_t i;

    for (i = 0; i < sizeof(input); i++) {
        input[i] = (uint8_t)i;
    }

    aes_set_key(key);

    aes_encrypt(
        iv,
        input,
        output,
        (int)sizeof(output)
    );

    if (
        memcmp(
            output,
            zero,
            sizeof(output)
        ) == 0
    ) {
        fprintf(
            stderr,
            "rijndael produced all-zero ciphertext\n"
        );

        return 1;
    }

    puts("rijndael sanitizer smoke: PASS");

    return 0;
}
C

gcc \
    "${SAN_FLAGS[@]}" \
    "${GLIB_CFLAGS[@]}" \
    -I"$ROOT/native" \
    "$TMP/rijndael-smoke.c" \
    "$ROOT/native/rijndael.c" \
    "${GLIB_LIBS[@]}" \
    -o "$TMP/rijndael-smoke"

"$TMP/rijndael-smoke" \
    >"$TMP/rijndael.stdout" \
    2>"$TMP/rijndael.stderr"

cat "$TMP/rijndael.stdout"
cat "$TMP/rijndael.stderr" >&2

check_log "$TMP/rijndael.stdout"
check_log "$TMP/rijndael.stderr"

grep -Fxq \
    'rijndael sanitizer smoke: PASS' \
    "$TMP/rijndael.stdout"

echo
echo "========================================================================"
echo "NATIVE ASAN + UBSAN: PASS"
echo "========================================================================"
