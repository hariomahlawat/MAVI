"""Faithful synthetic MSVC/NVCC artefacts for reproducibility tests.

A fixture that is not a faithful model of the artefact does not exercise the
code under test -- it exercises the preflight that rejects it, and every branch
behind that preflight returns the same refusal. These builders therefore
produce objects and images whose internal offsets are self-consistent: symbol
tables that are actually present, section tables that fit, data directories
that resolve through the section map. The parser's own out-of-range guards are
tested separately, by corrupting a fixture that was valid first.
"""

from __future__ import annotations

import struct

BIGOBJ_CLASS_ID = bytes(
    (
        0xC7, 0xA1, 0xBA, 0xD1, 0xEE, 0xBA, 0xA9, 0x4B,
        0xAF, 0x20, 0xFA, 0xF6, 0x6A, 0xA4, 0xDC, 0xB8,
    )
)

_MACHINE_AMD64 = 0x8664
_SYMBOL_SIZE = 18


def _symbol_table(count: int) -> bytes:
    symbols = b"".join(
        b"sym" + bytes([0x30 + index]) + b"\x00" * 4
        + struct.pack("<IhHBB", index, 1, 0, 2, 0)
        for index in range(count)
    )
    assert len(symbols) == count * _SYMBOL_SIZE
    return symbols + struct.pack("<I", 4)


def _section_header(name: bytes, size: int, raw_pointer: int) -> bytes:
    return (
        name.ljust(8, b"\x00")
        + struct.pack("<IIII", size, 0x1000, size, raw_pointer)
        + struct.pack("<IIHHI", 0, 0, 0, 0, 0x60000020)
    )


def coff_object(
    *,
    timestamp: int = 0x68A00000,
    body: bytes = b"\x90" * 512,
    symbols: int = 3,
    machine: int = _MACHINE_AMD64,
    optional_header_size: int = 0,
) -> bytes:
    """A standard (non-BIGOBJ) COFF object with a present symbol table."""
    header_size = 20
    section_offset = header_size + 40
    symbol_offset = section_offset + len(body)
    header = struct.pack(
        "<HHIIIHH",
        machine,
        1,
        timestamp,
        symbol_offset,
        symbols,
        optional_header_size,
        0,
    )
    return (
        header
        + _section_header(b".text", len(body), section_offset)
        + body
        + _symbol_table(symbols)
    )


def bigobj_object(
    *,
    timestamp: int = 0x68A00000,
    body: bytes = b"\x90" * 512,
    symbols: int = 3,
    machine: int = _MACHINE_AMD64,
    version: int = 2,
    class_id: bytes = BIGOBJ_CLASS_ID,
    metadata_size: int = 0,
    metadata_offset: int = 0,
) -> bytes:
    """An MSVC ``/bigobj`` anonymous-object-header object."""
    header_size = 56
    section_offset = header_size + 40
    symbol_offset = section_offset + len(body)
    header = (
        struct.pack("<HHHH", 0x0000, 0xFFFF, version, machine)
        + struct.pack("<I", timestamp)
        + class_id
        + struct.pack("<IIII", 0, 0, metadata_size, metadata_offset)
        + struct.pack("<III", 1, symbol_offset, symbols)
    )
    assert len(header) == header_size
    return (
        header
        + _section_header(b".text", len(body), section_offset)
        + body
        + _symbol_table(symbols)
    )


def pe_image(
    *,
    timestamp: int = 0x68A00000,
    checksum: int = 0x0001C0DE,
    body: bytes = b"\x90" * 1024,
    codeview_guid: bytes = bytes(range(16)),
    codeview_age: int = 1,
    pdb_path: bytes = rb"C:\mavi-c2\build-a\mmcv\_ext.pdb",
    debug_timestamp: int | None = None,
    export_timestamp: int | None = None,
    include_debug: bool = True,
    repro_entry: bool = False,
    signature: bytes = b"PE\x00\x00",
    optional_magic: int = 0x20B,
    codeview_signature: bytes = b"RSDS",
) -> bytes:
    """A PE32+ image carrying a debug directory with an RSDS CodeView record.

    The layout is built bottom-up so every RVA resolves through the section
    table, which is what makes the parser's RVA arithmetic actually run.
    """
    if debug_timestamp is None:
        debug_timestamp = timestamp
    if export_timestamp is None:
        export_timestamp = timestamp

    dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40)
    optional_size = 240
    header_span = 0x40 + 4 + 20 + optional_size + 40
    section_raw = (header_span + 0x1FF) & ~0x1FF
    section_rva = 0x1000

    # Section payload: export directory, then the debug entry array, then the
    # CodeView record, then the code body.
    export_dir = struct.pack("<IIIIIIIIIII", 0, export_timestamp, 0, 0, 1, 0, 0, 0, 0, 0, 0)
    export_rva = section_rva
    cursor = len(export_dir)

    entries = (2 if repro_entry else 1) if include_debug else 0
    debug_array_rva = section_rva + cursor
    debug_array_size = entries * 28
    cursor += debug_array_size

    codeview = (
        codeview_signature
        + codeview_guid
        + struct.pack("<I", codeview_age)
        + pdb_path
        + b"\x00"
    )
    codeview_rva = section_rva + cursor
    if include_debug:
        cursor += len(codeview)

    repro_blob = struct.pack("<I", 4) + b"\xde\xad\xbe\xef"
    repro_rva = section_rva + cursor
    if include_debug and repro_entry:
        cursor += len(repro_blob)

    payload_parts = [export_dir]
    debug_entries = b"".join(
        struct.pack(
            "<IIHHIIII",
            0,
            debug_timestamp,
            0,
            0,
            2 if index == 0 else 16,
            len(codeview) if index == 0 else len(repro_blob),
            codeview_rva if index == 0 else repro_rva,
            section_raw + (codeview_rva - section_rva)
            if index == 0
            else section_raw + (repro_rva - section_rva),
        )
        for index in range(entries)
    )
    payload_parts.append(debug_entries)
    if include_debug:
        payload_parts.append(codeview)
        if repro_entry:
            payload_parts.append(repro_blob)
    payload_parts.append(body)
    payload = b"".join(payload_parts)

    coff = struct.pack(
        "<HHIIIHH", _MACHINE_AMD64, 1, timestamp, 0, 0, optional_size, 0x2022
    )

    optional = bytearray(optional_size)
    struct.pack_into("<H", optional, 0, optional_magic)
    struct.pack_into("<I", optional, 16, section_rva)          # entry point
    struct.pack_into("<I", optional, 32, 0x1000)               # section align
    struct.pack_into("<I", optional, 36, 0x200)                # file align
    struct.pack_into("<I", optional, 56, section_rva + len(payload))
    struct.pack_into("<I", optional, 60, section_raw)
    struct.pack_into("<I", optional, 64, checksum)
    struct.pack_into("<I", optional, 108, 16)                  # NumberOfRvaAndSizes
    struct.pack_into("<II", optional, 112, export_rva, len(export_dir))
    if include_debug:
        struct.pack_into(
            "<II", optional, 112 + 6 * 8, debug_array_rva, debug_array_size
        )

    section = (
        b".text".ljust(8, b"\x00")
        + struct.pack("<IIII", len(payload), section_rva, len(payload), section_raw)
        + struct.pack("<IIHHI", 0, 0, 0, 0, 0x60000020)
    )

    head = dos + signature + coff + bytes(optional) + section
    return head + b"\x00" * (section_raw - len(head)) + payload
