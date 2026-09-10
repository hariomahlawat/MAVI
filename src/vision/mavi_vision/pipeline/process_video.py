from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from uuid import UUID

import numpy as np
from PIL import Image

from mavi_vision.common.analytical import (
    NormalizedBoundingBox,
    ObjectClass,
    ProcessedTrack,
    RepresentativeObservation,
    TrajectoryPoint,
    VisionProcessingResult,
)
from mavi_vision.detection.interfaces import Detector
from mavi_vision.quality.scoring import representative_quality
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.storage.integrity import SourceIntegrityError, open_verified_source
from mavi_vision.tracking.interfaces import Tracker
from mavi_vision.video.reader import DecodedFrame, VideoReadError, iter_frames
from mavi_vision.video.trajectory import serialize_trajectory


class VideoProcessingError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(slots=True)
class _RepresentativeCandidate:
    observation: RepresentativeObservation
    crop: np.ndarray


@dataclass(slots=True)
class _TrackAccumulator:
    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    confidence_sum: float = 0.0
    observation_count: int = 0
    trajectory: list[TrajectoryPoint] = field(default_factory=list)
    representative: _RepresentativeCandidate | None = None


class VideoProcessor:
    def __init__(
        self,
        detector: Detector,
        tracker: Tracker,
        artifact_store: StagingArtifactStore,
    ) -> None:
        self._detector = detector
        self._tracker = tracker
        self._artifact_store = artifact_store

    def process(
        self,
        *,
        job_id: UUID,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
    ) -> VisionProcessingResult:
        if self._artifact_store.job_id != job_id:
            raise VideoProcessingError("pipeline_configuration_invalid")
        try:
            self._artifact_store.cleanup()
        except Exception as exc:
            raise VideoProcessingError("pipeline_configuration_invalid") from exc

        tracks: dict[str, _TrackAccumulator] = {}
        frames_processed = 0
        try:
            with open_verified_source(
                source_path,
                expected_size_bytes=expected_source_size_bytes,
                expected_sha256=expected_source_sha256,
            ) as verified:
                if verified.stream is None:
                    raise SourceIntegrityError("source_read_failed")
                for frame in iter_frames(verified.stream):
                    frames_processed += 1
                    detections = self._detector.detect(frame)
                    tracked = self._tracker.update(frame, detections)
                    for candidate in tracked:
                        accumulator = tracks.get(candidate.track_id)
                        if accumulator is None:
                            accumulator = _TrackAccumulator(
                                object_class=candidate.object_class,
                                start_offset_ms=frame.offset_ms,
                                end_offset_ms=frame.offset_ms,
                            )
                            tracks[candidate.track_id] = accumulator
                        elif accumulator.object_class is not candidate.object_class:
                            raise ValueError("track_object_class_changed")

                        accumulator.end_offset_ms = frame.offset_ms
                        accumulator.confidence_sum += candidate.confidence
                        accumulator.observation_count += 1
                        bbox = candidate.bounding_box
                        accumulator.trajectory.append(
                            TrajectoryPoint(
                                frame.offset_ms,
                                bbox.x + bbox.width / 2.0,
                                bbox.y + bbox.height / 2.0,
                            )
                        )
                        observation = RepresentativeObservation(
                            offset_ms=frame.offset_ms,
                            source_frame_number=frame.source_frame_number,
                            confidence=candidate.confidence,
                            bounding_box=bbox,
                            quality_score=representative_quality(frame, bbox),
                        )
                        if self._is_better_representative(
                            observation,
                            accumulator.representative,
                        ):
                            accumulator.representative = _RepresentativeCandidate(
                                observation=observation,
                                crop=self._crop_rgb(frame, bbox),
                            )
        except SourceIntegrityError:
            self._cleanup_best_effort()
            raise
        except VideoReadError as exc:
            self._cleanup_best_effort()
            raise VideoProcessingError("video_decode_failed") from exc
        except Exception as exc:
            self._cleanup_best_effort()
            raise VideoProcessingError("pipeline_processing_failed") from exc

        try:
            processed_tracks = tuple(
                self._finalize_track(track_id, tracks[track_id])
                for track_id in sorted(tracks)
            )
            return VisionProcessingResult(
                job_id=job_id,
                frames_processed=frames_processed,
                tracks=processed_tracks,
            )
        except Exception as exc:
            self._cleanup_best_effort()
            if isinstance(exc, VideoProcessingError):
                raise
            raise VideoProcessingError("pipeline_processing_failed") from exc

    @staticmethod
    def _is_better_representative(
        candidate: RepresentativeObservation,
        current: _RepresentativeCandidate | None,
    ) -> bool:
        if current is None:
            return True
        existing = current.observation
        candidate_rank = (
            candidate.quality_score,
            candidate.confidence,
            -candidate.offset_ms,
            -candidate.source_frame_number,
        )
        existing_rank = (
            existing.quality_score,
            existing.confidence,
            -existing.offset_ms,
            -existing.source_frame_number,
        )
        return candidate_rank > existing_rank

    @staticmethod
    def _crop_rgb(frame: DecodedFrame, bbox: NormalizedBoundingBox) -> np.ndarray:
        height, width, _ = frame.image.shape
        left = max(0, min(width, int(np.floor(bbox.x * width))))
        top = max(0, min(height, int(np.floor(bbox.y * height))))
        right = max(left, min(width, int(np.ceil((bbox.x + bbox.width) * width))))
        bottom = max(top, min(height, int(np.ceil((bbox.y + bbox.height) * height))))
        crop = frame.image[top:bottom, left:right]
        if crop.size == 0:
            raise ValueError("representative_crop_empty")
        return np.ascontiguousarray(crop.copy(), dtype=np.uint8)

    @staticmethod
    def _jpeg_bytes(crop: np.ndarray) -> bytes:
        buffer = BytesIO()
        Image.fromarray(crop).save(
            buffer,
            format="JPEG",
            quality=90,
            optimize=False,
            progressive=False,
            subsampling=2,
        )
        return buffer.getvalue()

    def _finalize_track(
        self,
        track_id: str,
        accumulator: _TrackAccumulator,
    ) -> ProcessedTrack:
        if accumulator.representative is None or accumulator.observation_count == 0:
            raise ValueError("track_observation_missing")
        self._artifact_store.thumbnail_key(track_id)
        self._artifact_store.trajectory_key(track_id)
        points = tuple(accumulator.trajectory)
        trajectory_payload = serialize_trajectory(points)
        thumbnail_payload = self._jpeg_bytes(accumulator.representative.crop)
        thumbnail = self._artifact_store.write_bytes(
            f"thumbnails/{track_id}.jpg",
            thumbnail_payload,
            "image/jpeg",
        )
        trajectory_artifact = self._artifact_store.write_bytes(
            f"trajectories/{track_id}.msgpack",
            trajectory_payload,
            "application/msgpack",
        )
        return ProcessedTrack(
            track_id=track_id,
            object_class=accumulator.object_class,
            start_offset_ms=accumulator.start_offset_ms,
            end_offset_ms=accumulator.end_offset_ms,
            confidence=accumulator.confidence_sum / accumulator.observation_count,
            representative=accumulator.representative.observation,
            trajectory=points,
            thumbnail=thumbnail,
            trajectory_artifact=trajectory_artifact,
        )

    def _cleanup_best_effort(self) -> None:
        try:
            self._artifact_store.cleanup()
        except Exception:
            pass
