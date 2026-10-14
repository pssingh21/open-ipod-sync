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
  tools/run-reproducibility-matrix.sh \
    SOURCE.tar \
    COMMIT_SHA \
    SOURCE_DATE_EPOCH \
    OUTPUT_DIR

Builds the same committed source archive twice under deliberately different
build environments and requires the complete generated supply-chain bundles to
be byte-for-byte identical.

The actual package builds:
  - contain no .git metadata;
  - have git deliberately disabled;
  - derive SOURCE_DATE_EPOCH from the source archive;
  - use different paths, HOME, TMPDIR, timezone, locale, hash seed,
    umask, user/logname values, and make parallelism.
EOF

    exit 2
}

[[ $# -eq 4 ]] || usage

ARCHIVE="$1"
COMMIT="$2"
SOURCE_EPOCH="$3"
OUTPUT_ROOT="$4"

[[ -f "$ARCHIVE" ]] || {
    echo "ERROR: source archive missing: $ARCHIVE" >&2
    exit 1
}

[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    echo "ERROR: invalid commit identity: $COMMIT" >&2
    exit 1
}

[[ "$SOURCE_EPOCH" =~ ^[0-9]+$ ]] || {
    echo "ERROR: invalid source epoch: $SOURCE_EPOCH" >&2
    exit 1
}

for cmd in \
    cmp \
    diff \
    dpkg-deb \
    find \
    gcc \
    grep \
    mkdir \
    mktemp \
    python3 \
    sha256sum \
    stat \
    tar
do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "ERROR: required command missing: $cmd" >&2
        exit 1
    }
done

ARCHIVE="$(
    cd -- "$(dirname -- "$ARCHIVE")" &&
    printf '%s/%s\n' \
        "$PWD" \
        "$(basename -- "$ARCHIVE")"
)"

OUTPUT_ROOT="$(
    mkdir -p "$OUTPUT_ROOT"
    cd -- "$OUTPUT_ROOT"
    pwd
)"

rm -rf \
    "$OUTPUT_ROOT/builder-a" \
    "$OUTPUT_ROOT/builder-b"

mkdir -p \
    "$OUTPUT_ROOT/builder-a" \
    "$OUTPUT_ROOT/builder-b"

SYSTEM_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


echo
echo "===== BUILD KERNEL NETWORK-DENY HELPER ====="

NETWORK_POLICY_DIR="$OUTPUT_ROOT/.network-isolation"
NETWORK_HELPER="$NETWORK_POLICY_DIR/network-deny-exec"

mkdir -p "$NETWORK_POLICY_DIR"

gcc \
    -O2 \
    -g0 \
    -Wall \
    -Wextra \
    -Werror \
    -std=c11 \
    "$ROOT/tools/network-deny-exec.c" \
    -o "$NETWORK_HELPER"

[[ -x "$NETWORK_HELPER" ]] || {
    echo "ERROR: network-deny helper was not built" >&2
    exit 1
}

echo "network-deny helper build: PASS"


echo
echo "===== VERIFY ORDINARY EXECUTION UNDER SECCOMP ====="

"$NETWORK_HELPER" \
    /bin/sh \
    -c 'test "x$1" = xPASS' \
    sh \
    PASS

echo "ordinary subprocess execution: PASS"


echo
echo "===== VERIFY NETWORK SOCKET CREATION IS DENIED ====="

"$NETWORK_HELPER" \
    python3 \
    -c '
import errno
import socket
import sys

try:
    socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    )
except OSError as exc:
    if exc.errno != errno.EPERM:
        raise SystemExit(
            f"wrong socket failure errno: {exc.errno}"
        )
    print("AF_INET socket creation: DENIED (EPERM)")
else:
    raise SystemExit(
        "ERROR: AF_INET socket creation unexpectedly succeeded"
    )
'

echo "kernel network denial self-test: PASS"

WORK_A="$(
    mktemp \
        -d \
        /tmp/ipod-sync-repro-a.XXXXXX
)"

WORK_B_BASE="$(
    mktemp \
        -d \
        /tmp/ipod-sync-repro-b-long-root.XXXXXX
)"

WORK_B="$WORK_B_BASE/deeper/path/for/environment/variance"

mkdir -p "$WORK_B"

