"""Synthetic S3.2 fixtures: T1-shaped exports with real evidence bytes, tiny MP4 sources,
T8-shaped derivation manifests, and a throwaway git repository holding *synthetic*
requirements and labelling-guide files. Nothing here is a real requirement, guide,
release or label; it exists to exercise the hash, commit and lineage bindings."""

from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STAGE3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE3))
sys.path.insert(0, str(STAGE3.parent / "phase1"))
import artefacts as a  # noqa: E402

EXAMPLE = a.ROOT / "contracts" / "examples" / "vehicle-subclass-measurement-export-v1.example.json"
ROLES = ("Representative", "NearView", "EarlyDiverse", "LateDiverse")

PROFILE = {
    "schemaVersion": "1.2",
    "profileId": "phase1-detection-tracking-v1",
    "profileVersion": "1.3.0-candidate",
    "evidence": {"selectorVersion": "evidence-selector-v1-two-tier", "scorerVersion": "quality-v2"},
    "vehicleSubclass": {"vocabularyId": "mavi-vehicle-subclass-v1", "minShare": 0.6, "minMatchedDetections": 3},
    "synthetic": "S3.2a-2 test fixture profile",
}

# Clearly synthetic: these numbers are not, and must not be read as, the owner's requirements.
SYNTHETIC_REQUIREMENTS = {
    "schemaVersion": "vehicle-subclass-requirements-v1",
    "labelVocabulary": "mavi-vehicle-subclass-labels-v1",
    "operational": {
        "coverageOverEvaluable": {"minimum": 0.5},
        "perClass": {
            "car": {"precision": {"minimum": 0.5}, "recall": {"minimum": 0.5}},
            "truck": {"precision": {"minimum": 0.9}, "recall": {"minimum": None}},
            "bus": {"precision": {"minimum": None}, "recall": {"minimum": None}},
            "motorcycle": {"precision": {"minimum": 0.5}, "recall": {"minimum": 0.5}},
        },
    },
    "minimumSupport": {"evaluablePerClass": 2, "evaluableTotal": 3},
    "insufficientSupportOutcome": "insufficient-support",
}

SYNTHETIC_GUIDE = """# SYNTHETIC S3.2 labelling guide (test fixture only)

This file exists only to exercise the commit binding. It is not the owner's guide.

## Labels
- car, truck, bus, motorcycle, unknown (with a reason).

## Boundary cases
- pickup, SUV, van, minivan, minibus or shuttle, box truck, tractor or trailer unit,
  emergency and service vehicles, scooter and moped, motorcycle with sidecar, bicycle,
  partial or truncated vehicles: fixture placeholder rules.

## Class or unknown
- Choose a class only when the visible evidence fits its definition; otherwise unknown.

## Mixed tracks
- A Track that changes identity is unknown / mixed-track.
"""


