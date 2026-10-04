"""``prepare`` (S3.2d-1 plan §11 step 2): reconciled source → canonical ground truth and derived MP4s.

1. The frozen descriptor is loaded (``BLOCKED`` refused) and its **whole** manifest reconciled against the source
   root before discovery (``descriptor.reconcile``); discovery must find exactly the sequences the manifest describes.
2. Per sequence, the adapter writes canonical ground truth (validated as association will read it).
3. Per sequence, the labelled frame images are copied from verified bytes into a staging directory and encoded with
   the verified FFmpeg pack and pinned arguments (libx264, single thread, bit-exact flags) at the descriptor's
   ``index-at-fps`` rate, so derived frame ``k`` is labelled frame ``k``: the labelled-rate video. The output must be
   importable by MAVI and carry exactly that frame count and rate (``probe_media``, the platform reader's rules).
4. The derivation manifest names the descriptor, adapter, tools, arguments and every sequence's source frames, video
   and ground-truth hashes; its SHA-256 is the envelope's ``derivationManifestSha256``.

Everything is written into a new directory that appears only on success (``OutputDirectory``).
"""

from __future__ import annotations

import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.benchmarks import datasets
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as gt_module
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import (
    OutputDirectory, canonical_json, document_sha256, rational, read_artefact, require, sha256_hex)
from tools.benchmarks.datasets import bdd100k_mot, synthetic

import media_tools  # noqa: E402  (tools/stage3, on the path via _stage3)
import probe_media  # noqa: E402

KIND = "benchmark-derivation-manifest-v1"
MANIFEST = "derivation-manifest.json"
GROUND_TRUTH = "ground-truth.json"
VIDEO = "video.mp4"
ADAPTERS = {synthetic.ADAPTER_ID: synthetic.SyntheticAdapter,
            bdd100k_mot.ADAPTER_ID: bdd100k_mot.Bdd100kMotAdapter}
