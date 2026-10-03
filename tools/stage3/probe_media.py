#!/usr/bin/env python3
"""Media probe (Stage 3, S3.2 plan T7): ``vehicle-subclass-media-probe-v1``.

Runs exactly the platform reader's ``ffprobe -v error -print_format json -show_streams
-show_format <input>`` (``FfprobeVideoMetadataReader``) with the verified pack's ffprobe,
and applies the reader's selection rules: the first video stream; frame rate from
``avg_frame_rate`` then ``r_frame_rate`` (reduced by their GCD); duration from the format
then the stream, as decimal seconds × 1000 rounded half away from zero. ``maviImport``
reports what MAVI's importer would decide: ``containerSupported`` is an exact port of
``PhaseOneMp4ContainerPolicy.IsSupported`` (pinned by
``contracts/test-vectors/phase1-mp4-container-policy-v1.json``) and ``metadataValid`` is the
reader's acceptance. A file with no or several video streams still has a valid probe.

Usage: ``probe_media.py --media-tools <dir> --input <file> --out <file>``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artefacts as a  # noqa: E402
import media_tools  # noqa: E402

SCHEMA = "vehicle-subclass-media-probe-v1"
POLICY = "phase1-mp4-container-v1"
FFPROBE_ARGS = ("-v", "error", "-print_format", "json", "-show_streams", "-show_format")
PROBE_TIMEOUT_SECONDS = 300

# .NET char.IsWhiteSpace: Unicode Zs, Zl, Zp plus U+0009–U+000D, U+0085 (and U+00A0, a Zs).
# Python's str.isspace also counts U+001C–U+001F, which .NET does not; the port never uses it.
DOTNET_WHITESPACE = frozenset(
    "\t\n\x0b\x0c\r\x20\x85\xa0\u1680\u2028\u2029\u202f\u205f\u3000"
    + "".join(chr(c) for c in range(0x2000, 0x200B)))
# NumberStyles.Float: leading/trailing white space, a leading sign, a decimal point, an exponent.
_FLOAT_STYLE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_DIGITS = re.compile(r"[0-9]+")
INT32_MAX = 2**31 - 1
INT64_MAX = 2**63 - 1
DECIMAL_MAX = Decimal(79228162514264337593543950335)


def dotnet_trim(value: str) -> str:
    start, end = 0, len(value)
    while start < end and value[start] in DOTNET_WHITESPACE:
        start += 1
    while end > start and value[end - 1] in DOTNET_WHITESPACE:
        end -= 1
    return value[start:end]


def _ascii_lower(value: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in value)


def container_supported(format_name: str | None, major_brand: str | None) -> bool:
    """Exact port of ``PhaseOneMp4ContainerPolicy.IsSupported``, in its order."""
    if format_name is None:
        return False
    formats = [dotnet_trim(part) for part in format_name.split(",")]
    if not any(_ascii_lower(entry) == "mp4" for entry in formats if entry):
        return False
    if major_brand is None:
        return False
    brand = _ascii_lower(dotnet_trim(major_brand).rstrip("\0"))
    if not brand or not dotnet_trim(brand):
        return False
    return brand != "qt" and not brand.startswith("3gp") and not brand.startswith("3g2")


class _ReaderRefuses(Exception):
    """The platform reader throws (rather than falling back) for this value."""


def _duration_ms(value: object) -> int | None:
    """``TryReadDurationMs``: decimal parse, ``seconds > 0``, × 1000 rounded half away from zero."""
    if not isinstance(value, str):
        return None
    # .NET number parsing allows only U+0009–U+000D and U+0020 as leading/trailing white space.
    text = value.strip("\t\n\x0b\x0c\r ")
    if not _FLOAT_STYLE.fullmatch(text):
        return None
    try:
        seconds = Decimal(text)
    except InvalidOperation:
        return None
    if seconds <= 0:
        return None
    if seconds > DECIMAL_MAX:
        return None  # decimal.TryParse fails beyond System.Decimal's range.
    milliseconds = int((seconds * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if milliseconds > INT64_MAX:
        # The reader's checked (long) conversion throws: the whole metadata read fails, with no fallback.
        raise _ReaderRefuses
    return milliseconds if milliseconds > 0 else None


def _rational(value: object) -> tuple[int, int] | None:
    """``TryParseRational``: ``n/d`` of plain digits (``NumberStyles.None``), both positive, reduced."""
    if not isinstance(value, str):
        return None
    parts = value.split("/")
    if len(parts) != 2 or not all(_DIGITS.fullmatch(part) for part in parts):
        return None
    numerator, denominator = int(parts[0]), int(parts[1])
    if not (0 < numerator <= INT32_MAX and 0 < denominator <= INT32_MAX):
        return None
    from math import gcd
    divisor = gcd(numerator, denominator)
    return numerator // divisor, denominator // divisor


def _positive_int(value: object) -> int | None:
    return value if type(value) is int and 0 < value <= INT32_MAX else None


def _nonblank(value: object) -> str | None:
    return value if isinstance(value, str) and dotnet_trim(value) else None


def describe(ffprobe_output: dict[str, Any]) -> dict[str, Any]:
    """The probe members derived from ffprobe's JSON (the platform reader's rules)."""
    fmt = ffprobe_output.get("format")
    a.require(isinstance(fmt, dict), "probe_invalid_media")
    streams = ffprobe_output.get("streams")
    streams = streams if isinstance(streams, list) else []
    videos = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    tags = fmt.get("tags") if isinstance(fmt.get("tags"), dict) else {}
    major_brand = tags.get("major_brand") if isinstance(tags.get("major_brand"), str) else None
    format_name = fmt.get("format_name") if isinstance(fmt.get("format_name"), str) else None
    reader_refuses = False
    try:
        format_duration = _duration_ms(fmt.get("duration"))
    except _ReaderRefuses:
        format_duration, reader_refuses = None, True

    video = None
    metadata_valid = False
    if videos:
        stream = videos[0]
        width, height = _positive_int(stream.get("width")), _positive_int(stream.get("height"))
        codec = _nonblank(stream.get("codec_name"))
        rate = _rational(stream.get("avg_frame_rate")) or _rational(stream.get("r_frame_rate"))
        try:
            duration = format_duration if format_duration is not None or reader_refuses \
                else _duration_ms(stream.get("duration"))
        except _ReaderRefuses:
            duration, reader_refuses = None, True
        frames = stream.get("nb_frames")
        frame_count = int(frames) if isinstance(frames, str) and _DIGITS.fullmatch(frames) else None
        metadata_valid = (width is not None and height is not None and codec is not None and rate is not None
                          and duration is not None and _nonblank(format_name) is not None)
        video = {
            "codec": codec,
            "profile": _nonblank(stream.get("profile")),
            "width": width,
            "height": height,
            "frameRateNumerator": rate[0] if rate else None,
            "frameRateDenominator": rate[1] if rate else None,
            "durationMs": duration,
            "frameCount": frame_count,
            "frameCountSource": "container" if frame_count is not None else None,
        }
    return {
        "format": {"formatName": format_name, "majorBrand": major_brand, "durationMs": format_duration},
        "videoStreamCount": len(videos),
        "video": video,
        "maviImport": {"policy": POLICY, "containerSupported": container_supported(format_name, major_brand),
                       "metadataValid": metadata_valid},
    }


def _file_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
                size += len(block)
    except OSError as exc:
        raise a.S32Error("probe_input_unreadable") from exc
    return digest.hexdigest(), size


def probe(ffprobe: media_tools.Tool, path: Path) -> dict[str, Any]:
    """A ``vehicle-subclass-media-probe-v1`` record for the file at ``path`` (never naming it)."""
    path = Path(path)
    a.require(path.is_file(), "probe_input_unreadable")
    sha256, size = _file_identity(path)
    media_tools.require_unchanged(ffprobe)
    try:
        result = subprocess.run([str(ffprobe.path), *FFPROBE_ARGS, str(path)], capture_output=True,
                                timeout=PROBE_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise a.S32Error("probe_failed") from exc
    a.require(result.returncode == 0, "probe_failed")
    try:
        output = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise a.S32Error("probe_failed") from exc
    a.require(isinstance(output, dict), "probe_failed")
    # The input file is re-hashed after probing so the record describes the bytes ffprobe read.
    a.require(_file_identity(path) == (sha256, size), "probe_input_unreadable:changed")
    record = {"schemaVersion": SCHEMA, "sourceSha256": sha256, "sourceSizeBytes": size,
              "ffprobe": ffprobe.identity, **describe(output)}
    a.validate(record, SCHEMA, "probe_invalid")
    return record


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--media-tools", type=Path, required=True)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        a.require(not args.out.exists(), "output_exists")
        data = a.canonical_json(probe(media_tools.load(args.media_tools, "ffprobe"), args.input))
        a.write_once(args.out, data)
    except a.S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(a.sha256_hex(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
