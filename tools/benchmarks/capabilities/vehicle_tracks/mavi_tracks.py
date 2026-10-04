"""The class-free MAVI view association receives (plan §7 inputs).

From one T1 export (one processing run of one derived video): the capability selection first (``objectClass`` is
``Vehicle``; Person Tracks never enter association, any count or any denominator), then a projection holding only
the Track id, its decoded trajectory points, and its observation times and boxes, plus the run's video and run ids.
Subclass, its source and vocabulary, and confidence summaries are never copied.

**Observation timing (plan §2; S3.2d-1 slice 1 deferred check).** MAVI's video reader numbers decoded frames from 0
(``sourceFrameNumber``) and stamps each with its presentation time rounded half up to whole ms, relative to the
first frame (``videoOffsetMs``; ``src/vision/mavi_vision/video/reader.py``). The benchmark processes derived videos
encoded at a constant declared rate, so every observation must satisfy
``videoOffsetMs == round_half_up(sourceFrameNumber × 1000 × den / num)`` for the export's declared rate;
otherwise the run is refused (``export_invalid:observation_timing``) rather than aligned on a clock the GT does not
share.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from tools.benchmarks.capabilities.vehicle_tracks import trajectory
from tools.benchmarks.capabilities.vehicle_tracks.ground_truth import Box, box
from tools.benchmarks.core import mavi
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import require


# T1 stores boxes in single precision (shortest round-trip form): x + width may exceed 1 by a float32 ulp.
SINGLE_PRECISION_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class Observation:
    offset_ms: int
    box: Box


@dataclass(frozen=True, slots=True)
class MaviTrack:
    mavi_track_id: str
    points: tuple[trajectory.Point, ...]
    observations: tuple[Observation, ...]


@dataclass(frozen=True, slots=True)
class MaviRun:
    video_asset_id: str
    processing_run_id: str
    frame_rate: Fraction
    tracks: tuple[MaviTrack, ...]  # sorted by mavi_track_id
    # Input identities (hashes only), checked against the run envelope before anything is scored.
    export_sha256: str
    source_sha256: str  # the imported video: the sequence's derived video
    trajectory_sha256s: frozenset[str]

    @property
    def point_count(self) -> int:
        return sum(len(track.points) for track in self.tracks)


def round_half_up(value: Fraction) -> int:
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def frame_rate(export: artefacts.Export) -> Fraction:
    video = export.video
    return Fraction(video["frameRateNumerator"], video["frameRateDenominator"])


def require_observation_timing(export: artefacts.Export) -> None:
    period = Fraction(1000) / frame_rate(export)
    for track in mavi.vehicle_tracks(export):
        for observation in track["observations"]:
            expected = round_half_up(observation["sourceFrameNumber"] * period)
            require(observation["videoOffsetMs"] == expected, f"export_invalid:observation_timing:{track['id']}")


def project(export: artefacts.Export, evidence_root: Path) -> MaviRun:
    require_observation_timing(export)
    tracks = []
    for track in sorted(mavi.vehicle_tracks(export), key=lambda item: item["id"]):
        require(track["trajectorySha256"] is not None, f"trajectory_missing:{track['id']}")
        observations = sorted(
            (Observation(item["videoOffsetMs"], box(item["boundingBox"], f"export_invalid:box:{track['id']}",
                                                    SINGLE_PRECISION_TOLERANCE))
             for item in track["observations"]), key=lambda item: item.offset_ms)
        tracks.append(MaviTrack(track["id"], trajectory.read(evidence_root, track["trajectorySha256"]),
                                tuple(observations)))
    run = export.document["processingRun"]
    trajectories = frozenset(track["trajectorySha256"] for track in mavi.vehicle_tracks(export))
    return MaviRun(run["videoAssetId"], run["processingRunId"], frame_rate(export), tuple(tracks), export.sha256,
                   export.video["sourceSha256"], trajectories)
