#!/bin/bash
set -euo pipefail

ROOT="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &&
    pwd
)"

for cmd in \
    cmp \
    git \
    grep \
    mkdir \
    mktemp \
    stat \
    tar
do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "ERROR: required source-archive test command missing: $cmd" >&2
        exit 1
    }
done

COMMIT="$(
    git -C "$ROOT" \
        rev-parse \
        --verify \
        HEAD^{commit}
)"

EPOCH="$(
    git -C "$ROOT" \
        show \
        -s \
        --format=%ct \
        "$COMMIT"
)"

PREFIX="open-ipod-sync-${COMMIT}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p \
    "$TMP/env-a" \
    "$TMP/env-b" \
    "$TMP/extracted"

ARCHIVE_A="$TMP/source-a.tar"
ARCHIVE_B="$TMP/source-b.tar"

echo "===== SOURCE ARCHIVE A ====="

env \
    TZ=UTC \
    LC_ALL=C \
    LANG=C \
    TMPDIR="$TMP/env-a" \
    PYTHONHASHSEED=1 \
    "$ROOT/tools/make-source-archive.sh" \
    "$ARCHIVE_A" \
    "$COMMIT"

echo
echo "===== SOURCE ARCHIVE B ====="

env \
    TZ=Pacific/Kiritimati \
    LC_ALL=C \
    LANG=C \
    TMPDIR="$TMP/env-b" \
    PYTHONHASHSEED=8675309 \
    "$ROOT/tools/make-source-archive.sh" \
    "$ARCHIVE_B" \
    "$COMMIT"

cmp -s \
    "$ARCHIVE_A" \
    "$ARCHIVE_B" || {
        echo "ERROR: repeated source archives differ" >&2
        sha256sum "$ARCHIVE_A" "$ARCHIVE_B" >&2
        exit 1
    }

echo "source archive byte reproducibility: PASS"

EMBEDDED="$(
    git get-tar-commit-id < "$ARCHIVE_A"
)"

[[ "$EMBEDDED" == "$COMMIT" ]] || {
    echo "ERROR: embedded source commit mismatch" >&2
    exit 1
}

echo "embedded commit identity: PASS"

tar -tf "$ARCHIVE_A" > "$TMP/listing"

grep -Fxq \
    "${PREFIX}/" \
    "$TMP/listing" || {
        echo "ERROR: expected archive root missing: ${PREFIX}/" >&2
        exit 1
    }

if grep -Eq \
    '(^|/)\.git(/|$)' \
    "$TMP/listing"
then
    echo "ERROR: .git metadata present in source archive" >&2
    exit 1
fi

echo ".git metadata in archive: ABSENT"

tar -xf \
    "$ARCHIVE_A" \
    -C "$TMP/extracted"

TREE="$TMP/extracted/$PREFIX"

[[ -d "$TREE" ]] || {
    echo "ERROR: extracted source root missing: $TREE" >&2
    exit 1
}

if find "$TREE" \
    -name .git \
    -print -quit |
    grep -q .
then
    echo "ERROR: extracted source contains .git metadata" >&2
    exit 1
fi

echo "extracted .git metadata: ABSENT"

for required in \
    build-deb.sh \
    README.md \
    LICENSE \
    src/ipod_sync.py \
    vendor/ipodctl/cdb.py \
    native/sync-envelope.c \
    native/sign-cdb.c \
    native/rijndael.c
do
    [[ -f "$TREE/$required" ]] || {
        echo "ERROR: source archive missing required file: $required" >&2
        exit 1
    }
done

[[ -d "$TREE/third_party/libgpod-patched-source/src" ]] || {
    echo "ERROR: source archive missing patched libgpod source" >&2
    exit 1
}

echo "required build sources: PASS"

ARCHIVED_BUILD_EPOCH="$(
    stat -c '%Y' \
        "$TREE/build-deb.sh"
)"

[[ "$ARCHIVED_BUILD_EPOCH" == "$EPOCH" ]] || {
    echo "ERROR: archived build-deb.sh mtime != commit epoch" >&2
    echo "commit epoch:   $EPOCH" >&2
    echo "archive mtime:  $ARCHIVED_BUILD_EPOCH" >&2
    exit 1
}

echo "archive timestamp identity: PASS"

[[ -x "$TREE/build-deb.sh" ]] || {
    echo "ERROR: build-deb.sh lost executable mode in archive" >&2
    exit 1
}

echo "archive executable modes: PASS"

echo
echo "source archive tests: PASS"