cleanup()
{
    rm -rf \
        "$WORK_A" \
        "$WORK_B_BASE"
}

trap cleanup EXIT


build_profile()
{
    local label="$1"
    local work_root="$2"
    local timezone="$3"
    local locale_name="$4"
    local hash_seed="$5"
    local jobs="$6"
    local mask="$7"
    local synthetic_user="$8"

    local source_root="$work_root/open-ipod-sync-$COMMIT"
    local home_dir="$work_root/home-$label"
    local tmp_dir="$work_root/tmp-$label"
    local fake_bin="$work_root/no-git-bin"
    local bundle="$OUTPUT_ROOT/builder-$label"

    echo
    echo "========================================================================"
    echo "BUILDER $label"
    echo "========================================================================"

    echo "work root:       $work_root"
    echo "HOME:            $home_dir"
    echo "TMPDIR:          $tmp_dir"
    echo "TZ:              $timezone"
    echo "LC_ALL:          $locale_name"
    echo "PYTHONHASHSEED:  $hash_seed"
    echo "build jobs:      $jobs"
    echo "umask:           $mask"
    echo "USER/LOGNAME:    $synthetic_user"

    mkdir -p \
        "$home_dir" \
        "$tmp_dir" \
        "$fake_bin"

    tar \
        -xf "$ARCHIVE" \
        -C "$work_root"

    [[ -d "$source_root" ]] || {
        echo "ERROR: builder $label extracted source missing" >&2
        exit 1
    }

    if find "$source_root" \
        -name .git \
        -print -quit |
        grep -q .
    then
        echo "ERROR: builder $label extracted .git metadata" >&2
        exit 1
    fi

    local archive_epoch

    archive_epoch="$(
        stat \
            -c '%Y' \
            "$source_root/build-deb.sh"
    )"

    [[ "$archive_epoch" == "$SOURCE_EPOCH" ]] || {
        echo "ERROR: builder $label archive epoch mismatch" >&2
        echo "expected: $SOURCE_EPOCH" >&2
        echo "actual:   $archive_epoch" >&2
        exit 1
    }

    cat > "$fake_bin/git" <<'NO_GIT'
#!/bin/sh
echo "ERROR: git invoked inside no-.git reproducibility build" >&2
exit 97
NO_GIT

    chmod 0755 "$fake_bin/git"

    echo
    echo "===== BUILD $label ====="

    (
        umask "$mask"

        cd "$source_root"

        "$NETWORK_HELPER" /usr/bin/env -i \
            PATH="$fake_bin:$SYSTEM_PATH" \
            HOME="$home_dir" \
            TMPDIR="$tmp_dir" \
            TZ="$timezone" \
            LC_ALL="$locale_name" \
            LANG="$locale_name" \
            USER="$synthetic_user" \
            LOGNAME="$synthetic_user" \
            PYTHONHASHSEED="$hash_seed" \
            IPOD_SYNC_BUILD_JOBS="$jobs" \
            ./build-deb.sh
    )

    mapfile -t debs < <(
        find "$source_root/dist" \
            -maxdepth 1 \
            -type f \
            -name 'ipod-sync_*_amd64.deb' \
            -print |
        sort
    )

    [[ "${#debs[@]}" -eq 1 ]] || {
        echo "ERROR: builder $label expected exactly one Debian package" >&2
        printf '%s\n' "${debs[@]}" >&2
        exit 1
    }

    local deb="${debs[0]}"
    local package_name

    package_name="$(
        basename -- "$deb"
    )"

    echo
    echo "===== AUDIT $label PACKAGE ====="

    "$source_root/tools/audit-deb.sh" \
        "$deb"

    cp \
        "$deb" \
        "$bundle/$package_name"

    echo
    echo "===== GENERATE $label SUPPLY-CHAIN METADATA ====="

    "$NETWORK_HELPER" /usr/bin/env -i \
        PATH="$fake_bin:$SYSTEM_PATH" \
        HOME="$home_dir" \
        TMPDIR="$tmp_dir" \
        TZ="$timezone" \
        LC_ALL="$locale_name" \
        LANG="$locale_name" \
        USER="$synthetic_user" \
        LOGNAME="$synthetic_user" \
        PYTHONHASHSEED="$hash_seed" \
        python3 \
        "$source_root/tools/generate-supply-chain-metadata.py" \
        "$bundle/$package_name" \
        --output-dir "$bundle" \
        --git-commit "$COMMIT" \
        --source-date-epoch "$SOURCE_EPOCH" \
        --build-environment \
          "debian-11-amd64-snapshot-20260830T235959Z"

    (
        cd "$bundle"

        mapfile -t checksum_files < <(
            find . \
                -maxdepth 1 \
                -type f \
                \( \
                    -name '*.deb' -o \
                    -name '*.spdx.json' -o \
                    -name 'PROVENANCE.json' \
                \) \
                -printf '%f\n' |
            sort
        )

        [[ "${#checksum_files[@]}" -eq 3 ]] || {
            echo "ERROR: builder $label unexpected supply-chain bundle" >&2
            printf '%s\n' "${checksum_files[@]}" >&2
            exit 1
        }

        sha256sum \
            "${checksum_files[@]}" \
            > SHA256SUMS

        sha256sum -c SHA256SUMS
    )

    echo
    echo "builder $label: PASS"
}