FFMPEG_TIMEOUT_SECONDS = 6 * 3600
# Labelled frames → MP4 (the S3.2 transcode settings applied to an image sequence; deterministic for one binary).
ARGS = ["-nostdin", "-hide_banner", "-loglevel", "error", "-f", "image2", "-framerate", "{rate}",
        "-start_number", "0", "-i", "{input}", "-map", "0:v:0", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-pix_fmt", "yuv420p", "-threads", "1", "-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-movflags", "+faststart", "-f", "mp4", "{output}"]


def adapter(adapter_id: str):
    require(adapter_id in ADAPTERS, f"adapter_unknown:{adapter_id}")
    return ADAPTERS[adapter_id]()


def _encode(ffmpeg: media_tools.Tool, frames: Path, extension: str, rate: Fraction, output: Path) -> None:
    rendered = {"{rate}": f"{rate.numerator}/{rate.denominator}", "{input}": str(frames / f"%06d{extension}"),
                "{output}": str(output)}
    command = [str(ffmpeg.path), *(rendered.get(part, part) for part in ARGS)]
    media_tools.require_unchanged(ffmpeg)
    try:
        result = subprocess.run(command, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise artefacts.S32Error("derivation_ffmpeg_failed") from exc
    require(result.returncode == 0 and output.is_file(), f"derivation_ffmpeg_failed:{result.returncode}")


def prepare(*, descriptor_path: Path, source_root: Path, split: str, adapter_id: str, media_tools_dir: Path,
            out: Path) -> str:
    """Writes ``out`` (a new directory) and returns the derivation manifest's SHA-256."""
    document, descriptor_sha = descriptors.load(descriptor_path)
    entries = descriptors.reconcile(document, source_root)
    require(descriptors.split(document, split)["labelled"], f"descriptor_invalid:split_unlabelled:{split}")
    frame_time = document["frameTime"]
    require(frame_time["kind"] == "index-at-fps", "derivation_frame_time_unsupported")
    rate = Fraction(frame_time["fpsNumerator"], frame_time["fpsDenominator"])
    source = adapter(adapter_id)
    sequences = datasets.discover(source, source_root, entries, split)
    ffmpeg = media_tools.load(media_tools_dir, "ffmpeg")
    ffprobe = media_tools.load(media_tools_dir, "ffprobe")
    rows = []
    with OutputDirectory(out) as staging:
        for sequence in sequences:
            directory = staging / "sequences" / sequence
            directory.mkdir(parents=True)
            gt = source.ground_truth(source_root, entries, document, split, sequence)
            gt_module.validate(gt)
            (directory / GROUND_TRUTH).write_bytes(canonical_json(gt))
            frames = source.frame_paths(source_root, entries, split, sequence)
            indices = [index for index, _ in frames]
            require(indices == list(range(len(frames))) and indices == [i["frameIndex"] for i in gt["instants"]],
                    f"derivation_frames_not_contiguous:{sequence}")
            extensions = {Path(path).suffix for _, path in frames}
            require(len(extensions) == 1, f"derivation_frames_mixed:{sequence}")
            extension = extensions.pop()
            work = staging / f".frames-{sequence}"
            work.mkdir()
            for index, path in frames:
                (work / f"{index:06d}{extension}").write_bytes(descriptors.read_verified(entries, source_root, path))
            video = directory / VIDEO
            _encode(ffmpeg, work, extension, rate, video)
            shutil.rmtree(work)
            probe = probe_media.probe(ffprobe, video)
            described = probe["video"] or {}
            require(probe["maviImport"]["containerSupported"] and probe["maviImport"]["metadataValid"]
                    and described.get("frameCount") == len(frames)
                    and Fraction(described.get("frameRateNumerator") or 0, described.get("frameRateDenominator") or 1)
                    == rate, f"derivation_output_inconsistent:{sequence}")
            data = video.read_bytes()
            rows.append({"sequenceId": sequence, "frameCount": len(frames),
                         "sourceFrames": [path for _, path in frames],
                         "derivedVideoSha256": sha256_hex(data), "derivedVideoSizeBytes": len(data),
                         "groundTruthSha256": document_sha256(gt)})
        manifest = {"kind": KIND, "descriptorSha256": descriptor_sha, "datasetId": document["datasetId"],
                    "release": document["release"], "split": split,
                    "adapter": {"id": source.adapter_id, "version": source.adapter_version},
                    "ffmpeg": ffmpeg.identity, "ffprobe": ffprobe.identity, "args": ARGS, "frameRate": rational(rate),
                    "sequences": rows}
        data = canonical_json(manifest)
        (staging / MANIFEST).write_bytes(data)
    return sha256_hex(data)


def load(derived: Path) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    """A prepared directory: (manifest, its SHA-256, canonical GT by sequence), every file re-hashed."""
    derived = Path(derived)
    data = artefacts.read_bytes(derived / MANIFEST, "derivation_invalid")
    manifest = artefacts.parse_json(data, "derivation_invalid")
    require(isinstance(manifest, dict) and manifest.get("kind") == KIND and canonical_json(manifest) == data,
            "derivation_invalid")
    require(isinstance(manifest.get("sequences"), list) and manifest["sequences"], "derivation_invalid:sequences")
    documents: dict[str, dict[str, Any]] = {}
    for row in manifest["sequences"]:
        sequence = row["sequenceId"]
        directory = derived / "sequences" / artefacts.safe_relative(sequence, "derivation_invalid:sequence")
        gt_bytes = artefacts.read_bytes(directory / GROUND_TRUTH, "derivation_invalid")
        document = artefacts.parse_json(gt_bytes, "derivation_invalid")
        require(canonical_json(document) == gt_bytes and sha256_hex(gt_bytes) == row["groundTruthSha256"],
                f"derivation_invalid:ground_truth:{sequence}")
        video = artefacts.read_bytes(directory / VIDEO, "derivation_invalid")
        require(sha256_hex(video) == row["derivedVideoSha256"], f"derivation_invalid:video:{sequence}")
        require(sequence not in documents, "derivation_invalid:duplicate_sequence")
        documents[sequence] = document
    return manifest, sha256_hex(data), documents


__all__ = ["prepare", "load", "adapter", "read_artefact"]
