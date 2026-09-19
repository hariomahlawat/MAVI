"""Windows native metadata must be proved benign, never assumed benign.

The empirical finding from the C2 host was that two MMCV builds from the same
source path, venv, commit, flags and toolchain produce objects whose raw hashes
all differ. Hand inspection of two of the 136 showed the difference was a COFF
timestamp. These tests pin the distinction that matters: a difference inside a
documented metadata field reduces to equality, and *everything else* -- a
changed instruction byte, a header word nobody has explained, a binary that
will not parse -- does not.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

import pytest

import native_binary_fixtures as fixtures


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "vision" / "native_binary_metadata.py"


def _load():
    spec = importlib.util.spec_from_file_location("native_binary_metadata", TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError("analyser_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


def _classify(left: bytes, right: bytes) -> str:
    return str(MODULE.compare_native_payloads(left, right)["classification"])


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def test_each_supported_format_is_detected() -> None:
    assert MODULE.detect_native_format(fixtures.coff_object()) == "coff-object"
    assert MODULE.detect_native_format(fixtures.bigobj_object()) == "bigobj-object"
    assert MODULE.detect_native_format(fixtures.pe_image()) == "pe-image"


def test_a_payload_that_is_no_known_format_is_not_guessed() -> None:
    assert MODULE.detect_native_format(b"not a binary at all") is None
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(b"not a binary at all")
    assert excinfo.value.code == "native_format_unrecognised"


def test_bigobj_is_detected_before_coff() -> None:
    # A BIGOBJ header begins with machine word 0x0000, which is not a known
    # machine, so ordering is what keeps it from falling through to the COFF
    # branch and being parsed with the wrong offsets.
    data = fixtures.bigobj_object()
    assert data[:4] == b"\x00\x00\xff\xff"
    assert MODULE.detect_native_format(data) == "bigobj-object"


# ---------------------------------------------------------------------------
# Standard COFF objects
# ---------------------------------------------------------------------------


def test_coff_objects_differing_only_in_timestamp_reduce_to_equality() -> None:
    left = fixtures.coff_object(timestamp=0x68A00001)
    right = fixtures.coff_object(timestamp=0x68A0FFFF)
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "metadata-normalized-identical"
    assert [field["name"] for field in result["normalizedFields"]] == [
        "coff.TimeDateStamp"
    ]
    assert result["residualDifferenceCount"] == 0


def test_the_reported_timestamp_values_are_decoded() -> None:
    left = fixtures.coff_object(timestamp=0x11111111)
    right = fixtures.coff_object(timestamp=0x22222222)
    field = MODULE.compare_native_payloads(left, right)["normalizedFields"][0]

    assert field["left"]["hex"] == "0x11111111"
    assert field["right"]["hex"] == "0x22222222"


def test_one_changed_instruction_byte_is_not_excused() -> None:
    left = fixtures.coff_object()
    right = fixtures.coff_object(body=b"\x90" * 511 + b"\xcc")
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "unexplained-native-difference"
    assert result["residualDifferenceCount"] == 1
    assert result["residualDifferences"][0]["category"] == "unexplained"


def test_a_changed_symbol_name_is_not_excused() -> None:
    left = fixtures.coff_object(symbols=3)
    right = bytearray(fixtures.coff_object(symbols=3))
    right[-20] ^= 0xFF
    assert _classify(left, bytes(right)) == "unexplained-native-difference"


def test_coff_normalization_excuses_only_four_bytes() -> None:
    layout = MODULE.describe_native_layout(fixtures.coff_object())
    assert MODULE.normalized_byte_count(layout) == 4


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (fixtures.coff_object()[:12], "native_format_unrecognised"),
        (fixtures.coff_object(machine=0x1234), "native_format_unrecognised"),
        (
            fixtures.coff_object(optional_header_size=224),
            "coff_object_has_optional_header",
        ),
    ],
)
def test_malformed_coff_is_refused_rather_than_normalized(
    payload: bytes, code: str
) -> None:
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(payload)
    assert excinfo.value.code == code


def test_a_coff_symbol_table_pointing_past_the_file_is_refused() -> None:
    data = bytearray(fixtures.coff_object())
    struct.pack_into("<I", data, 8, len(data) + 4096)
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(bytes(data))
    assert excinfo.value.code == "coff_symbol_table_out_of_range"


def test_an_unparsable_native_payload_is_refused_not_passed() -> None:
    left = fixtures.coff_object(timestamp=1)
    right = bytearray(fixtures.coff_object(timestamp=2))
    struct.pack_into("<I", right, 8, len(right) + 4096)
    result = MODULE.compare_native_payloads(left, bytes(right))

    assert result["classification"] == "unparsable-native-format"
    assert result["reason"] == "coff_symbol_table_out_of_range"
    assert result["classification"] not in MODULE.ACCEPTABLE_CLASSIFICATIONS


# ---------------------------------------------------------------------------
# BIGOBJ objects
# ---------------------------------------------------------------------------


def test_bigobj_objects_differing_only_in_timestamp_reduce_to_equality() -> None:
    left = fixtures.bigobj_object(timestamp=0x68A00001)
    right = fixtures.bigobj_object(timestamp=0x68A0FFFF)
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "metadata-normalized-identical"
    assert [field["name"] for field in result["normalizedFields"]] == [
        "bigobj.TimeDateStamp"
    ]


def test_bigobj_metadata_size_is_reported_not_normalized() -> None:
    """Offset 36 is `MetaDataSize`, not a second timestamp.

    The host investigation normalised bytes 36:40 alongside the timestamp and
    reached byte equality. That field is CLR metadata in the documented
    `ANON_OBJECT_HEADER_BIGOBJ` layout, so zeroing it would be excusing a
    difference nobody has explained. It is decoded and reported instead, and it
    blocks equivalence until someone establishes what it is.
    """
    left = fixtures.bigobj_object(metadata_size=0)
    right = fixtures.bigobj_object(metadata_size=0x68A0FFFF)
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "undocumented-header-field-divergence"
    assert result["classification"] not in MODULE.ACCEPTABLE_CLASSIFICATIONS
    residual = result["residualDifferences"][0]
    assert residual["field"] == "bigobj.MetaDataSize"
    assert residual["left"]["uint32"] == 0
    assert residual["right"]["hex"] == "0x68a0ffff"


def test_bigobj_metadata_offset_is_also_reported_not_normalized() -> None:
    left = fixtures.bigobj_object(metadata_offset=0)
    right = fixtures.bigobj_object(metadata_offset=9)
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "undocumented-header-field-divergence"
    assert result["residualDifferences"][0]["field"] == "bigobj.MetaDataOffset"


def test_bigobj_body_divergence_is_not_excused() -> None:
    left = fixtures.bigobj_object()
    right = fixtures.bigobj_object(body=b"\x90" * 511 + b"\xcc")
    assert _classify(left, right) == "unexplained-native-difference"


def test_bigobj_normalization_excuses_only_four_bytes() -> None:
    layout = MODULE.describe_native_layout(fixtures.bigobj_object())
    assert MODULE.normalized_byte_count(layout) == 4


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (fixtures.bigobj_object(version=1), "bigobj_version_unsupported"),
        (fixtures.bigobj_object(machine=0x1234), "bigobj_machine_unknown"),
        (fixtures.bigobj_object(class_id=bytes(16)), "bigobj_class_id_invalid"),
        (fixtures.bigobj_object()[:40], "native_format_unrecognised"),
    ],
)
def test_malformed_bigobj_is_refused_rather_than_normalized(
    payload: bytes, code: str
) -> None:
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(payload)
    assert excinfo.value.code == code


# ---------------------------------------------------------------------------
# PE images
# ---------------------------------------------------------------------------


def test_pe_images_differing_only_in_link_metadata_reduce_to_equality() -> None:
    left = fixtures.pe_image(
        timestamp=0x68A00001, checksum=1, codeview_guid=bytes(range(16)), codeview_age=1
    )
    right = fixtures.pe_image(
        timestamp=0x68A0FFFF,
        checksum=2,
        codeview_guid=bytes(range(16, 32)),
        codeview_age=2,
    )
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "metadata-normalized-identical"
    assert set(field["name"] for field in result["normalizedFields"]) == {
        "pe.coff.TimeDateStamp",
        "pe.optional.CheckSum",
        "pe.export.TimeDateStamp",
        "pe.debug[0].TimeDateStamp",
        "pe.debug[0].codeview.Guid",
        "pe.debug[0].codeview.Age",
    }


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"timestamp": 0x68A0FFFF}, "pe.coff.TimeDateStamp"),
        ({"checksum": 0x99}, "pe.optional.CheckSum"),
        ({"debug_timestamp": 0x77}, "pe.debug[0].TimeDateStamp"),
        ({"export_timestamp": 0x55}, "pe.export.TimeDateStamp"),
        ({"codeview_guid": bytes(range(16, 32))}, "pe.debug[0].codeview.Guid"),
        ({"codeview_age": 7}, "pe.debug[0].codeview.Age"),
    ],
)
def test_each_pe_metadata_field_is_named_individually(
    kwargs: dict[str, object], field: str
) -> None:
    base = {"timestamp": 0x68A00001, "debug_timestamp": 0x11, "export_timestamp": 0x22}
    left = fixtures.pe_image(**base)
    right = fixtures.pe_image(**{**base, **kwargs})
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "metadata-normalized-identical"
    assert [item["name"] for item in result["normalizedFields"]] == [field]


def test_a_changed_pe_code_byte_is_not_excused() -> None:
    left = fixtures.pe_image()
    right = fixtures.pe_image(body=b"\x90" * 1023 + b"\xcc")
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "unexplained-native-difference"
    assert result["residualDifferences"][0]["category"] == "unexplained"


def test_a_differing_pdb_path_is_named_as_an_embedded_build_path() -> None:
    """Two builds from different source roots are not reproducible.

    The PDB path is deliberately *not* normalised: it is the evidence that the
    build is not relocatable, and normalising it would hide exactly the finding
    that the A-versus-B comparison exists to surface.
    """
    left = fixtures.pe_image(pdb_path=rb"C:\mavi-c2\mmcv-src-a\build\_ext.pdb")
    right = fixtures.pe_image(pdb_path=rb"C:\mavi-c2\mmcv-src-b\build\_ext.pdb")
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "embedded-build-path-divergence"
    assert result["classification"] not in MODULE.ACCEPTABLE_CLASSIFICATIONS
    assert result["residualDifferences"][0]["category"] == "embedded-build-path"


def test_a_repro_debug_entry_is_recorded_when_present() -> None:
    plain = MODULE.describe_native_layout(fixtures.pe_image())
    repro = MODULE.describe_native_layout(fixtures.pe_image(repro_entry=True))

    assert plain.detail["reproDebugEntry"] is False
    assert repro.detail["reproDebugEntry"] is True


def test_a_pe_without_a_debug_directory_still_normalizes_its_header() -> None:
    left = fixtures.pe_image(include_debug=False, timestamp=1)
    right = fixtures.pe_image(include_debug=False, timestamp=2)
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "metadata-normalized-identical"
    assert [item["name"] for item in result["normalizedFields"]] == [
        "pe.coff.TimeDateStamp",
        "pe.export.TimeDateStamp",
    ]


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"signature": b"PX\x00\x00"}, "pe_signature_invalid"),
        ({"optional_magic": 0x107}, "pe_optional_magic_unknown"),
        ({"codeview_signature": b"NB10"}, "pe_codeview_signature_unknown"),
    ],
)
def test_malformed_pe_is_refused_rather_than_normalized(
    kwargs: dict[str, object], code: str
) -> None:
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(fixtures.pe_image(**kwargs))
    assert excinfo.value.code == code


def test_a_truncated_pe_is_refused() -> None:
    with pytest.raises(MODULE.NativeFormatError):
        MODULE.describe_native_layout(fixtures.pe_image()[:32])


def test_a_debug_directory_outside_every_section_is_refused() -> None:
    data = bytearray(fixtures.pe_image())
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe + 4 + 20
    struct.pack_into("<I", data, optional + 112 + 6 * 8, 0x7FFF0000)
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(bytes(data))
    assert excinfo.value.code == "pe_debug_directory_unmapped"


# ---------------------------------------------------------------------------
# Cross-cutting refusals
# ---------------------------------------------------------------------------


def test_two_different_formats_are_never_compared_field_wise() -> None:
    result = MODULE.compare_native_payloads(
        fixtures.coff_object(), fixtures.bigobj_object()
    )
    assert result["classification"] == "native-format-mismatch"
    assert result["leftFormat"] == "coff-object"
    assert result["rightFormat"] == "bigobj-object"


def test_payloads_of_different_length_cannot_be_proved_equivalent() -> None:
    result = MODULE.compare_native_payloads(
        fixtures.coff_object(body=b"\x90" * 512),
        fixtures.coff_object(body=b"\x90" * 640),
    )
    assert result["classification"] == "native-size-mismatch"
    assert result["sizeBytes"] == {
        "left": len(fixtures.coff_object(body=b"\x90" * 512)),
        "right": len(fixtures.coff_object(body=b"\x90" * 640)),
    }


def test_identical_payloads_are_reported_as_identical() -> None:
    data = fixtures.coff_object()
    result = MODULE.compare_native_payloads(data, data)
    assert result["classification"] == "identical"
    assert result["byteIdentical"] is True


def test_a_truncated_residual_sample_never_yields_a_named_cause() -> None:
    """A bounded sample cannot prove what the bytes it did not look at are.

    Without this rule, a binary whose first thirty-two differing bytes happen
    to fall inside a path string would be classified `embedded-build-path` no
    matter what the remaining megabyte held.
    """
    path = rb"C:\mavi-c2\mmcv-src-a\a-very-long-source-directory-name\file.cpp"
    left = fixtures.coff_object(body=path + b"\x00" + b"\x90" * 400)
    right = fixtures.coff_object(
        body=path.replace(b"src-a", b"src-b") + b"\x00" + b"\xcc" * 400
    )
    result = MODULE.compare_native_payloads(left, right, residual_limit=1)

    assert result["residualSampleTruncated"] is True
    assert result["classification"] == "unexplained-native-difference"


def test_the_residual_count_is_the_whole_set_not_the_sample() -> None:
    left = fixtures.coff_object(body=b"\x90" * 512)
    right = fixtures.coff_object(body=b"\xcc" * 512)
    result = MODULE.compare_native_payloads(left, right, residual_limit=4)

    assert len(result["residualDifferences"]) == 4
    assert result["residualDifferenceCount"] == 512


def test_only_identical_and_normalized_are_acceptable() -> None:
    assert MODULE.ACCEPTABLE_CLASSIFICATIONS == frozenset(
        {"identical", "metadata-normalized-identical"}
    )


# ---------------------------------------------------------------------------
# Embedded build paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        b"See https://github.com/open-mmlab/mmcv for details",
        b"Paper: https://arxiv.org/abs/1904.07850",
        b"http://www.apache.org/licenses/LICENSE-2.0",
        b"git+ssh://git@github.com/open-mmlab/mmcv.git",
        b"Reference implementation at https://download.pytorch.org/whl/cu124",
        b"ftp://mirror.example.org/usr/share/doc/readme",
    ],
)
def test_urls_are_not_reported_as_build_paths(payload: bytes) -> None:
    assert MODULE.embedded_build_paths(payload) == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"\x00C:\\mavi-c2\\mmcv-src-a\\mmcv\\ops\\nms.cpp\x00", "C:\\mavi-c2\\mmcv-src-a\\mmcv\\ops\\nms.cpp"),
        (b"\x00D:/a/MAVI/src/vision/build/temp.win-amd64\x00", "D:/a/MAVI/src/vision/build/temp.win-amd64"),
        (b'"/home/runner/work/MAVI/src"', "/home/runner/work/MAVI/src"),
        (b"\x00/usr/lib/x86_64-linux-gnu/libstdc++.so.6\x00", "/usr/lib/x86_64-linux-gnu/libstdc++.so.6"),
    ],
)
def test_real_build_paths_are_still_reported(payload: bytes, expected: str) -> None:
    assert MODULE.embedded_build_paths(payload) == [expected]


def test_a_url_next_to_a_real_path_does_not_suppress_the_path() -> None:
    payload = b"https://github.com/open-mmlab/mmcv\x00C:\\mavi-c2\\build-a\\_ext.pyd\x00"
    assert MODULE.embedded_build_paths(payload) == ["C:\\mavi-c2\\build-a\\_ext.pyd"]


def test_a_drive_letter_inside_a_longer_word_is_not_a_path() -> None:
    # `https:` ends in `s`, which is what made the first detector report every
    # documentation URL in MMCV as an absolute build path.
    assert MODULE.embedded_build_paths(b"xyzs:/something/that/is/long") == []


def test_paths_are_deduplicated_and_sorted() -> None:
    payload = (
        b"\x00C:\\b\\second\\file.cpp\x00C:\\a\\first\\file.cpp\x00C:\\b\\second\\file.cpp\x00"
    )
    assert MODULE.embedded_build_paths(payload) == [
        "C:\\a\\first\\file.cpp",
        "C:\\b\\second\\file.cpp",
    ]


def test_an_ipv6_url_authority_does_not_smuggle_a_rooted_path() -> None:
    """The case the lexical guards cannot reach.

    An IPv6 literal authority ends in `]`, which is neither a word character
    nor a path character, so `/usr/...` after it passes the lookbehind. The
    URL-overlap drop is what catches it, and this is the test that makes that
    check earn its place rather than being redundant cover.
    """
    assert MODULE.embedded_build_paths(b"http://[::1]/usr/share/doc/readme") == []
    assert (
        MODULE.embedded_build_paths(b"https://[2001:db8::1]/home/runner/work") == []
    )


def test_a_file_url_still_reports_the_local_path_it_wraps() -> None:
    """Excluding URLs must not become a way to hide an absolute build path."""
    assert MODULE.embedded_build_paths(b"file:///C:/mavi-c2/build-a/_ext.pdb") == [
        "C:/mavi-c2/build-a/_ext.pdb"
    ]


# ---------------------------------------------------------------------------
# Declared ranges must be provably metadata, not merely pointed at by metadata
#
# Every offset the PE parser reads comes out of the file. Left unconstrained,
# a declared range nominates arbitrary bytes -- including `.text` -- as
# normalisable, and the equivalence proof becomes circular: whoever produced
# the file chooses which bytes the comparison ignores.
# ---------------------------------------------------------------------------


def test_a_declared_range_inside_a_code_section_is_refused() -> None:
    """The headline fail-open: 20 bytes of `.text` excused per debug entry.

    Two checks can catch this -- the mapped/raw consistency check usually
    fires first, and the section rule is the backstop for a record crafted to
    satisfy it. Either refusal is correct; what must never happen is a layout.
    """
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(fixtures.pe_image(debug_in_code_section=True))
    assert excinfo.value.code in {
        "pe_normalized_field_in_code_section",
        "pe_codeview_record_unmapped",
        "pe_codeview_signature_unknown",
    }


def test_the_section_rule_catches_a_range_the_other_checks_admit() -> None:
    """The backstop, exercised on its own: a field aimed into `.text`."""
    import struct as _struct

    data = bytearray(fixtures.pe_image())
    pe = _struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe + 4 + 20
    # Point the export directory at the code section; its TimeDateStamp field
    # is then declared inside executable bytes.
    text_rva = _struct.unpack_from("<I", data, optional + 16)[0]
    _struct.pack_into("<I", data, optional + 112, text_rva)
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(bytes(data))
    assert excinfo.value.code == "pe_normalized_field_in_code_section"


def test_a_code_section_payload_cannot_be_normalized_away() -> None:
    """End to end: the same two images the layout refuses are never equivalent."""
    left = fixtures.pe_image(debug_in_code_section=True, body=b"\x90" * 1024)
    right = fixtures.pe_image(
        debug_in_code_section=True, body=b"\xcc" * 20 + b"\x90" * 1004
    )
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "unparsable-native-format"
    assert result["classification"] not in MODULE.ACCEPTABLE_CLASSIFICATIONS


def test_size_of_data_is_read_from_the_documented_offset() -> None:
    """`SizeOfData` is at entry offset 16, not 20 -- 20 is `AddressOfRawData`.

    Reading it from 20 made the `size_of_data < 24` guard test a large RVA,
    which always passes, so an entry describing no CodeView record at all was
    accepted and its pointer honoured.
    """
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(fixtures.pe_image(codeview_size_of_data=0))
    assert excinfo.value.code == "pe_codeview_record_too_small"


def test_a_codeview_record_whose_two_views_disagree_is_refused() -> None:
    """`AddressOfRawData` must map to `PointerToRawData` through the sections.

    A record reachable through only one of them is not the record the loader
    sees, and the mismatch is how two images can be made to declare different
    ranges from the same apparent content.
    """
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(
            fixtures.pe_image(codeview_address_override=0x1)
        )
    assert excinfo.value.code == "pe_codeview_record_unmapped"


def test_an_implausible_debug_entry_count_is_refused() -> None:
    """Entries are how a crafted image buys normalisable bytes, 20 at a time."""
    with pytest.raises(MODULE.NativeFormatError) as excinfo:
        MODULE.describe_native_layout(fixtures.pe_image(extra_debug_entries=32))
    assert excinfo.value.code == "pe_debug_entry_count_implausible"


def test_two_payloads_declaring_different_ranges_are_refused() -> None:
    """Masking each file with its own declaration compares two remainders."""
    left = fixtures.pe_image(timestamp=1)
    right = fixtures.pe_image(timestamp=1, include_debug=False)
    result = MODULE.compare_native_payloads(left, right)

    assert result["classification"] == "normalized-field-disagreement"
    assert result["classification"] not in MODULE.ACCEPTABLE_CLASSIFICATIONS
    assert result["fieldsOnlyInLeft"]


def test_the_normalized_byte_budget_is_small_for_an_honest_image() -> None:
    layout = MODULE.describe_native_layout(fixtures.pe_image())
    assert MODULE.normalized_byte_count(layout) <= 64
    assert MODULE.MAX_NORMALIZED_BYTES <= 256


def test_overlap_detection_handles_nested_spans() -> None:
    """A nested span must still be found once the scan became a binary search."""
    prepared = MODULE._prepare_spans([(0, 100), (10, 20), (200, 210)])
    assert MODULE._overlaps((15, 16), prepared) is True
    assert MODULE._overlaps((120, 130), prepared) is False
    assert MODULE._overlaps((99, 205), prepared) is True
    assert MODULE._overlaps((0, 0), MODULE._prepare_spans([])) is False


@pytest.mark.parametrize(
    "payload",
    [
        b"#!/usr/bin/env python\n",
        b"#!/bin/sh\n",
    ],
)
def test_a_shebang_interpreter_is_not_a_build_path(payload: bytes) -> None:
    """Every wheel's console scripts carry one; none of them is a build path."""
    assert MODULE.embedded_build_paths(payload) == []


