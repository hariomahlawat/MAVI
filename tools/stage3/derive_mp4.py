#!/usr/bin/env python3
"""MP4 derivation (Stage 3, S3.2 plan T8): ``vehicle-subclass-derivation-v1``.

Turns one authorised release member into ``<out>/video.mp4`` (what T9 imports) and
``<out>/derivation-manifest.json``. No second rights or provenance model exists: the release
record is read, verified and authorised only through ``attributes.datasets.release``; T8
makes no legal judgement and only enforces the determination in force, bound by
``releaseRecordSha256``. The mode is explicit and has a precondition; there is no fallback.

Order of checks (plan T8): parse the release; verify the store (outside Git); member listed
and not excluded; copy-hash the member into staging; authorise for the mode's operations;
mode; probe the verified copy (exactly one video stream); mode precondition; FFmpeg with the
pinned arguments; output probe and importability; manifest consistency. Everything is built in
a hidden staging sibling and published by one rename, so a refusal leaves no output.

Usage: ``derive_mp4.py --media-tools <dir> --release <record> --release-root <dir>
--member <release-relative path> --mode passthrough|remux|transcode --max-import-bytes <n>
--out <new-dir>``. ``--media-tools`` and ``--release-root`` are runtime-only and never recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artefacts as a  # noqa: E402
import media_tools  # noqa: E402
import probe_media  # noqa: E402
import release_bridge as rb  # noqa: E402

SCHEMA = "vehicle-subclass-derivation-v1"
VIDEO = "video.mp4"
MANIFEST = "derivation-manifest.json"
SOURCE_COPY = ".source"
MODES = ("passthrough", "remux", "transcode")
OPERATIONS = {"passthrough": [], "remux": ["create-derivatives"], "transcode": ["create-derivatives"]}
REMUX_CODECS = ("h264",)
FFMPEG_TIMEOUT_SECONDS = 6 * 3600
_HEAD = ["-nostdin", "-hide_banner", "-loglevel", "error", "-i", "{input}", "-map", "0:v:0"]
_TAIL = ["-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact",
         "-flags:v", "+bitexact", "-movflags", "+faststart", "-f", "mp4", "{output}"]
ARGS = {
    "passthrough": [],
    "remux": [*_HEAD, "-c:v", "copy", *_TAIL],
    "transcode": [*_HEAD, "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
                  "-threads", "1", *_TAIL],
}


def _copy_hashed(source: Path, target: Path) -> tuple[str, int]:
    """Copies ``source`` to ``target`` while hashing; everything after reads only the copy."""
    digest = hashlib.sha256()
    size = 0
    try:
        with open(source, "rb") as reader, open(target, "xb") as writer:
            for block in iter(lambda: reader.read(1 << 20), b""):
                digest.update(block)
                size += len(block)
                writer.write(block)
    except OSError as exc:
        raise a.S32Error("derivation_member_changed:unreadable") from exc
    return digest.hexdigest(), size


def importable(probe: dict[str, Any], size: int, limit: int, name: str) -> bool:
    """What MAVI's import accepts: the Phase-1 container policy, the reader's metadata, the
    host's size limit and the ``.mp4`` file name T8 always writes."""
    return (probe["maviImport"]["containerSupported"] and probe["maviImport"]["metadataValid"]
            and size <= limit and name == VIDEO)


def _probe(ffprobe: media_tools.Tool, path: Path, code: str) -> dict[str, Any]:
    try:
        return probe_media.probe(ffprobe, path)
    except a.S32Error as exc:
        if exc.code == media_tools.CODE:
            raise
        raise a.S32Error(f"{code}:{exc}") from exc


