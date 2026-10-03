"""Synthetic S3.2b fixtures: a verified media pack, tiny generated media, and release records.

The media pack is resolved, in order, from ``MAVI_TEST_MEDIA_TOOLS`` (a real MAVI FFmpeg
dependency pack, e.g. the staged ``vendor/ffmpeg``), or a throwaway pack built around the
test environment's own ``ffmpeg``/``ffprobe`` (``shutil.which`` is used here, in tests only;
the tools under test never search PATH). Without either the media tests skip, unless
``MAVI_REQUIRE_MEDIA_TESTS=1`` (set in CI), when they fail. Nothing here is a real release,
licence, determination or corpus file.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

STAGE3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE3))
import artefacts as a  # noqa: E402
import media_tools  # noqa: E402
import release_bridge as rb  # noqa: E402

rel = rb.release_module
INVENTORY_ALL = {op: "granted" for op in rel.INVENTORY_OPERATIONS}
RELEASE_ID = "synthetic-s32b-release"


# ---------------------------------------------------------------- media pack


def _missing(reason: str):
    if os.environ.get("MAVI_REQUIRE_MEDIA_TESTS") == "1":
        pytest.fail(f"media tests required but unavailable: {reason}")
    pytest.skip(f"no media pack: {reason}")


def _version_token(executable: str) -> str:
    output = subprocess.run([executable, "-version"], capture_output=True, check=True).stdout.decode("utf-8", "replace")
    match = re.match(r"\S+ version (\S+)", output)
    assert match, output[:200]
    return match.group(1)


def write_manifest(pack: Path, version: str, runtime: str | None = None, entries: list[dict] | None = None) -> None:
    runtime = runtime or media_tools.current_runtime_id()
    if entries is None:
        entries = [{"fileName": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in sorted((pack / media_tools.current_runtime_id()).iterdir())]
    document = {"schemaVersion": "1.0", "runtimeId": runtime, "version": version, "artifacts": entries}
    (pack / "manifest.json").write_bytes(json.dumps(document, indent=2).encode("utf-8"))


def build_pack(target: Path) -> Path:
    """A pack at ``target`` (a copy, so tests may mutate it)."""
    configured = os.environ.get("MAVI_TEST_MEDIA_TOOLS")
    if configured:
        source = Path(configured)
        if not (source / "manifest.json").is_file():
            _missing(f"MAVI_TEST_MEDIA_TOOLS has no manifest.json")
        shutil.copytree(source, target)
        return target
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        _missing("set MAVI_TEST_MEDIA_TOOLS or install ffmpeg/ffprobe")
    binaries = target / media_tools.current_runtime_id()
    binaries.mkdir(parents=True)
    for tool in (ffmpeg, ffprobe):
        destination = binaries / media_tools.executable_name(Path(tool).stem)
        shutil.copy2(tool, destination)
    write_manifest(target, _version_token(ffmpeg))
    return target


def tool_path(pack: Path, tool: str) -> Path:
    return pack / media_tools.current_runtime_id() / media_tools.executable_name(tool)


# ---------------------------------------------------------------- synthetic media

_BITEXACT = ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact"]
_TESTSRC = ["-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=1"]
_TESTSRC2 = ["-f", "lavfi", "-i", "testsrc2=size=32x24:rate=10:duration=1"]
_H264 = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-threads", "1"]

MEDIA = {
    "h264.mp4": [*_TESTSRC, *_H264, *_BITEXACT, "-f", "mp4"],
    "h264.mkv": [*_TESTSRC, *_H264, *_BITEXACT, "-f", "matroska"],
    "mpeg4.mkv": [*_TESTSRC, "-c:v", "mpeg4", *_BITEXACT, "-f", "matroska"],
    "quicktime.mov": [*_TESTSRC, *_H264, *_BITEXACT, "-f", "mov"],
    "brand3gp.3gp": [*_TESTSRC, *_H264, *_BITEXACT, "-f", "3gp"],
    "brand3g2.3g2": [*_TESTSRC, *_H264, *_BITEXACT, "-f", "3g2"],
    "audio-only.mp4": ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", *_BITEXACT, "-f", "mp4"],
    "two-video.mp4": [*_TESTSRC, *_TESTSRC2, "-map", "0:v", "-map", "1:v", *_H264, *_BITEXACT, "-f", "mp4"],
}


def make_media(pack: Path, directory: Path) -> dict[str, bytes]:
    directory.mkdir(parents=True, exist_ok=True)
    ffmpeg = str(tool_path(pack, "ffmpeg"))
    produced: dict[str, bytes] = {}
    for name, args in MEDIA.items():
        target = directory / name
        subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", *args, str(target)],
                       capture_output=True, check=True)
        produced[name] = target.read_bytes()
    produced["invalid.mp4"] = b"\x00not a media file at all\x00" * 8
    return produced


# ---------------------------------------------------------------- release records


def files_of(members: dict[str, bytes]) -> list[dict[str, Any]]:
    return [{"path": path, "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in sorted(members.items())]


def determination(inventory: dict[str, str] | None = None, **over) -> dict[str, Any]:
    record = {
        "determinationId": "synthetic-s32b", "reviewedOn": "2026-10-03",
        "purposes": ["benchmarking", "development"],
        "licenceCodes": ["cc-by-4.0"],
        "rights": {"reviewedBy": "R-5", "determination": "PERMITTED_FOR_ENGINEERING_USE",
                   "evidence": "synthetic fixture determination", "inventory": dict(inventory or INVENTORY_ALL)},
        "privacy": {"reviewedBy": "Synthetic Reviewer", "disposition": "PERMITTED",
                    "basis": "synthetic test media; no person depicted"},
        "r5Ruling": None,
    }
    record.update(over)
    return record


def release_document(members: dict[str, bytes], det: Any = ..., excluded: tuple[str, ...] = (),
                     release_id: str = RELEASE_ID) -> dict[str, Any]:
    document = {
        "schemaVersion": rel.RELEASE_SCHEMA, "releaseId": release_id, "name": "Synthetic S3.2b release",
        "version": "fixture", "origin": "public", "officialUrl": "https://example.invalid/synthetic",
        "pinnedSource": {"kind": "google-drive-folder", "reference": "synthetic-fixture", "retrievedOn": "2026-10-02"},
        "licence": {"codes": ["cc-by-4.0"], "url": "https://creativecommons.org/licenses/by/4.0/", "textSha256": "a" * 64},
        "files": files_of(members), "excludedMembers": [{"path": p, "reason": "synthetic exclusion"} for p in excluded],
        "determination": determination() if det is ... else det,
        "knownExposure": [],
    }
    rel.parse_release(copy.deepcopy(document))
    return document


def write_store(root: Path, members: dict[str, bytes]) -> Path:
    for path, data in members.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    return root


def write_release(path: Path, document: dict[str, Any]) -> Path:
    path.write_bytes(json.dumps(document, indent=2).encode("utf-8"))
    return path


def release_sha256(document: dict[str, Any]) -> str:
    return rel.release_sha256(rel.parse_release(copy.deepcopy(document)))


def sha(data: bytes) -> str:
    return a.sha256_hex(data)


def clone_pack(source: Path, target: Path) -> Path:
    """A pack sharing the binaries (hard links where possible) so a test may rewrite only its manifest."""
    runtime = media_tools.current_runtime_id()
    (target / runtime).mkdir(parents=True)
    for item in (source / runtime).iterdir():
        try:
            os.link(item, target / runtime / item.name)
        except OSError:
            shutil.copy2(item, target / runtime / item.name)
    shutil.copy2(source / "manifest.json", target / "manifest.json")
    return target


def manifest_of(pack: Path) -> dict[str, Any]:
    return json.loads((pack / "manifest.json").read_bytes().decode("utf-8-sig"))


def rewrite_manifest(pack: Path, document: dict[str, Any]) -> None:
    (pack / "manifest.json").write_bytes(json.dumps(document).encode("utf-8"))