def jpeg(seed: int, size: tuple[int, int] = (48, 32)) -> bytes:
    from PIL import Image

    width, height = size
    image = Image.new("RGB", size)
    image.putdata([((x * 7 + seed * 31) % 256, (y * 11 + seed * 17) % 256, (x + y + seed * 5) % 256)
                   for y in range(height) for x in range(width)])
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def mp4(path: Path, *, frames: int = 12, size: tuple[int, int] = (160, 120), grey: int = 128) -> bytes:
    """A tiny MPEG-4 Part 2 video of uniform grey frames (the box-drawing test reads its pixels)."""
    import av
    import numpy

    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=25)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        stream.options = {"qscale": "1"}
        frame_data = numpy.full((size[1], size[0], 3), grey, dtype=numpy.uint8)
        for _ in range(frames):
            frame = av.VideoFrame.from_ndarray(frame_data, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path.read_bytes()


@dataclass
class TrackSpec:
    number: int
    object_class: str = "Vehicle"
    subclass: str | None = "car"  # None: the vote abstained (Vehicle) or no subclass (Person)
    start: int = 0
    end: int = 4000
    roles: tuple[str, ...] = ("Representative",)
    quality: float = 0.8
    box: tuple[float, float, float, float] = (0.25, 0.25, 0.5, 0.5)
    mean_confidence: float = 0.7
    frame_shift: int = 0  # moves every observation's source frame (a frame past the video's end)
    track_id: str = field(default_factory=lambda: str(uuid.uuid4()))


def write_export(directory: Path, *, run_id: str, video_id: str, camera: str, source: bytes,
                 profile_sha: str, tracks: list[TrackSpec], seed: int = 0) -> Path:
    """A T1-shaped export directory: canonical JSON plus evidence/<sha256>.jpg."""
    template = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    attestation = copy.deepcopy(template["processingRun"]["attestation"])
    attestation.update({"processingRunId": run_id, "videoAssetId": video_id, "pipelineProfileSha256": profile_sha,
                        "tracksCreated": len(tracks)})
    (directory / "evidence").mkdir(parents=True)
    exported = []
    for spec in tracks:
        observations = []
        for rank, role in enumerate(spec.roles):
            data = jpeg(seed * 1000 + spec.number * 10 + rank, (48 + rank * 4, 32 + spec.number % 5))
            sha = a.sha256_hex(data)
            (directory / "evidence" / f"{sha}.jpg").write_bytes(data)
            x, y, w, hh = spec.box
            observations.append({"evidenceRole": role, "evidenceRank": rank, "sourceFrameNumber": min(11, 2 + rank * 3) + spec.frame_shift,
                                 "videoOffsetMs": spec.start + rank * 100,
                                 "boundingBox": {"x": x, "y": y, "width": w, "height": hh},
                                 "qualityScore": round(spec.quality - rank * 0.05, 4),
                                 "evidenceSha256": sha, "evidenceSizeBytes": len(data), "evidencePath": f"evidence/{sha}.jpg"})
        vehicle = spec.object_class == "Vehicle"
        exported.append({
            "id": spec.track_id, "localTrackNumber": spec.number, "objectClass": spec.object_class,
            "startOffsetMs": spec.start, "endOffsetMs": spec.end, "detectionCount": 6,
            "meanConfidence": spec.mean_confidence, "maxConfidence": 0.95,
            "representative": {"videoOffsetMs": spec.start, "boundingBox": observations[0]["boundingBox"]},
            "objectSubclass": spec.subclass if vehicle else None,
            "objectSubclassVocabulary": "mavi-vehicle-subclass-v1" if vehicle else None,
            "objectSubclassSource": f"detector-native:{profile_sha}" if vehicle else None,
            "observations": observations, "trajectorySha256": a.sha256_hex(f"trajectory-{spec.track_id}".encode()),
        })
    document = {
        "schemaVersion": "vehicle-subclass-measurement-export-v1",
        "processingRun": {"processingRunId": run_id, "videoAssetId": video_id, "status": "Completed",
                          "completedAtUtc": template["processingRun"]["completedAtUtc"], "attestation": attestation},
        "video": {"videoAssetId": video_id, "cameraCode": camera, "sourceSha256": a.sha256_hex(source),
                  "sourceSizeBytes": len(source), "durationMs": 480, "width": 160, "height": 120,
                  "frameRateNumerator": 25, "frameRateDenominator": 1},
        "profile": {"pipelineProfileSha256": profile_sha, "evidenceSelectorVersion": "evidence-selector-v1-two-tier",
                    "evidenceScorerVersion": "quality-v2"},
        "tracks": sorted(exported, key=lambda t: t["localTrackNumber"]),
    }
    a.validate(document, "vehicle-subclass-measurement-export-v1", "fixture_export_invalid")
    path = directory / a.EXPORT_FILE_NAME
    path.write_bytes(a.canonical_json(document))
    return path


def write_derivation(path: Path, *, source: bytes, release_id: str = "synthetic-release-1",
                     release_record_sha: str = "e" * 64, member: str = "videos/clip.mp4", mode: str = "passthrough",
                     authorisation: dict[str, Any] | None = None) -> Path:
    """A T8-shaped manifest (consumer view only). ``source`` is the derived MP4 the export names; for a remux
    or transcode the release member's own bytes differ, so its digest is synthetic here."""
    sha = a.sha256_hex(source)
    derived = mode != "passthrough"
    document = {
        "schemaVersion": "vehicle-subclass-derivation-v1",
        "release": {"releaseId": release_id, "releaseRecordSha256": release_record_sha, "member": member},
        "authorisation": authorisation if authorisation is not None else {
            "purposes": ["benchmarking", "development"],
            "operations": ["create-derivatives"] if derived else [], "blockers": []},
        "sourceSha256": a.sha256_hex(b"release member " + source[:64]) if derived else sha,
        "sourceMedia": {"container": "mkv" if derived else "mp4"}, "mode": mode,
        "ffmpegVersion": "7.1" if derived else None, "ffmpegSha256": ("b" * 64) if derived else None,
        "args": ["-c", "copy"] if derived else [], "outputSha256": sha, "outputMedia": {"container": "mp4"},
    }
    path.write_bytes(a.canonical_json(document))
    return path


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "-c", "user.name=S32 Fixture", "-c", "user.email=fixture@invalid",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        capture_output=True, check=True, text=True)
    return result.stdout.strip()


