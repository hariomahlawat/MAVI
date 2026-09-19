#!/usr/bin/env python3
"""Structural analysis of Windows native artefacts for reproducibility work.

Two builds of the same source with the same toolchain produce MSVC/NVCC output
that differs in a small number of *named* header fields -- build timestamps and
linker-generated debug identifiers -- while the compiled code is identical. The
question a reproducibility gate must answer is not "do the bytes differ" but
"does every differing byte lie inside a field we can name".

This module answers that mechanically. For each supported format it derives the
byte ranges of the documented metadata fields, zeroes exactly those ranges in
both inputs, and compares what is left. If the masked copies are equal then
every differing byte was inside a declared field, which is a proof rather than
an assertion. If anything is left over, the difference is reported as
unexplained and no equivalence is claimed.

Three rules keep it fail-closed:

* A format that will not parse is never normalised. `unparsable-native-format`
  is a refusal, not a pass.
* Only fields whose meaning is documented are declared. A header word that
  varies for reasons nobody has established is reported with its decoded values
  so the question can be settled empirically, and it blocks equivalence until it
  is.
* The declared ranges are small, named and reported. A caller can see exactly
  how many bytes were excused and which field excused them.

Stdlib only: the C2 host runs this beside the build, and the object trees it
reads are hundreds of megabytes of intermediate output.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Iterable

# The CLSID MSVC stamps into every /bigobj header, little-endian mixed as the
# GUID is laid out on disk: {D1BAA1C7-BAEE-4BA9-AF20-FAF66AA4DCB8}.
_BIGOBJ_CLASS_ID = bytes(
    (
        0xC7, 0xA1, 0xBA, 0xD1, 0xEE, 0xBA, 0xA9, 0x4B,
        0xAF, 0x20, 0xFA, 0xF6, 0x6A, 0xA4, 0xDC, 0xB8,
    )
)
_BIGOBJ_SIGNATURE = b"\x00\x00\xff\xff"
_BIGOBJ_HEADER_SIZE = 56
_COFF_HEADER_SIZE = 20

# Machine types MSVC and NVCC emit for the frozen toolchain, plus the ones a
# cross build would plausibly produce. An unknown machine means the leading
# bytes are not a COFF header and guessing would mask a real difference.
_KNOWN_MACHINES = frozenset({0x014C, 0x8664, 0xAA64, 0x01C4, 0x0200})

_PE_DEBUG_ENTRY_SIZE = 28
_PE_DEBUG_TYPE_CODEVIEW = 2
_PE_DEBUG_TYPE_REPRO = 16
_PE_DIRECTORY_EXPORT = 0
_PE_DIRECTORY_DEBUG = 6

FORMAT_COFF_OBJECT = "coff-object"
FORMAT_BIGOBJ_OBJECT = "bigobj-object"
FORMAT_PE_IMAGE = "pe-image"

#: Classifications that mean two artefacts carry the same compiled content.
ACCEPTABLE_CLASSIFICATIONS = frozenset(
    {"identical", "metadata-normalized-identical"}
)


class NativeFormatError(ValueError):
    """The payload is not the native format it appears to claim."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NormalizedField:
    """One byte range whose variance between builds is documented and benign."""

    name: str
    offset: int
    length: int

    @property
    def end(self) -> int:
        return self.offset + self.length


@dataclass(frozen=True, slots=True)
class ObservedField:
    """One byte range that varies but whose meaning is *not* established.

    Reported, decoded, and never normalised. Its presence blocks equivalence.
    """

    name: str
    offset: int
    length: int

    @property
    def end(self) -> int:
        return self.offset + self.length


@dataclass(frozen=True, slots=True)
class NativeLayout:
    native_format: str
    normalized: tuple[NormalizedField, ...]
    observed: tuple[ObservedField, ...]
    detail: dict[str, object]