@pytest.mark.parametrize(
    "prose",
    [
        b"See /usr/share/doc/python3/README for details",
        b"Defaults to /tmp/cache unless overridden",
        b"it searches /usr/lib and /usr/lib64 in order",
    ],
)
def test_a_directory_mentioned_in_prose_is_not_a_build_path(prose: bytes) -> None:
    assert MODULE.embedded_build_paths(prose) == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"\x00/github/workspace/mmcv/src/ext.cpp\x00", "/github/workspace/mmcv/src/ext.cpp"),
        (b"\x00/builds/group/proj/mmcv/ext.cpp\x00", "/builds/group/proj/mmcv/ext.cpp"),
        (b"\x00/workspace/mmcv/ops/nms.cu\x00", "/workspace/mmcv/ops/nms.cu"),
        (b"\x00/opt/conda/lib/python3.12/site-packages/torch/include\x00", "/opt/conda/lib/python3.12/site-packages/torch/include"),
        (b"\x00\\\\buildhost\\share\\mmcv\\src\\ext.cpp\x00", "\\\\buildhost\\share\\mmcv\\src\\ext.cpp"),
    ],
)
def test_ci_and_unc_build_roots_are_detected(payload: bytes, expected: str) -> None:
    """The roots real builds run under, which the first allow-list missed."""
    assert MODULE.embedded_build_paths(payload) == [expected]