def fixture_repository(root: Path, requirements: dict[str, Any] | None = None, guide: str = SYNTHETIC_GUIDE) -> tuple[Path, str]:
    repository = root / "repo"
    repository.mkdir()
    git(repository, "init", "-q")
    write_repository_files(repository, requirements or SYNTHETIC_REQUIREMENTS, guide)
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", "synthetic S3.2 fixture")
    return repository, git(repository, "rev-parse", "HEAD")


def write_repository_files(repository: Path, requirements: dict[str, Any], guide: str) -> None:
    requirements_path = repository / a.REQUIREMENTS_GIT_PATH
    requirements_path.parent.mkdir(parents=True, exist_ok=True)
    requirements_path.write_bytes(json.dumps(requirements, indent=2).encode("utf-8"))
    (repository / a.LABELING_GUIDE_GIT_PATH).write_bytes(guide.encode("utf-8"))


@dataclass
class Video:
    run_id: str
    video_id: str
    camera: str
    source_path: Path
    export_path: Path
    derivation_path: Path
    tracks: list[TrackSpec]


@dataclass
class World:
    root: Path
    repository: Path
    commit: str
    profile_path: Path
    profile_sha: str
    videos: list[Video]

    @property
    def requirements(self) -> Path:
        return self.repository / a.REQUIREMENTS_GIT_PATH

    @property
    def guide(self) -> Path:
        return self.repository / a.LABELING_GUIDE_GIT_PATH

    def exports(self) -> list[Path]:
        return [video.export_path for video in self.videos]

    def derivations(self) -> list[Path]:
        return [video.derivation_path for video in self.videos]

    def sources(self) -> list[Path]:
        return [video.source_path for video in self.videos]

    def track(self, number: int) -> TrackSpec:
        return next(t for v in self.videos for t in v.tracks if t.number == number)

    def video_of(self, number: int) -> Video:
        return next(v for v in self.videos if any(t.number == number for t in v.tracks))


def build_world(root: Path, layout: dict[str, list[TrackSpec]], *, requirements: dict[str, Any] | None = None,
                base: int = 0) -> World:
    """One export per camera code in ``layout``, each with its own source video and derivation."""
    root.mkdir(parents=True, exist_ok=True)
    repository, commit = fixture_repository(root, requirements)
    profile_bytes = json.dumps(PROFILE, indent=2).encode("utf-8")
    profile_path = root / "pipeline-profile.json"
    profile_path.write_bytes(profile_bytes)
    profile_sha = a.sha256_hex(profile_bytes)
    videos = []
    for index, (camera, tracks) in enumerate(sorted(layout.items())):
        run_id, video_id = str(uuid.UUID(int=0x1000 + base + index)), str(uuid.UUID(int=0x2000 + base + index))
        source_path = root / f"source-{index}.mp4"
        source = mp4(source_path, grey=20 + (80 + (base + index) * 20) % 200)
        export_path = write_export(root / f"export-{index}", run_id=run_id, video_id=video_id, camera=camera,
                                   source=source, profile_sha=profile_sha, tracks=tracks, seed=index)
        derivation_path = write_derivation(root / f"derivation-{index}.json", source=source,
                                           member=f"videos/{camera.lower()}.mp4")
        videos.append(Video(run_id, video_id, camera, source_path, export_path, derivation_path, tracks))
    return World(root, repository, commit, profile_path, profile_sha, videos)


def numbered(prefix: int, count: int, **kwargs: Any) -> list[TrackSpec]:
    return [TrackSpec(number=prefix + i, track_id=str(uuid.UUID(int=0x9000_0000 + prefix + i)), **kwargs) for i in range(count)]