def _u16(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise NativeFormatError("native_format_truncated")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise NativeFormatError("native_format_truncated")
    return struct.unpack_from("<I", data, offset)[0]


def detect_native_format(data: bytes) -> str | None:
    """Name the format, or ``None`` when the payload is not one we analyse."""
    if len(data) >= 2 and data[:2] == b"MZ":
        return FORMAT_PE_IMAGE
    if len(data) >= _BIGOBJ_HEADER_SIZE and data[:4] == _BIGOBJ_SIGNATURE:
        return FORMAT_BIGOBJ_OBJECT
    if len(data) >= _COFF_HEADER_SIZE:
        machine = struct.unpack_from("<H", data, 0)[0]
        if machine in _KNOWN_MACHINES:
            return FORMAT_COFF_OBJECT
    return None


def _coff_object_layout(data: bytes) -> NativeLayout:
    if len(data) < _COFF_HEADER_SIZE:
        raise NativeFormatError("native_format_truncated")
    machine = _u16(data, 0)
    if machine not in _KNOWN_MACHINES:
        raise NativeFormatError("coff_machine_unknown")
    sections = _u16(data, 2)
    optional_header = _u16(data, 16)
    # An object file carries no optional header. A non-zero value here means the
    # bytes are something else that happens to start with a known machine word.
    if optional_header != 0:
        raise NativeFormatError("coff_object_has_optional_header")
    symbol_table = _u32(data, 8)
    if symbol_table > len(data):
        raise NativeFormatError("coff_symbol_table_out_of_range")
    if _COFF_HEADER_SIZE + sections * 40 > len(data):
        raise NativeFormatError("coff_section_table_out_of_range")
    return NativeLayout(
        native_format=FORMAT_COFF_OBJECT,
        normalized=(NormalizedField("coff.TimeDateStamp", 4, 4),),
        observed=(),
        detail={
            "machine": f"0x{machine:04x}",
            "numberOfSections": sections,
            "numberOfSymbols": _u32(data, 12),
        },
    )


def _bigobj_object_layout(data: bytes) -> NativeLayout:
    if len(data) < _BIGOBJ_HEADER_SIZE:
        raise NativeFormatError("native_format_truncated")
    if data[:4] != _BIGOBJ_SIGNATURE:
        raise NativeFormatError("bigobj_signature_invalid")
    version = _u16(data, 4)
    if version < 2:
        raise NativeFormatError("bigobj_version_unsupported")
    machine = _u16(data, 6)
    if machine not in _KNOWN_MACHINES:
        raise NativeFormatError("bigobj_machine_unknown")
    if data[12:28] != _BIGOBJ_CLASS_ID:
        # Without the CLSID this is not MSVC's anonymous-object header and the
        # field offsets below would be guesses.
        raise NativeFormatError("bigobj_class_id_invalid")
    sections = _u32(data, 44)
    symbol_table = _u32(data, 48)
    if symbol_table > len(data):
        raise NativeFormatError("bigobj_symbol_table_out_of_range")
    if _BIGOBJ_HEADER_SIZE + sections * 40 > len(data):
        raise NativeFormatError("bigobj_section_table_out_of_range")
    return NativeLayout(
        native_format=FORMAT_BIGOBJ_OBJECT,
        normalized=(NormalizedField("bigobj.TimeDateStamp", 8, 4),),
        # `MetaDataSize` and `MetaDataOffset` are CLR metadata fields that MSVC
        # leaves zero for native objects. LLVM's reader calls them `unused3` and
        # `unused4`. They are declared here so that variance in them is decoded
        # and reported rather than silently masked, because normalising a field
        # whose meaning is unestablished is the one thing this module must not
        # do -- and because a 2026-era timestamp and a small metadata size are
        # distinguishable on sight once the values are printed.
        observed=(
            ObservedField("bigobj.MetaDataSize", 36, 4),
            ObservedField("bigobj.MetaDataOffset", 40, 4),
        ),
        detail={
            "machine": f"0x{machine:04x}",
            "version": version,
            "numberOfSections": sections,
            "numberOfSymbols": _u32(data, 52),
        },
    )


@dataclass(frozen=True, slots=True)
class _Section:
    virtual_address: int
    virtual_size: int
    pointer_to_raw_data: int
    size_of_raw_data: int


def _pe_sections(data: bytes, offset: int, count: int) -> tuple[_Section, ...]:
    sections: list[_Section] = []
    for index in range(count):
        base = offset + index * 40
        if base + 40 > len(data):
            raise NativeFormatError("pe_section_table_out_of_range")
        sections.append(
            _Section(
                virtual_size=_u32(data, base + 8),
                virtual_address=_u32(data, base + 12),
                size_of_raw_data=_u32(data, base + 16),
                pointer_to_raw_data=_u32(data, base + 20),
            )
        )
    return tuple(sections)


def _rva_to_offset(rva: int, sections: Iterable[_Section]) -> int | None:
    for section in sections:
        span = max(section.virtual_size, section.size_of_raw_data)
        if section.virtual_address <= rva < section.virtual_address + span:
            delta = rva - section.virtual_address
            if delta >= section.size_of_raw_data:
                return None
            return section.pointer_to_raw_data + delta
    return None


def _pe_image_layout(data: bytes) -> NativeLayout:
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise NativeFormatError("pe_dos_header_invalid")
    pe = _u32(data, 0x3C)
    if pe + 24 > len(data):
        raise NativeFormatError("pe_header_out_of_range")
    if data[pe : pe + 4] != b"PE\x00\x00":
        raise NativeFormatError("pe_signature_invalid")

    coff = pe + 4
    machine = _u16(data, coff)
    if machine not in _KNOWN_MACHINES:
        raise NativeFormatError("pe_machine_unknown")
    section_count = _u16(data, coff + 2)
    optional_size = _u16(data, coff + 16)
    optional = coff + _COFF_HEADER_SIZE
    if optional + optional_size > len(data):
        raise NativeFormatError("pe_optional_header_out_of_range")
    if optional_size < 68:
        # Anything smaller cannot carry the checksum, let alone a data
        # directory, so the file is not a linked image.
        raise NativeFormatError("pe_optional_header_too_small")

    magic = _u16(data, optional)
    if magic == 0x10B:
        directory_count_offset = optional + 92
        directory_offset = optional + 96
    elif magic == 0x20B:
        directory_count_offset = optional + 108
        directory_offset = optional + 112
    else:
        raise NativeFormatError("pe_optional_magic_unknown")

    normalized = [
        NormalizedField("pe.coff.TimeDateStamp", coff + 4, 4),
        NormalizedField("pe.optional.CheckSum", optional + 64, 4),
    ]
    detail: dict[str, object] = {
        "machine": f"0x{machine:04x}",
        "optionalHeaderMagic": f"0x{magic:03x}",
        "numberOfSections": section_count,
        "debugEntries": [],
        "reproDebugEntry": False,
    }

    sections = _pe_sections(data, optional + optional_size, section_count)

    if directory_count_offset + 4 <= optional + optional_size:
        directory_count = _u32(data, directory_count_offset)
    else:
        directory_count = 0

    def directory(index: int) -> tuple[int, int] | None:
        if index >= directory_count:
            return None
        base = directory_offset + index * 8
        if base + 8 > optional + optional_size:
            raise NativeFormatError("pe_data_directory_out_of_range")
        return _u32(data, base), _u32(data, base + 4)

    export = directory(_PE_DIRECTORY_EXPORT)
    if export is not None and export[0] and export[1] >= 8:
        offset = _rva_to_offset(export[0], sections)
        if offset is not None and offset + 8 <= len(data):
            normalized.append(
                NormalizedField("pe.export.TimeDateStamp", offset + 4, 4)
            )

    debug = directory(_PE_DIRECTORY_DEBUG)
    if debug is not None and debug[0] and debug[1]:
        table = _rva_to_offset(debug[0], sections)
        if table is None:
            raise NativeFormatError("pe_debug_directory_unmapped")
        count = debug[1] // _PE_DEBUG_ENTRY_SIZE
        if table + count * _PE_DEBUG_ENTRY_SIZE > len(data):
            raise NativeFormatError("pe_debug_directory_out_of_range")
        entries: list[dict[str, object]] = []
        for index in range(count):
            base = table + index * _PE_DEBUG_ENTRY_SIZE
            entry_type = _u32(data, base + 12)
            size_of_data = _u32(data, base + 20)
            pointer = _u32(data, base + 24)
            normalized.append(
                NormalizedField(
                    f"pe.debug[{index}].TimeDateStamp", base + 4, 4
                )
            )
            entries.append({"index": index, "type": entry_type})
            if entry_type == _PE_DEBUG_TYPE_REPRO:
                detail["reproDebugEntry"] = True
            if entry_type != _PE_DEBUG_TYPE_CODEVIEW:
                continue
            # RSDS: signature(4) GUID(16) Age(4) then a NUL-terminated PDB path.
            # The linker mints a fresh GUID on every link unless the build is
            # made deterministic, so it is the dominant source of PE variance.
            # The PDB path is *not* normalised: it is an embedded absolute build
            # path and belongs to that category, where it stays visible.
            if size_of_data < 24 or pointer + 24 > len(data):
                raise NativeFormatError("pe_codeview_record_out_of_range")
            if data[pointer : pointer + 4] != b"RSDS":
                raise NativeFormatError("pe_codeview_signature_unknown")
            normalized.append(
                NormalizedField(f"pe.debug[{index}].codeview.Guid", pointer + 4, 16)
            )
            normalized.append(
                NormalizedField(f"pe.debug[{index}].codeview.Age", pointer + 20, 4)
            )
        detail["debugEntries"] = entries

    normalized.sort(key=lambda field: (field.offset, field.name))
    return NativeLayout(
        native_format=FORMAT_PE_IMAGE,
        normalized=tuple(normalized),
        observed=(),
        detail=detail,
    )


_LAYOUTS = {
    FORMAT_COFF_OBJECT: _coff_object_layout,
    FORMAT_BIGOBJ_OBJECT: _bigobj_object_layout,
    FORMAT_PE_IMAGE: _pe_image_layout,
}


def describe_native_layout(data: bytes) -> NativeLayout:
    """Parse ``data`` and name the metadata fields it is allowed to vary in."""
    native_format = detect_native_format(data)
    if native_format is None:
        raise NativeFormatError("native_format_unrecognised")
    layout = _LAYOUTS[native_format](data)
    for field in (*layout.normalized, *layout.observed):
        if field.offset < 0 or field.end > len(data):
            raise NativeFormatError("native_field_out_of_range")
    return layout


def normalized_copy(data: bytes, layout: NativeLayout) -> bytes:
    """Return ``data`` with exactly the declared metadata ranges zeroed."""
    buffer = bytearray(data)
    for field in layout.normalized:
        buffer[field.offset : field.end] = b"\x00" * field.length
    return bytes(buffer)


def normalized_byte_count(layout: NativeLayout) -> int:
    covered: set[int] = set()
    for field in layout.normalized:
        covered.update(range(field.offset, field.end))
    return len(covered)


def differing_offsets(left: bytes, right: bytes, *, limit: int) -> list[int]:
    """Offsets at which two equal-length payloads differ, up to ``limit``."""
    found: list[int] = []
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            found.append(index)
            if len(found) >= limit:
                break
    return found


def _decode_dword(data: bytes, offset: int) -> dict[str, object]:
    value = struct.unpack_from("<I", data, offset)[0]
    return {"uint32": value, "hex": f"0x{value:08x}"}



# ---------------------------------------------------------------------------
# Embedded absolute build paths
# ---------------------------------------------------------------------------
#
# A path embedded in an artefact defeats relocatable reproduction, so the scan
# must be broad. Breadth is what made the first version wrong: `https://x/y`
# contains `s://x/y`, which reads as a drive letter followed by a separator, so
# every GitHub, arXiv and licence URL in MMCV's docstrings was reported as a
# build path. A detector that cries wolf on documentation strings is worse than
# none, because the real finding arrives in a list nobody reads.
#
# Two guards, both mechanical rather than an allow-list of known hosts:
#   * a drive letter must not be the tail of a longer word, and the separator
#     after it must not be doubled -- `C:\x` and `C:/x` match, `s://x` does not;
#   * any match overlapping a `scheme://...` token is dropped outright, which
#     catches the residue regardless of how the scheme is spelled.

_URL_TOKEN = re.compile(rb"[A-Za-z][A-Za-z0-9+.\-]{1,31}://[^\x00-\x20\"<>|]{1,400}")
_EMBEDDED_PATH = re.compile(
    # Windows: a bare drive letter, not preceded by a word character (which
    # would make it the last letter of `https`), and not followed by `//`.
    rb"(?<![A-Za-z0-9_])[A-Za-z]:(?:\\|/(?!/))[^\x00-\x1f\"<>|*?]{6,120}"
    # POSIX: a rooted path under a directory a build actually runs from, not
    # preceded by anything that would make it the tail of a URL or a longer
    # path fragment.
    rb"|(?<![A-Za-z0-9_:/.\-])/(?:home|build|tmp|work|opt|usr|root|var|mnt|Users)"
    rb"/[\w./+\-]{4,120}"
)


def _url_spans(data: bytes) -> list[tuple[int, int]]:
    return [match.span() for match in _URL_TOKEN.finditer(data)]


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < other_end and other_start < end for other_start, other_end in spans)


