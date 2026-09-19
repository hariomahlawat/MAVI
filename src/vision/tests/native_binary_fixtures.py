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
    debug_in_code_section: bool = False,
    codeview_size_of_data: int | None = None,
    codeview_address_override: int | None = None,
    extra_debug_entries: int = 0,
) -> bytes:
    """A PE32+ image with a read-only data section and a code section.

    The split matters. MSVC puts the export directory, the debug directory and
    the CodeView record in read-only data, never in `.text`, and the analyser
    refuses to normalise a range that lands in an executable section. A
    single-section fixture would put the metadata in code and be rejected --
    correctly, which is why `debug_in_code_section` exists as an explicit
    negative case rather than as the default shape.

    Every RVA resolves through the section table, so the parser's address
    arithmetic and its mapped-versus-raw consistency check both actually run.
    """
    if debug_timestamp is None:
        debug_timestamp = timestamp
    if export_timestamp is None:
        export_timestamp = timestamp

    dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40)
    optional_size = 240
    header_span = 0x40 + 4 + 20 + optional_size + 2 * 40
    rdata_raw = (header_span + 0x1FF) & ~0x1FF
    rdata_rva = 0x1000

    export_dir = struct.pack(
        "<IIIIIIIIIII", 0, export_timestamp, 0, 0, 1, 0, 0, 0, 0, 0, 0
    )
    cursor = len(export_dir)

    entries = ((2 if repro_entry else 1) + extra_debug_entries) if include_debug else 0
    debug_array_rva = rdata_rva + cursor
    debug_array_size = entries * 28
    cursor += debug_array_size

    codeview = (
        codeview_signature
        + codeview_guid
        + struct.pack("<I", codeview_age)
        + pdb_path
        + b"\x00"
    )
    codeview_rva = rdata_rva + cursor
    if include_debug:
        cursor += len(codeview)

    repro_blob = struct.pack("<I", 4) + b"\xde\xad\xbe\xef"
    repro_rva = rdata_rva + cursor
    if include_debug and repro_entry:
        cursor += len(repro_blob)

    rdata_len = cursor
    text_raw = (rdata_raw + rdata_len + 0x1FF) & ~0x1FF
    text_rva = (rdata_rva + rdata_len + 0xFFF) & ~0xFFF

    if debug_in_code_section:
        # Aim the CodeView record into `.text` while leaving the record itself
        # where it is, so only the declared range moves into executable bytes.
        codeview_pointer = text_raw
        codeview_address = text_rva
    else:
        codeview_pointer = rdata_raw + (codeview_rva - rdata_rva)
        codeview_address = codeview_rva

    def entry(index: int) -> bytes:
        if index == 0:
            return struct.pack(
                "<IIHHIIII",
                0,
                debug_timestamp,
                0,
                0,
                2,
                len(codeview) if codeview_size_of_data is None else codeview_size_of_data,
                codeview_address
                if codeview_address_override is None
                else codeview_address_override,
                codeview_pointer,
            )
        return struct.pack(
            "<IIHHIIII",
            0,
            debug_timestamp,
            0,
            0,
            16,
            len(repro_blob),
            repro_rva,
            rdata_raw + (repro_rva - rdata_rva),
        )

    rdata = export_dir + b"".join(entry(i) for i in range(entries))
    if include_debug:
        rdata += codeview
        if repro_entry:
            rdata += repro_blob

    coff = struct.pack(
        "<HHIIIHH", _MACHINE_AMD64, 2, timestamp, 0, 0, optional_size, 0x2022
    )

    optional = bytearray(optional_size)
    struct.pack_into("<H", optional, 0, optional_magic)
    struct.pack_into("<I", optional, 16, text_rva)
    struct.pack_into("<I", optional, 32, 0x1000)
    struct.pack_into("<I", optional, 36, 0x200)
    struct.pack_into("<I", optional, 56, text_rva + len(body))
    struct.pack_into("<I", optional, 60, rdata_raw)
    struct.pack_into("<I", optional, 64, checksum)
    struct.pack_into("<I", optional, 108, 16)
    struct.pack_into("<II", optional, 112, rdata_rva, len(export_dir))
    if include_debug:
        struct.pack_into(
            "<II", optional, 112 + 6 * 8, debug_array_rva, debug_array_size
        )

    sections = (
        b".rdata".ljust(8, b"\x00")
        + struct.pack("<IIII", len(rdata), rdata_rva, len(rdata), rdata_raw)
        + struct.pack("<IIHHI", 0, 0, 0, 0, 0x40000040)
        + b".text".ljust(8, b"\x00")
        + struct.pack("<IIII", len(body), text_rva, len(body), text_raw)
        + struct.pack("<IIHHI", 0, 0, 0, 0, 0x60000020)
    )

    head = dos + signature + coff + bytes(optional) + sections
    image = head + b"\x00" * (rdata_raw - len(head)) + rdata
    image += b"\x00" * (text_raw - len(image)) + body
    return image
