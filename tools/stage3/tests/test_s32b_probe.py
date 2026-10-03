"""S3.2b-1 T7: the approved media binaries (``media_tools``) and the media probe (``probe_media``)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import artefacts as a
import media_tools
import probe_media
import s32b_fixtures as f

VECTOR = a.ROOT / "contracts" / "test-vectors" / "phase1-mp4-container-policy-v1.json"


def refused(code: str, call) -> None:
    with pytest.raises(a.S32Error) as raised:
        call()
    assert str(raised.value).startswith(code), str(raised.value)


# ---------------------------------------------------------------- parity vector (no media needed)


def _vector_cases():
    return json.loads(VECTOR.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _vector_cases(), ids=lambda case: case["name"])
def test_container_policy_port_matches_the_shared_vector(case):
    assert probe_media.container_supported(case["formatName"], case["majorBrand"]) is case["supported"]


def test_the_vector_pins_the_order_and_white_space_cases():
    cases = {case["name"]: case for case in _vector_cases()}
    assert cases["brand-qt-nul"]["supported"] is False and cases["brand-qt-space-nul"]["supported"] is True
    assert cases["brand-x1c-padded-qt"]["supported"] is True  # \x1c is not .NET white space
    assert "\x1c".strip() == ""  # ...but Python's str.strip would remove it: the port must not use it


def test_dotnet_white_space_is_the_char_is_white_space_set():
    import unicodedata

    expected = {chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) in ("Zs", "Zl", "Zp")}
    expected |= set("\t\n\x0b\x0c\r\x85")
    assert probe_media.DOTNET_WHITESPACE == expected


# ---------------------------------------------------------------- reader rules (no media needed)


def _ffprobe(stream=None, fmt=None, streams=None):
    base_stream = {"codec_type": "video", "codec_name": "h264", "width": 64, "height": 48,
                   "avg_frame_rate": "20/2", "r_frame_rate": "10/1", "duration": "1.000000", "nb_frames": "10"}
    base_format = {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "1.0005", "tags": {"major_brand": "isom"}}
    return {"streams": streams if streams is not None else [{**base_stream, **(stream or {})}],
            "format": {**base_format, **(fmt or {})}}


def test_reader_rules_frame_rate_duration_and_counts():
    described = probe_media.describe(_ffprobe())
    assert described["video"]["frameRateNumerator"] == 10 and described["video"]["frameRateDenominator"] == 1
    assert described["format"]["durationMs"] == 1001  # 1000.5 rounds half away from zero
    assert described["video"]["frameCount"] == 10 and described["video"]["frameCountSource"] == "container"
    assert described["maviImport"] == {"policy": "phase1-mp4-container-v1", "containerSupported": True,
                                       "metadataValid": True}


@pytest.mark.parametrize("value, expected", [("0.0004", None), ("0.0005", 1), ("2.4994", 2499), ("-1", None),
                                             (" 1.5 ", 1500), ("1e1", 10000), ("abc", None), ("nan", None)])
def test_duration_is_the_readers_decimal_rounding(value, expected):
    assert probe_media._duration_ms(value) == expected


@pytest.mark.parametrize("value, expected", [("30000/1001", (30000, 1001)), ("0/0", None), ("+25/1", None),
                                             ("25", None), ("25/1/1", None), ("2147483648/1", None), ("50/2", (25, 1))])
def test_frame_rate_is_the_readers_rational(value, expected):
    assert probe_media._rational(value) == expected


def test_a_duration_the_reader_cannot_convert_fails_the_read_without_fallback():
    # checked((long)...) throws in the reader: no fallback to the stream duration.
    described = probe_media.describe(_ffprobe(fmt={"duration": "9300000000000000"}))
    assert described["maviImport"]["metadataValid"] is False and described["video"]["durationMs"] is None
    assert probe_media._duration_ms("\u0661.5") is None  # non-ASCII digits: .NET invariant parsing refuses


def test_a_binary_changed_after_verification_is_refused(tmp_path):
    binary = tmp_path / "tool"
    binary.write_bytes(b"verified bytes")
    tool = media_tools.Tool(path=binary, version="v", sha256=a.sha256_hex(b"verified bytes"))
    media_tools.require_unchanged(tool)
    binary.write_bytes(b"swapped bytes")
    refused("media_tools_invalid:changed", lambda: media_tools.require_unchanged(tool))


def test_frame_rate_falls_back_to_r_frame_rate_and_duration_to_the_stream():
    described = probe_media.describe(_ffprobe(stream={"avg_frame_rate": "0/0"}, fmt={"duration": "N/A"}))
    assert (described["video"]["frameRateNumerator"], described["video"]["frameRateDenominator"]) == (10, 1)
    assert described["format"]["durationMs"] is None and described["video"]["durationMs"] == 1000
    assert described["maviImport"]["metadataValid"] is True


@pytest.mark.parametrize("stream", [{"width": 0}, {"codec_name": "  "}, {"avg_frame_rate": "0/0", "r_frame_rate": "x"},
                                    {"height": "48"}])
def test_metadata_the_reader_refuses_is_not_valid(stream):
    described = probe_media.describe(_ffprobe(stream=stream))
    assert described["maviImport"]["metadataValid"] is False


def test_brand_is_recorded_raw_and_no_format_is_invalid_media():
    described = probe_media.describe(_ffprobe(fmt={"tags": {"major_brand": "qt  "}}))
    assert described["format"]["majorBrand"] == "qt  " and described["maviImport"]["containerSupported"] is False
    refused("probe_invalid_media", lambda: probe_media.describe({"streams": []}))


# ---------------------------------------------------------------- media pack binding


def test_the_pack_loads_and_records_only_version_and_sha(media_pack):
    tool = media_tools.load(media_pack, "ffprobe")
    assert set(tool.identity) == {"version", "sha256"}
    assert tool.identity["sha256"] == a.sha256_hex(f.tool_path(media_pack, "ffprobe").read_bytes())


@pytest.mark.parametrize("mutation, code", [
    (lambda m: m.update(runtimeId="linux-arm64"), "media_tools_invalid:runtime"),
    (lambda m: m.update(version="0.0.0-not-this-build"), "media_tools_invalid:version_mismatch"),
    (lambda m: m.update(schemaVersion="2.0"), "media_tools_invalid:schema"),
    (lambda m: [e.update(sha256="0" * 64) for e in m["artifacts"]], "media_tools_invalid:sha256_mismatch"),
    (lambda m: [e.update(sha256=e["sha256"].upper()) for e in m["artifacts"]], "media_tools_invalid:sha256_invalid"),
    (lambda m: m.update(artifacts=[e for e in m["artifacts"] if "ffprobe" not in e["fileName"].lower()]),
     "media_tools_invalid:not_listed"),
])
def test_a_wrong_manifest_is_refused(media_pack, tmp_path, mutation, code):
    pack = f.clone_pack(media_pack, tmp_path / "pack")
    manifest = f.manifest_of(pack)
    mutation(manifest)
    f.rewrite_manifest(pack, manifest)
    refused(code, lambda: media_tools.load(pack, "ffprobe"))


def test_a_listed_but_absent_binary_is_never_found_on_path(media_pack, tmp_path, monkeypatch):
    pack = f.clone_pack(media_pack, tmp_path / "pack")
    binary = f.tool_path(pack, "ffprobe")
    binary.unlink()
    # Even with a usable ffprobe first on PATH, the pack is the only source.
    monkeypatch.setenv("PATH", str(f.tool_path(media_pack, "ffprobe").parent) + os.pathsep + os.environ.get("PATH", ""))
    refused("media_tools_invalid:missing", lambda: media_tools.load(pack, "ffprobe"))
    refused("media_tools_invalid:manifest", lambda: media_tools.load(tmp_path / "empty", "ffprobe"))


# ---------------------------------------------------------------- probing real media


def _probe(media_pack, tmp_path, media, name):
    path = tmp_path / name
    path.write_bytes(media[name])
    return probe_media.probe(media_tools.load(media_pack, "ffprobe"), path)


def test_a_supported_mp4_probe_is_schema_valid_and_deterministic(media_pack, media, tmp_path):
    first = _probe(media_pack, tmp_path, media, "h264.mp4")
    second = probe_media.probe(media_tools.load(media_pack, "ffprobe"), tmp_path / "h264.mp4")
    assert a.canonical_json(first) == a.canonical_json(second)
    a.validate(first, "vehicle-subclass-media-probe-v1", "unexpected")
    assert first["sourceSha256"] == a.sha256_hex(media["h264.mp4"]) and first["sourceSizeBytes"] == len(media["h264.mp4"])
    assert first["videoStreamCount"] == 1 and first["video"]["codec"] == "h264"
    assert first["maviImport"]["containerSupported"] and first["maviImport"]["metadataValid"]
    assert str(tmp_path) not in a.canonical_json(first).decode("utf-8") and "h264.mp4" not in a.canonical_json(first).decode()


@pytest.mark.parametrize("name, brand_prefix", [("quicktime.mov", "qt"), ("brand3gp.3gp", "3gp"), ("brand3g2.3g2", "3g2")])
def test_quicktime_3gp_and_3g2_brands_are_not_supported(media_pack, media, tmp_path, name, brand_prefix):
    record = _probe(media_pack, tmp_path, media, name)
    assert record["format"]["majorBrand"].startswith(brand_prefix)
    assert "mp4" in record["format"]["formatName"].split(",")
    assert record["maviImport"]["containerSupported"] is False and record["maviImport"]["metadataValid"] is True


def test_a_non_mp4_container_is_not_supported(media_pack, media, tmp_path):
    record = _probe(media_pack, tmp_path, media, "h264.mkv")
    assert record["format"]["majorBrand"] is None and record["maviImport"]["containerSupported"] is False


def test_no_video_stream_and_two_video_streams_are_valid_probes(media_pack, media, tmp_path):
    audio = _probe(media_pack, tmp_path, media, "audio-only.mp4")
    assert audio["videoStreamCount"] == 0 and audio["video"] is None and audio["maviImport"]["metadataValid"] is False
    two = _probe(media_pack, tmp_path, media, "two-video.mp4")
    assert two["videoStreamCount"] == 2 and two["video"]["width"] == 64  # the first stream


def test_invalid_bytes_and_unreadable_input_are_refused(media_pack, media, tmp_path):
    refused("probe_failed", lambda: _probe(media_pack, tmp_path, media, "invalid.mp4"))
    refused("probe_input_unreadable", lambda: probe_media.probe(media_tools.load(media_pack, "ffprobe"), tmp_path / "no"))


def test_cli_writes_once_and_refuses_an_existing_output(media_pack, media, tmp_path, capsys):
    source = tmp_path / "in.mp4"
    source.write_bytes(media["h264.mp4"])
    out = tmp_path / "probe.json"
    args = ["--media-tools", str(media_pack), "--input", str(source), "--out", str(out)]
    assert probe_media.main(args) == 0
    assert a.sha256_hex(out.read_bytes()) == capsys.readouterr().out.strip()
    assert probe_media.main(args) == 2 and "refused output_exists" in capsys.readouterr().err
