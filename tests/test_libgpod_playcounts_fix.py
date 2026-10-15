#!/usr/bin/env python3

from pathlib import Path
import hashlib
import re


ROOT = Path(__file__).resolve().parents[1]

SOURCE = (
    ROOT
    / "third_party"
    / "libgpod-patched-source"
    / "src"
    / "itdb_itunesdb.c"
)

PATCH = (
    ROOT
    / "third_party"
    / "libgpod-0.8.3-ipod-sync.patch"
)

PROVENANCE = (
    ROOT
    / "vendor"
    / "PROVENANCE.txt"
)


source = SOURCE.read_text()

buggy = (
    "g_array_index (array, GValue *, i)"
)

fixed = (
    "&g_array_index (array, GValue, i)"
)

assert buggy not in source, (
    "buggy PlayCounts.plist GArray pointer access remains"
)

assert source.count(fixed) == 2, (
    "expected exactly two corrected inline GValue accesses"
)


patch_text = PATCH.read_text()

assert (
    "-       if (!G_VALUE_HOLDS "
    "(g_array_index (array, GValue *, i), "
    "G_TYPE_HASH_TABLE)) {"
) in patch_text

assert (
    "+       if (!G_VALUE_HOLDS "
    "(&g_array_index (array, GValue, i), "
    "G_TYPE_HASH_TABLE)) {"
) in patch_text

assert (
    "-       track_dict = g_value_get_boxed "
    "(g_array_index (array, GValue *, i));"
) in patch_text

assert (
    "+       track_dict = g_value_get_boxed "
    "(&g_array_index (array, GValue, i));"
) in patch_text


provenance = PROVENANCE.read_text()

match = re.search(
    r"(?m)^source_patch_sha256=([0-9a-f]{64})$",
    provenance,
)

assert match is not None, (
    "vendor provenance patch digest missing"
)

actual_patch_sha = hashlib.sha256(
    PATCH.read_bytes()
).hexdigest()

assert match.group(1) == actual_patch_sha, (
    "vendor provenance patch digest does not match "
    "third_party/libgpod-0.8.3-ipod-sync.patch"
)


print(
    "libgpod PlayCounts.plist GValue regression: PASS"
)

print(
    "libgpod reviewable patch provenance: PASS"
)
