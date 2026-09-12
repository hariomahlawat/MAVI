from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import numpy as np

from mavi_vision.common.analytical import (
    NormalizedBoundingBox,
    ObjectClass,
    ProcessedTrack,
    RepresentativeObservation,
    TrajectoryPoint,
    VisionProcessingResult,
)
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.detection.interfaces import Detector
from mavi_vision.pipeline.finalization import prepare_track
from mavi_vision.runtime.errors import ProcessingDependencyError
from mavi_vision.quality.scoring import representative_quality
from mavi_vision.storage.artifact_publisher import ArtifactPublisher
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.storage.integrity import (
    SourceIntegrityError,
    SourceSnapshotCancelled,
    open_verified_source,
)
from mavi_vision.tracking.interfaces import Tracker
from mavi_vision.video.reader import DecodedFrame, VideoReadError, iter_frames


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
    """Deterministic Task-9 orchestration for exactly one leased job attempt.

    Lease ownership is represented by a shared ``LeaseGuard`` rather than scattered
    boolean cancellation callbacks. CPU-only track preparation is separated from
    filesystem publication, and all artifacts are written through the guarded
    ``ArtifactPublisher`` into this processor's attempt-scoped staging namespace.
    """

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
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
    ) -> VisionProcessingResult:
        if (
            self._artifact_store.job_id != job_id
            or self._artifact_store.attempt_count != attempt_count
        ):
            raise VideoProcessingError("pipeline_configuration_invalid")

        # Startup cleanup is confined to this exact attempt, but it is still a
        # mutation. Never perform it once ownership is known to be lost or expired.
        lease_guard.check_owned()
        try:
            self._artifact_store.cleanup()
        except Exception as exc:
            raise VideoProcessingError("pipeline_configuration_invalid") from exc
        lease_guard.check_owned()

        tracks: dict[str, _TrackAccumulator] = {}
        frames_processed = 0
        try:
            with open_verified_source(
                source_path,
                expected_size_bytes=expected_source_size_bytes,
                expected_sha256=expected_source_sha256,
                cancel_requested=lease_guard.is_lost,
            ) as verified:
                if verified.stream is None:
                    raise SourceIntegrityError("source_read_failed")

                for frame in iter_frames(verified.stream):
                    lease_guard.check_owned()
                    frames_processed += 1

                    detections = self._detector.detect(frame)
                    lease_guard.check_owned()

                    tracked = self._tracker.update(frame, detections)
                    lease_guard.check_owned()

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
        except SourceSnapshotCancelled as exc:
            # Snapshot cancellation is the source-integrity layer's cooperative
            # representation of lease loss. Normalize it to the ownership exception.
            raise LeaseLostError() from exc
        except LeaseLostError:
            raise
        except SourceIntegrityError:
            self._cleanup_best_effort(lease_guard)
            raise
        except ProcessingDependencyError:
            try:
                self._cleanup_best_effort(lease_guard)
            except LeaseLostError:
                # Runtime health is independent of lease authority. Never mutate
                # staging after ownership loss, but preserve the dependency signal
                # so the local supervisor can classify/recover the runtime.
                pass
            raise
        except VideoReadError as exc:
            self._cleanup_best_effort(lease_guard)
            raise VideoProcessingError("video_decode_failed") from exc
        except VideoProcessingError:
            self._cleanup_best_effort(lease_guard)
            raise
        except Exception as exc:
            self._cleanup_best_effort(lease_guard)
            raise VideoProcessingError("pipeline_processing_failed") from exc

        publisher = ArtifactPublisher(self._artifact_store, lease_guard)
        try:
            processed_tracks: list[ProcessedTrack] = []
            for track_id in sorted(tracks):
                lease_guard.check_owned()
                accumulator = tracks[track_id]
                representative = accumulator.representative

                # Preparation is pure CPU work. If ownership expires during encoding
                # or serialization, the following guard prevents publication. The
                # low-level store then checks the same guard again immediately before
                # each atomic destination replacement.
                prepared = prepare_track(
                    track_id=track_id,
                    object_class=accumulator.object_class,
                    start_offset_ms=accumulator.start_offset_ms,
                    end_offset_ms=accumulator.end_offset_ms,
                    confidence_sum=accumulator.confidence_sum,
                    observation_count=accumulator.observation_count,
                    representative=(
                        None if representative is None else representative.observation
                    ),
                    representative_crop=(
                        None if representative is None else representative.crop
                    ),
                    trajectory=tuple(accumulator.trajectory),
                )
                lease_guard.check_owned()
                processed_tracks.append(publisher.publish_track(prepared))
                lease_guard.check_owned()

            lease_guard.check_owned()
            return VisionProcessingResult(
                job_id=job_id,
                frames_processed=frames_processed,
                tracks=tuple(processed_tracks),
            )
        except LeaseLostError:
            # Never cleanup after ownership loss. This attempt is structurally
            # isolated from replacements, and leaving its private subtree is safer
            # than mutating shared filesystem state as a stale worker.
            raise
        except ProcessingDependencyError:
            try:
                self._cleanup_best_effort(lease_guard)
            except LeaseLostError:
                # Preserve local runtime-health classification while refusing stale
                # cleanup. WorkerRunner still applies lease precedence before any
                # terminal control-plane mutation.
                pass
            raise
        except VideoProcessingError:
            self._cleanup_best_effort(lease_guard)
            raise
        except Exception as exc:
            self._cleanup_best_effort(lease_guard)
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

    def _cleanup_best_effort(self, lease_guard: LeaseGuard) -> None:
        # Lease loss takes precedence over any concurrent processing error. The guard
        # is checked immediately at the mutation boundary so a stale worker never
        # cleans even its own attempt after authority has been lost.
        lease_guard.check_owned()
        try:
            self._artifact_store.cleanup()
        except Exception:
            pass
