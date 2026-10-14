#!/bin/bash
set -euo pipefail

ROOT="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &&
    pwd
)"

usage()
{
    cat >&2 <<'EOF'
usage:
  tools/make-source-archive.sh OUTPUT.tar [TREEISH]

Creates a deterministic source tar directly from a committed Git object.

The working tree is not archived. Uncommitted and untracked files therefore
cannot accidentally enter the source artifact.
EOF

    exit 2
}

[[ $# -ge 1 && $# -le 2 ]] || usage

OUTPUT="$1"
TREEISH="${2:-HEAD}"

for cmd in \
    git \
    mkdir \
    mktemp \
    mv
do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "ERROR: required command missing: $cmd" >&2
        exit 1
    }
done

git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "ERROR: project source is not a Git working tree" >&2
    exit 1
}

COMMIT="$(
    git -C "$ROOT" \
        rev-parse \
        --verify \
        "${TREEISH}^{commit}"
)"

[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    echo "ERROR: unexpected commit identity: $COMMIT" >&2
    exit 1
}

SOURCE_DATE_EPOCH="$(
    git -C "$ROOT" \
        show \
        -s \
        --format=%ct \
        "$COMMIT"
)"

[[ "$SOURCE_DATE_EPOCH" =~ ^[0-9]+$ ]] || {
    echo "ERROR: invalid commit epoch: $SOURCE_DATE_EPOCH" >&2
    exit 1
}

PREFIX="open-ipod-sync-${COMMIT}/"

OUT_DIR="$(
    dirname -- "$OUTPUT"
)"

OUT_BASE="$(
    basename -- "$OUTPUT"
)"

mkdir -p "$OUT_DIR"

TMP="$(
    mktemp \
        --tmpdir="$OUT_DIR" \
        ".${OUT_BASE}.tmp.XXXXXX"
)"

cleanup()
{
    rm -f -- "$TMP"
}

trap cleanup EXIT

# Git's tar writer archives repository objects rather than the working tree.
#
# Explicit tar.umask avoids dependence on a user's Git configuration. The tar
# entry timestamps come from the archived commit, giving build-deb.sh a stable
# SOURCE_DATE_EPOCH fallback when the extracted tree contains no .git metadata.
git \
    -C "$ROOT" \
    -c tar.umask=0002 \
    archive \
    --format=tar \
    --prefix="$PREFIX" \
    "$COMMIT" \
    > "$TMP"

[[ -s "$TMP" ]] || {
    echo "ERROR: generated source archive is empty" >&2
    exit 1
}

EMBEDDED_COMMIT="$(
    git get-tar-commit-id < "$TMP"
)"

[[ "$EMBEDDED_COMMIT" == "$COMMIT" ]] || {
    echo "ERROR: archive commit identity mismatch" >&2
    echo "expected: $COMMIT" >&2
    echo "actual:   $EMBEDDED_COMMIT" >&2
    exit 1
}

mv -f -- \
    "$TMP" \
    "$OUTPUT"

trap - EXIT

echo "source archive commit: $COMMIT"
echo "source archive epoch:  $SOURCE_DATE_EPOCH"
echo "source archive prefix: $PREFIX"
echo "source archive:        $OUTPUT"
