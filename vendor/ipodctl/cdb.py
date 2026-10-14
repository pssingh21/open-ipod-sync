from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass


MHBD_HEADER_LEN = 244

HASH72_OFF = 0x72
HASH72_LEN = 46

MHOD_TITLE = 1
MHOD_PATH = 2
MHOD_ALBUM = 3
MHOD_ARTIST = 4
MHOD_GENRE = 5
MHOD_FILETYPE = 6
MHOD_ALBUMARTIST = 22

DISPLAY_REMOVE_TYPES = {
    MHOD_ALBUM,
    MHOD_ARTIST,
    MHOD_ALBUMARTIST,
}


class CDBError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrackSection:
    section_off: int
    header_len: int
    total_len: int
    mhlt_off: int
    mhlt_header_len: int
    track_count: int
    records: tuple[tuple[int, int], ...]


def _u16(data: bytes, off: int) -> int:
    if off < 0 or off + 2 > len(data):
        raise CDBError(
            f"u16 outside buffer at {off:#x}"
        )

    return struct.unpack_from(
        "<H",
        data,
        off,
    )[0]


def _u32(data: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(data):
        raise CDBError(
            f"u32 outside buffer at {off:#x}"
        )

    return struct.unpack_from(
        "<I",
        data,
        off,
    )[0]


def _put_u32(
    data: bytearray,
    off: int,
    value: int,
) -> None:
    struct.pack_into(
        "<I",
        data,
        off,
        value,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inflate_container(cdb: bytes) -> bytes:
    if len(cdb) < MHBD_HEADER_LEN:
        raise CDBError(
            "CDB smaller than Apple mhbd header"
        )

    if cdb[:4] != b"mhbd":
        raise CDBError(
            "CDB does not begin with mhbd"
        )

    header_len = _u32(cdb, 4)
    total_len = _u32(cdb, 8)

    if header_len != MHBD_HEADER_LEN:
        raise CDBError(
            f"unexpected mhbd header length "
            f"{header_len}"
        )

    if total_len != len(cdb):
        raise CDBError(
            "mhbd total length does not match "
            "actual file size"
        )

    if _u16(cdb, 0x30) != 2:
        raise CDBError(
            "unexpected CDB hashing scheme"
        )

    if cdb[0xA8] != 1:
        raise CDBError(
            "expected compressed Apple CDB"
        )

    try:
        body = zlib.decompress(
            cdb[header_len:]
        )
    except zlib.error as exc:
        raise CDBError(
            f"CDB zlib decompression failed: {exc}"
        ) from exc

    return body


def _all_tag_offsets(
    data: bytes,
    tag: bytes,
):
    start = 0

    while True:
        pos = data.find(
            tag,
            start,
        )

        if pos < 0:
            return

        yield pos
        start = pos + 1


def find_track_sections(
    body: bytes,
) -> tuple[TrackSection, ...]:
    """
    Return every structurally valid mhsd -> mhlt section
    containing a walkable sequence of MHIT records.

    Apple databases may contain more than one such section.
    Callers must disambiguate using stronger evidence such
    as the exact PATH MHOD.
    """

    candidates = []

    for section_off in _all_tag_offsets(
        body,
        b"mhsd",
    ):
        if section_off + 16 > len(body):
            continue

        hlen = _u32(
            body,
            section_off + 4,
        )

        total = _u32(
            body,
            section_off + 8,
        )

        if hlen < 32:
            continue

        if total < hlen:
            continue

        section_end = (
            section_off + total
        )

        if section_end > len(body):
            continue

        mhlt_off = (
            section_off + hlen
        )

        if (
            mhlt_off + 12
            > section_end
        ):
            continue

        if (
            body[
                mhlt_off:
                mhlt_off + 4
            ]
            != b"mhlt"
        ):
            continue

        mhlt_hlen = _u32(
            body,
            mhlt_off + 4,
        )

        count = _u32(
            body,
            mhlt_off + 8,
        )

        if mhlt_hlen < 12:
            continue

        pos = (
            mhlt_off
            + mhlt_hlen
        )

        records = []
        valid = True

        try:
            for _ in range(count):
                if (
                    pos + 16
                    > section_end
                ):
                    valid = False
                    break

                if (
                    body[
                        pos:
                        pos + 4
                    ]
                    != b"mhit"
                ):
                    valid = False
                    break

                rec_hlen = _u32(
                    body,
                    pos + 4,
                )

                rec_total = _u32(
                    body,
                    pos + 8,
                )

                if rec_hlen < 16:
                    valid = False
                    break

                if rec_total < rec_hlen:
                    valid = False
                    break

                rec_end = (
                    pos + rec_total
                )

                if rec_end > section_end:
                    valid = False
                    break

                records.append(
                    (pos, rec_end)
                )

                pos = rec_end

        except CDBError:
            valid = False

        if not valid:
            continue

        if len(records) != count:
            continue

        candidates.append(
            TrackSection(
                section_off=
                    section_off,
                header_len=
                    hlen,
                total_len=
                    total,
                mhlt_off=
                    mhlt_off,
                mhlt_header_len=
                    mhlt_hlen,
                track_count=
                    count,
                records=
                    tuple(records),
            )
        )

    if not candidates:
        raise CDBError(
            "no structurally valid "
            "mhsd/mhlt MHIT sections found"
        )

    return tuple(candidates)

def parse_mhit(
    record: bytes,
) -> dict:
    if record[:4] != b"mhit":
        raise CDBError(
            "record is not MHIT"
        )

    if len(record) < 16:
        raise CDBError(
            "MHIT too short"
        )

    hlen = _u32(record, 4)
    total = _u32(record, 8)
    count = _u32(record, 12)

    if total != len(record):
        raise CDBError(
            "MHIT declared total length "
            "does not equal actual bytes"
        )

    if hlen < 16:
        raise CDBError(
            "MHIT header too short"
        )

    if hlen > total:
        raise CDBError(
            "MHIT header exceeds record"
        )

    children = []

    pos = hlen

    for index in range(count):
        if pos + 16 > total:
            raise CDBError(
                f"MHOD {index} header "
                "outside MHIT"
            )

        if (
            record[
                pos:
                pos + 4
            ]
            != b"mhod"
        ):
            raise CDBError(
                f"expected MHOD at "
                f"{pos:#x}"
            )

        child_hlen = _u32(
            record,
            pos + 4,
        )

        child_total = _u32(
            record,
            pos + 8,
        )

        child_type = _u32(
            record,
            pos + 12,
        )

        if child_hlen < 16:
            raise CDBError(
                "MHOD header too short"
            )

        if child_total < child_hlen:
            raise CDBError(
                "MHOD total smaller "
                "than header"
            )

        end = pos + child_total

        if end > total:
            raise CDBError(
                "MHOD extends beyond MHIT"
            )

        children.append({
            "index": index,
            "offset": pos,
            "header_len":
                child_hlen,
            "total_len":
                child_total,
            "type":
                child_type,
            "raw":
                record[pos:end],
        })

        pos = end

    if pos != total:
        raise CDBError(
            "MHIT has unaccounted bytes "
            "after declared MHOD children"
        )

    return {
        "header_len": hlen,
        "total_len": total,
        "mhod_count": count,
        "track_id":
            _u32(record, 0x10),
        "children": children,
    }


def decode_string_mhod(
    raw: bytes,
) -> str:
    """
    Decode the Apple UTF-16LE string MHOD form
    observed on this iPod.

    Formal MHOD header = 24 bytes.
    String-specific metadata = another 16 bytes.
    Text begins at +0x28.
    """

    if raw[:4] != b"mhod":
        raise CDBError(
            "not an MHOD"
        )

    if _u32(raw, 4) != 24:
        raise CDBError(
            "unexpected string MHOD "
            "header length"
        )

    if _u32(raw, 8) != len(raw):
        raise CDBError(
            "string MHOD total length "
            "mismatch"
        )

    if len(raw) < 40:
        raise CDBError(
            "string MHOD shorter than "
            "fixed 40-byte prefix"
        )

    encoding = _u32(raw, 0x18)
    byte_len = _u32(raw, 0x1C)

    if encoding != 1:
        raise CDBError(
            f"unsupported string encoding "
            f"{encoding}"
        )

    if byte_len % 2:
        raise CDBError(
            "UTF-16 byte length is odd"
        )

    if 40 + byte_len != len(raw):
        raise CDBError(
            "string byte length does not "
            "match MHOD size"
        )

    try:
        return raw[
            40:
            40 + byte_len
        ].decode("utf-16le")

    except UnicodeDecodeError as exc:
        raise CDBError(
            "invalid UTF-16LE MHOD"
        ) from exc


def replace_string_mhod(
    old: bytes,
    value: str,
) -> bytes:
    """
    Preserve the existing 40-byte Apple string
    prefix byte-for-byte except fields that must
    change because string length changes.
    """

    # Validate old representation first.
    decode_string_mhod(old)

    encoded = value.encode(
        "utf-16le"
    )

    prefix = bytearray(
        old[:40]
    )

    _put_u32(
        prefix,
        8,
        40 + len(encoded),
    )

    _put_u32(
        prefix,
        0x1C,
        len(encoded),
    )

    result = (
        bytes(prefix)
        + encoded
    )

    if (
        _u32(result, 8)
        != len(result)
    ):
        raise CDBError(
            "rebuilt string MHOD "
            "length mismatch"
        )

    if (
        decode_string_mhod(result)
        != value
    ):
        raise CDBError(
            "rebuilt string MHOD "
            "failed round-trip"
        )

    return result


def _record_strings(
    parsed: dict,
) -> dict[int, list[str]]:
    result = {}

    for child in parsed["children"]:
        typ = child["type"]

        if typ not in {
            MHOD_TITLE,
            MHOD_PATH,
            MHOD_ALBUM,
            MHOD_ARTIST,
            MHOD_GENRE,
            MHOD_FILETYPE,
            MHOD_ALBUMARTIST,
        }:
            continue

        value = decode_string_mhod(
            child["raw"]
        )

        result.setdefault(
            typ,
            [],
        ).append(value)

    return result


def locate_track_by_path(
    body: bytes,
    apple_path: str,
):
    """
    Locate a track using its exact PATH MHOD across every
    structurally valid MHIT section.

    We require exactly one matching MHIT globally.
    """

    sections = find_track_sections(
        body
    )

    matches = []

    for section in sections:
        for start, end in section.records:
            record = body[start:end]

            parsed = parse_mhit(
                record
            )

            paths = []

            for child in parsed["children"]:
                if (
                    child["type"]
                    != MHOD_PATH
                ):
                    continue

                paths.append(
                    decode_string_mhod(
                        child["raw"]
                    )
                )

            # A normal media MHIT must not have multiple
            # PATH children. If it has none, it simply
            # cannot be our target.
            if len(paths) > 1:
                raise CDBError(
                    "MHIT contains multiple "
                    "PATH MHODs at "
                    f"{start:#x}: {paths!r}"
                )

            if paths == [apple_path]:
                matches.append(
                    (
                        section,
                        start,
                        end,
                        parsed,
                    )
                )

    if len(matches) != 1:
        details = [
            {
                "section":
                    hex(x.section_off),
                "track_count":
                    x.track_count,
            }
            for x in sections
        ]

        raise CDBError(
            f"path {apple_path!r}: "
            "expected exactly one MHIT "
            f"across {len(sections)} "
            "valid sections; "
            f"found {len(matches)}; "
            f"sections={details!r}"
        )

    return matches[0]

def describe_track_by_path(
    body: bytes,
    apple_path: str,
) -> dict:
    (
        section,
        start,
        end,
        parsed,
    ) = locate_track_by_path(
        body,
        apple_path,
    )

    strings = _record_strings(
        parsed
    )

    return {
        "section_offset":
            section.section_off,
        "section_total_len":
            section.total_len,
        "track_count":
            section.track_count,
        "record_offset":
            start,
        "record_total_len":
            end - start,
        "track_id":
            parsed["track_id"],
        "mhod_count":
            parsed["mhod_count"],
        "types": [
            x["type"]
            for x in parsed["children"]
        ],
        "title":
            strings.get(
                MHOD_TITLE,
                [None],
            )[0],
        "path":
            strings.get(
                MHOD_PATH,
                [None],
            )[0],
        "artist":
            strings.get(
                MHOD_ARTIST,
                [None],
            )[0],
        "album":
            strings.get(
                MHOD_ALBUM,
                [None],
            )[0],
        "album_artist":
            strings.get(
                MHOD_ALBUMARTIST,
                [None],
            )[0],
        "genre":
            strings.get(
                MHOD_GENRE,
                [None],
            )[0],
    }


def normalize_track_body(
    body: bytes,
    apple_path: str,
    new_title: str,
) -> tuple[bytes, dict]:
    """
    Existing-track metadata normalization only.

    - locate by exact PATH MHOD
    - replace TITLE MHOD
    - remove ALBUM / ARTIST / ALBUMARTIST
    - preserve every other child byte-for-byte
    - keep track count unchanged
    """

    (
        section,
        rec_start,
        rec_end,
        parsed,
    ) = locate_track_by_path(
        body,
        apple_path,
    )

    old_record = body[
        rec_start:
        rec_end
    ]

    old_strings = _record_strings(
        parsed
    )

    titles = [
        c
        for c in parsed["children"]
        if c["type"] == MHOD_TITLE
    ]

    if len(titles) != 1:
        raise CDBError(
            "expected exactly one TITLE MHOD"
        )

    paths = [
        c
        for c in parsed["children"]
        if c["type"] == MHOD_PATH
    ]

    if len(paths) != 1:
        raise CDBError(
            "expected exactly one PATH MHOD"
        )

    new_children = []
    removed_types = []

    # Hash preserved children before rebuilding so
    # we can prove unknown metadata is untouched.
    preserved_before = []

    for child in parsed["children"]:
        typ = child["type"]
        raw = child["raw"]

        if typ == MHOD_TITLE:
            new_children.append(
                replace_string_mhod(
                    raw,
                    new_title,
                )
            )

        elif typ in DISPLAY_REMOVE_TYPES:
            removed_types.append(
                typ
            )

        else:
            new_children.append(
                raw
            )

            preserved_before.append(
                (
                    typ,
                    sha256_bytes(raw),
                )
            )

    header = bytearray(
        old_record[
            :parsed["header_len"]
        ]
    )

    new_total = (
        len(header)
        + sum(
            len(x)
            for x in new_children
        )
    )

    _put_u32(
        header,
        8,
        new_total,
    )

    _put_u32(
        header,
        12,
        len(new_children),
    )

    new_record = (
        bytes(header)
        + b"".join(
            new_children
        )
    )

    # Only MHIT total length and MHOD count are
    # allowed to change in the fixed MHIT header.
    old_header = bytearray(
        old_record[
            :parsed["header_len"]
        ]
    )

    new_header = bytearray(
        new_record[
            :parsed["header_len"]
        ]
    )

    for off in range(
        parsed["header_len"]
    ):
        if (
            8 <= off < 16
        ):
            continue

        if old_header[off] != new_header[off]:
            raise CDBError(
                "unexpected MHIT header "
                f"change at +{off:#x}"
            )

    reparsed = parse_mhit(
        new_record
    )

    new_strings = _record_strings(
        reparsed
    )

    if (
        new_strings.get(
            MHOD_TITLE
        )
        != [new_title]
    ):
        raise CDBError(
            "rebuilt TITLE mismatch"
        )

    if (
        new_strings.get(
            MHOD_PATH
        )
        != [apple_path]
    ):
        raise CDBError(
            "rebuilt PATH mismatch"
        )

    for typ in DISPLAY_REMOVE_TYPES:
        if typ in new_strings:
            raise CDBError(
                f"MHOD type {typ} "
                "survived normalization"
            )

    preserved_after = []

    for child in reparsed["children"]:
        typ = child["type"]

        if typ == MHOD_TITLE:
            continue

        preserved_after.append(
            (
                typ,
                sha256_bytes(
                    child["raw"]
                ),
            )
        )

    if (
        preserved_before
        != preserved_after
    ):
        raise CDBError(
            "non-display MHOD bytes changed"
        )

    delta = (
        len(new_record)
        - len(old_record)
    )

    new_body = bytearray(
        body[:rec_start]
        + new_record
        + body[rec_end:]
    )

    # mhsd total length encloses this MHIT.
    old_section_total = (
        section.total_len
    )

    _put_u32(
        new_body,
        section.section_off + 8,
        old_section_total + delta,
    )

    new_body = bytes(new_body)

    # Everything after the selected MHIT must be
    # byte-identical, just shifted by delta bytes.
    new_rec_end = (
        rec_start
        + len(new_record)
    )

    if (
        new_body[new_rec_end:]
        != body[rec_end:]
    ):
        raise CDBError(
            "bytes after selected MHIT changed"
        )

    # Prefix may differ only in mhsd total length.
    old_prefix = bytearray(
        body[:rec_start]
    )

    new_prefix = bytearray(
        new_body[:rec_start]
    )

    for off in range(
        section.section_off + 8,
        section.section_off + 12,
    ):
        old_prefix[off] = 0
        new_prefix[off] = 0

    if old_prefix != new_prefix:
        raise CDBError(
            "unexpected bytes changed before MHIT"
        )

    # Re-parse whole track section after resizing.
    (
        new_section,
        _new_start,
        _new_end,
        _new_parsed,
    ) = locate_track_by_path(
        new_body,
        apple_path,
    )

    if (
        new_section.track_count
        != section.track_count
    ):
        raise CDBError(
            "track count changed"
        )

    after = describe_track_by_path(
        new_body,
        apple_path,
    )

    if after["title"] != new_title:
        raise CDBError(
            "post-transform title mismatch"
        )

    audit = {
        "path":
            apple_path,
        "track_id":
            parsed["track_id"],
        "old_title":
            old_strings.get(
                MHOD_TITLE,
                [None],
            )[0],
        "new_title":
            new_title,
        "old_types": [
            x["type"]
            for x in parsed["children"]
        ],
        "new_types":
            after["types"],
        "removed_types":
            removed_types,
        "old_record_len":
            len(old_record),
        "new_record_len":
            len(new_record),
        "record_delta":
            delta,
        "old_section_len":
            old_section_total,
        "new_section_len":
            old_section_total + delta,
        "track_count":
            section.track_count,
        "preserved_children":
            preserved_before,
    }

    return (
        new_body,
        audit,
    )


def build_unsigned_container(
    base_signed: bytes,
    new_body: bytes,
) -> bytes:
    """
    Build the unsigned Apple container.

    Hash72 is deliberately all-zero. Signing is a
    separate later stage.
    """

    # Validate the base and recover its body first.
    inflate_container(
        base_signed
    )

    header = bytearray(
        base_signed[
            :MHBD_HEADER_LEN
        ]
    )

    header[
        HASH72_OFF:
        HASH72_OFF + HASH72_LEN
    ] = bytes(HASH72_LEN)

    compressed = zlib.compress(
        new_body,
        level=1,
    )

    if not compressed.startswith(
        b"\x78\x01"
    ):
        raise CDBError(
            "unexpected zlib level-1 prefix"
        )

    total_len = (
        MHBD_HEADER_LEN
        + len(compressed)
    )

    _put_u32(
        header,
        8,
        total_len,
    )

    unsigned = (
        bytes(header)
        + compressed
    )

    if (
        _u32(unsigned, 8)
        != len(unsigned)
    ):
        raise CDBError(
            "unsigned mhbd length mismatch"
        )

    if (
        unsigned[
            HASH72_OFF:
            HASH72_OFF + HASH72_LEN
        ]
        != bytes(HASH72_LEN)
    ):
        raise CDBError(
            "unsigned Hash72 is not zero"
        )

    if inflate_container(
        unsigned
    ) != new_body:
        raise CDBError(
            "unsigned CDB round-trip mismatch"
        )

    # Header preservation: only total-length and
    # Hash72 may differ at this stage.
    old_header = base_signed[
        :MHBD_HEADER_LEN
    ]

    new_header = unsigned[
        :MHBD_HEADER_LEN
    ]

    allowed = (
        set(range(8, 12))
        | set(
            range(
                HASH72_OFF,
                HASH72_OFF
                + HASH72_LEN,
            )
        )
    )

    unexpected = [
        i
        for i, (a, b) in enumerate(
            zip(
                old_header,
                new_header,
            )
        )
        if a != b
        and i not in allowed
    ]

    if unexpected:
        raise CDBError(
            "unexpected mhbd header "
            f"changes: {unexpected}"
        )

    return unsigned