build_profile \
    a \
    "$WORK_A" \
    'UTC0' \
    'C' \
    '1' \
    '1' \
    '022' \
    'repro-builder-a'

build_profile \
    b \
    "$WORK_B" \
    'EST5EDT,M3.2.0/2,M11.1.0/2' \
    'C.UTF-8' \
    '8675309' \
    '4' \
    '077' \
    'repro-builder-b'


echo
echo "===== VERIFY MATRIX BUNDLE FILE SET ====="

mapfile -t NAMES_A < <(
    find "$OUTPUT_ROOT/builder-a" \
        -maxdepth 1 \
        -type f \
        -printf '%f\n' |
    sort
)

mapfile -t NAMES_B < <(
    find "$OUTPUT_ROOT/builder-b" \
        -maxdepth 1 \
        -type f \
        -printf '%f\n' |
    sort
)

[[ "${#NAMES_A[@]}" -eq 4 ]] || {
    echo "ERROR: builder A expected four bundle files" >&2
    printf '%s\n' "${NAMES_A[@]}" >&2
    exit 1
}

[[ "${#NAMES_B[@]}" -eq 4 ]] || {
    echo "ERROR: builder B expected four bundle files" >&2
    printf '%s\n' "${NAMES_B[@]}" >&2
    exit 1
}

if ! diff -u \
    <(printf '%s\n' "${NAMES_A[@]}") \
    <(printf '%s\n' "${NAMES_B[@]}")
then
    echo "ERROR: builder bundle file sets differ" >&2
    exit 1
fi

echo "bundle file set: PASS"


echo
echo "===== BYTE-FOR-BYTE ENVIRONMENT MATRIX ====="

for name in "${NAMES_A[@]}"; do
    cmp -s \
        "$OUTPUT_ROOT/builder-a/$name" \
        "$OUTPUT_ROOT/builder-b/$name" || {
            echo "ERROR: reproducibility matrix differs: $name" >&2

            echo
            echo "builder A:"
            sha256sum "$OUTPUT_ROOT/builder-a/$name"

            echo
            echo "builder B:"
            sha256sum "$OUTPUT_ROOT/builder-b/$name"

            exit 1
        }

    printf '%-42s PASS\n' "$name"
done


echo
echo "===== VERIFY BOTH CHECKSUM MANIFESTS ====="

(
    cd "$OUTPUT_ROOT/builder-a"
    sha256sum -c SHA256SUMS
)

(
    cd "$OUTPUT_ROOT/builder-b"
    sha256sum -c SHA256SUMS
)


echo
echo "===== NETWORK ISOLATION SUMMARY ====="
echo "socket/network syscalls: KERNEL-DENIED BY SECCOMP"
echo "inherited non-stdio fds: CLOSED"
echo "socket-backed stdio:     REFUSED"
echo "builder A:               ISOLATED"
echo "builder B:               ISOLATED"
echo "metadata A/B:            ISOLATED"

echo
echo "========================================================================"
echo "REPRODUCIBILITY ENVIRONMENT MATRIX: PASS"
echo "========================================================================"

cleanup
trap - EXIT