def embedded_build_path_spans(data: bytes) -> list[tuple[int, int, str]]:
    """Absolute build paths in ``data`` as ``(start, end, text)``.

    URLs are excluded mechanically rather than by host allow-list.
    """
    urls = _url_spans(data)
    found: list[tuple[int, int, str]] = []
    for match in _EMBEDDED_PATH.finditer(data):
        span = match.span()
        if _overlaps(span, urls):
            continue
        text = match.group().decode("utf-8", "replace").rstrip("\x00")
        found.append((span[0], span[1], text))
    return found


def embedded_build_paths(data: bytes) -> list[str]:
    """Distinct absolute build paths in ``data``, sorted."""
    return sorted({text for _start, _end, text in embedded_build_path_spans(data)})


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

#: How many residual differing offsets to report before truncating. Enough to
#: diagnose, bounded so a genuinely divergent 27 MB binary cannot produce a
#: report nobody can read.
RESIDUAL_SAMPLE_LIMIT = 32


def compare_native_payloads(
    left: bytes,
    right: bytes,
    *,
    residual_limit: int = RESIDUAL_SAMPLE_LIMIT,
) -> dict[str, object]:
    """Classify the difference between two native payloads.

    The classification is one of:

    ``identical``
        The bytes are equal.
    ``metadata-normalized-identical``
        Every differing byte lay inside a declared, documented metadata field.
    ``embedded-build-path-divergence``
        Differences remain and all of them fall inside an embedded absolute
        build path. The builds ran from different directories.
    ``undocumented-header-field-divergence``
        Differences remain and all of them fall inside a header field that is
        declared-but-unratified. Reported with decoded values so the owner can
        settle what the field is.
    ``unexplained-native-difference``
        Differences remain that nothing above accounts for.
    ``native-size-mismatch``
        The payloads are different lengths, so no field-wise proof is possible.
    ``native-format-mismatch``
        The two payloads are different formats.
    ``unparsable-native-format``
        At least one payload would not parse. Never normalised.

    Only ``identical`` and ``metadata-normalized-identical`` mean the compiled
    content agrees.
    """
    result: dict[str, object] = {}

    if left == right:
        native_format = detect_native_format(left)
        return {
            "classification": "identical",
            "format": native_format,
            "byteIdentical": True,
            "normalizedFields": [],
            "residualDifferences": [],
            "residualDifferenceCount": 0,
        }

    left_format = detect_native_format(left)
    right_format = detect_native_format(right)
    if left_format != right_format:
        return {
            "classification": "native-format-mismatch",
            "format": None,
            "leftFormat": left_format,
            "rightFormat": right_format,
            "byteIdentical": False,
            "normalizedFields": [],
            "residualDifferences": [],
            "residualDifferenceCount": None,
        }

    if left_format is None:
        return {
            "classification": "unparsable-native-format",
            "format": None,
            "reason": "native_format_unrecognised",
            "byteIdentical": False,
            "normalizedFields": [],
            "residualDifferences": [],
            "residualDifferenceCount": None,
        }

    try:
        left_layout = describe_native_layout(left)
        right_layout = describe_native_layout(right)
    except NativeFormatError as exc:
        return {
            "classification": "unparsable-native-format",
            "format": left_format,
            "reason": exc.code,
            "byteIdentical": False,
            "normalizedFields": [],
            "residualDifferences": [],
            "residualDifferenceCount": None,
        }

    result["format"] = left_format
    result["byteIdentical"] = False
    result["normalizedByteCount"] = {
        "left": normalized_byte_count(left_layout),
        "right": normalized_byte_count(right_layout),
    }
    result["detail"] = {"left": left_layout.detail, "right": right_layout.detail}

    if len(left) != len(right):
        # Masking cannot prove anything about payloads of different lengths:
        # the fields would no longer line up.
        result["classification"] = "native-size-mismatch"
        result["sizeBytes"] = {"left": len(left), "right": len(right)}
        result["normalizedFields"] = []
        result["residualDifferences"] = []
        result["residualDifferenceCount"] = None
        return result

    # Which declared fields actually differ, as opposed to merely being
    # declared. Reporting the whole declaration would overstate what varied.
    differing_named: list[dict[str, object]] = []
    for field in left_layout.normalized:
        if left[field.offset : field.end] != right[field.offset : field.end]:
            entry: dict[str, object] = {
                "name": field.name,
                "offset": field.offset,
                "length": field.length,
            }
            if field.length == 4:
                entry["left"] = _decode_dword(left, field.offset)
                entry["right"] = _decode_dword(right, field.offset)
            differing_named.append(entry)
    result["normalizedFields"] = differing_named

    masked_left = normalized_copy(left, left_layout)
    masked_right = normalized_copy(right, right_layout)
    if masked_left == masked_right:
        result["classification"] = "metadata-normalized-identical"
        result["residualDifferences"] = []
        result["residualDifferenceCount"] = 0
        return result

    residual = differing_offsets(masked_left, masked_right, limit=residual_limit + 1)
    truncated = len(residual) > residual_limit
    sample = residual[:residual_limit]

    # Count the whole residual set, not the sample: "3 bytes left over" and
    # "3 million bytes left over" are different engineering situations and the
    # bounded sample cannot tell them apart.
    residual_count = sum(1 for a, b in zip(masked_left, masked_right) if a != b)

    observed_fields = {
        field.name: field
        for field in (*left_layout.observed, *right_layout.observed)
    }
    left_paths = embedded_build_path_spans(left)
    right_paths = embedded_build_path_spans(right)

    def classify_offset(offset: int) -> dict[str, object]:
        for field in observed_fields.values():
            if field.offset <= offset < field.end:
                entry: dict[str, object] = {
                    "offset": offset,
                    "category": "undocumented-header-field",
                    "field": field.name,
                }
                if field.length == 4:
                    entry["left"] = _decode_dword(left, field.offset)
                    entry["right"] = _decode_dword(right, field.offset)
                return entry
        for start, end, text in left_paths:
            if start <= offset < end:
                return {
                    "offset": offset,
                    "category": "embedded-build-path",
                    "left": text,
                }
        for start, end, text in right_paths:
            if start <= offset < end:
                return {
                    "offset": offset,
                    "category": "embedded-build-path",
                    "right": text,
                }
        return {
            "offset": offset,
            "category": "unexplained",
            "left": f"0x{left[offset]:02x}",
            "right": f"0x{right[offset]:02x}",
        }

    classified = [classify_offset(offset) for offset in sample]
    result["residualDifferences"] = classified
    result["residualDifferenceCount"] = residual_count
    result["residualSampleTruncated"] = truncated

    categories = {entry["category"] for entry in classified}
    if truncated or "unexplained" in categories or not categories:
        # A truncated sample cannot establish that *every* residual byte is
        # accounted for, so it never yields a named cause.
        result["classification"] = "unexplained-native-difference"
    elif categories == {"embedded-build-path"}:
        result["classification"] = "embedded-build-path-divergence"
    elif categories == {"undocumented-header-field"}:
        result["classification"] = "undocumented-header-field-divergence"
    else:
        result["classification"] = "unexplained-native-difference"
    return result


__all__ = [
    "ACCEPTABLE_CLASSIFICATIONS",
    "RESIDUAL_SAMPLE_LIMIT",
    "FORMAT_BIGOBJ_OBJECT",
    "FORMAT_COFF_OBJECT",
    "FORMAT_PE_IMAGE",
    "NativeFormatError",
    "NativeLayout",
    "NormalizedField",
    "ObservedField",
    "compare_native_payloads",
    "describe_native_layout",
    "detect_native_format",
    "embedded_build_path_spans",
    "embedded_build_paths",
    "differing_offsets",
    "normalized_byte_count",
    "normalized_copy",
]