def _ffmpeg(ffmpeg: media_tools.Tool, mode: str, source: Path, output: Path) -> None:
    command = [str(ffmpeg.path)] + [str(source) if part == "{input}" else str(output) if part == "{output}" else part
                                    for part in ARGS[mode]]
    media_tools.require_unchanged(ffmpeg)
    try:
        result = subprocess.run(command, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise a.S32Error("derivation_ffmpeg_failed") from exc
    a.require(result.returncode == 0 and output.is_file(), f"derivation_ffmpeg_failed:{result.returncode}")


def derive(*, media_tools_dir: Path, release_path: Path, release_root: Path, member: str, mode: str,
           max_import_bytes: int, out: Path) -> bytes:
    """Builds ``out``; returns the manifest's canonical bytes."""
    a.require(type(max_import_bytes) is int and max_import_bytes > 0, "derivation_import_limit_invalid")
    a.require(not Path(out).exists(), "output_exists")
    # The mode selects the operations to authorise, so an unknown mode is refused before any work.
    a.require(mode in MODES, "derivation_mode_invalid")
    # Derived corpus video never lands in a Git worktree (no video datasets in Git).
    a.require(rb.git_worktree_ancestor(Path(out).absolute().parent) is None, "derivation_output_in_git")
    release, release_sha = rb.read_release(release_path, "derivation_release_invalid")
    rb.verify_store(release, release_root, "derivation_release_root_invalid", "derivation_release_files_mismatch")
    entry = rb.member_entry(release, member, "derivation_member_not_listed", "derivation_member_excluded")

    with a.OutputDirectory(out) as staging:
        source_copy = staging / SOURCE_COPY
        sha, size = _copy_hashed(Path(release_root) / member, source_copy)
        a.require(sha == entry["sha256"] and size == entry["sizeBytes"], "derivation_member_changed")

        blockers = rb.authorise(release, member, OPERATIONS[mode])
        a.require(not blockers, "derivation_not_authorised:" + ",".join(blockers))

        ffprobe = media_tools.load(media_tools_dir, "ffprobe")
        ffmpeg = media_tools.load(media_tools_dir, "ffmpeg") if mode != "passthrough" else None
        source_media = _probe(ffprobe, source_copy, "derivation_probe_failed")
        a.require(source_media["videoStreamCount"] == 1, "derivation_probe_failed:video_streams")

        video = staging / VIDEO
        if mode == "passthrough":
            a.require(importable(source_media, size, max_import_bytes, VIDEO), "derivation_passthrough_not_importable")
            source_copy.rename(video)
        else:
            if mode == "remux":
                a.require(source_media["video"]["codec"] in REMUX_CODECS, "derivation_remux_codec_unsupported")
            _ffmpeg(ffmpeg, mode, source_copy, video)
            source_copy.unlink()

        output_media = _probe(ffprobe, video, "derivation_output_not_importable")
        output_sha = output_media["sourceSha256"]
        a.require(output_media["videoStreamCount"] == 1
                  and importable(output_media, output_media["sourceSizeBytes"], max_import_bytes, video.name),
                  "derivation_output_not_importable")

        manifest = {
            "schemaVersion": SCHEMA,
            "release": {"releaseId": release["releaseId"], "releaseRecordSha256": release_sha, "member": member},
            "authorisation": {"purposes": list(rb.PURPOSES), "operations": OPERATIONS[mode], "blockers": []},
            "sourceSha256": sha,
            "sourceMedia": source_media,
            "mode": mode,
            "ffmpegVersion": ffmpeg.version if ffmpeg else None,
            "ffmpegSha256": ffmpeg.sha256 if ffmpeg else None,
            "args": ARGS[mode],
            "outputSha256": output_sha,
            "outputMedia": output_media,
            "importLimitBytes": max_import_bytes,
        }
        check_consistency(manifest, a.sha256_hex(video.read_bytes()))
        a.validate(manifest, SCHEMA, "derivation_output_inconsistent")
        data = a.canonical_json(manifest)
        (staging / MANIFEST).write_bytes(data)
    return data


def check_consistency(manifest: dict[str, Any], written_sha256: str) -> None:
    """The member equalities the schema cannot express (``derivation_output_inconsistent``)."""
    code = "derivation_output_inconsistent"
    a.require(manifest["outputSha256"] == written_sha256, f"{code}:output")
    a.require(manifest["sourceMedia"]["sourceSha256"] == manifest["sourceSha256"], f"{code}:source_media")
    a.require(manifest["outputMedia"]["sourceSha256"] == manifest["outputSha256"], f"{code}:output_media")
    if manifest["mode"] == "passthrough":
        a.require(manifest["outputSha256"] == manifest["sourceSha256"], f"{code}:passthrough")
    else:
        a.require(manifest["outputSha256"] != manifest["sourceSha256"], f"{code}:unchanged")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--media-tools", type=Path, required=True)
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--release-root", type=Path, required=True)
    p.add_argument("--member", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--max-import-bytes", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        data = derive(media_tools_dir=args.media_tools, release_path=args.release, release_root=args.release_root,
                      member=args.member, mode=args.mode, max_import_bytes=args.max_import_bytes, out=args.out)
    except a.S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(a.sha256_hex(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
