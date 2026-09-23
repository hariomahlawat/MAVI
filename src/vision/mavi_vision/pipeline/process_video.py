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
from mavi_vision.runtime.errors import ProcessingDependencyError, TrackerError
from mavi_vision.runtime.progress import ProcessingProgressSink
from mavi_vision.quality.scoring import representative_quality
from mavi_vision.storage.artifact_publisher import ArtifactPublisher
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.storage.integrity import (
    SourceIntegrityError,
    SourceSnapshotCancelled,
    open_verified_source,
)
from mavi_vision.tracking.interfaces import TrackCandidate, Tracker, TrackerUpdate
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
    """Live state of one Track; discarded when the Track is finalised."""

    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    confidence_sum: float = 0.0
    max_confidence: float = 0.0
    observation_count: int = 0
    trajectory: list[TrajectoryPoint] = field(default_factory=list)
    representative: _RepresentativeCandidate | None = None


class VideoProcessor:
    """Deterministic, model-independent processing for one leased job attempt.

    Track lifecycle (ADR-013 §5). A Track is *live* from its first tracker
    candidate and is finalised exactly once: when the tracker reports it retired,
    or at end-of-stream if it is still live then. Finalisation prepares and stages
    the whole Track -- trajectory, summary and Representative -- and replaces the
    live accumulator with a descriptor-only ``ProcessedTrack``, so live memory is
    bounded by the Tracks currently live rather than by every Track seen.

    The processor never infers retirement itself; a temporarily unmatched Track
    stays live until the tracker, which alone knows its backend's association
    budget, retires it. The processor re-checks the cross-update half of the
    tracker contract: a candidate for an already finalised Track, or the
    retirement of a Track that is not live, fails the attempt.

    An attempt that fails, is cancelled or loses its lease produces no result.
    Tracks finalised earlier in that attempt exist only as attempt-scoped staging,
    which is removed on failure, or by the next attempt after a lease loss.
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
        progress_sink: ProcessingProgressSink | None = None,
    ) -> VisionProcessingResult:
        if (
            self._artifact_store.job_id != job_id
            or self._artifact_store.attempt_count != attempt_count
        ):
            raise VideoProcessingError("pipeline_configuration_invalid")

        lease_guard.check_owned()
        try:
            self._artifact_store.cleanup()
            lease_guard.check_owned()
            # Earlier attempts of this job are fenced out by the platform: this
            # lease carries a higher attempt number, so nothing they staged can
            # ever be accepted. Remove it before this attempt stages anything.
            self._artifact_store.cleanup_superseded_attempts()
        except LeaseLostError:
            raise
        except Exception as exc:
            raise VideoProcessingError("pipeline_configuration_invalid") from exc
        lease_guard.check_owned()

        publisher = ArtifactPublisher(self._artifact_store, lease_guard)
        live: dict[str, _TrackAccumulator] = {}
        finalised: dict[str, ProcessedTrack] = {}
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

                if progress_sink is not None:
                    progress_sink.mark_processing_started()

                for frame in iter_frames(verified.stream):
                    lease_guard.check_owned()

                    detections = self._detector.detect(frame)
                    lease_guard.check_owned()

                    update = self._tracker.update(frame, detections)
                    if not isinstance(update, TrackerUpdate):
                        raise TrackerError("tracker_update_invalid")
                    lease_guard.check_owned()

                    for candidate in update.candidates:
                        if candidate.track_id in finalised:
                            raise TrackerError(
                                "tracker_track_reappeared_after_retirement"
                            )
                        self._accumulate(live, frame, candidate)

                    # Retirement is final: the tracker guarantees these ids can
                    # never be emitted again, so each whole Track is staged now
                    # and its live state released. The accumulator is passed
                    # straight from the live map so no binding outlives it.
                    for track_id in update.retired_track_ids:
                        if track_id not in live:
                            raise TrackerError("tracker_retired_unknown_track")
                        finalised[track_id] = self._finalise_track(
                            track_id,
                            live.pop(track_id),
                            publisher,
                            lease_guard,
                        )

                    # Re-check lease authority at the exact successful-frame
                    # commit boundary. A frame completed after lease expiry must
                    # never advance observable attempt progress.
                    lease_guard.check_owned()

                    # A frame becomes observable forward progress only after its
                    # detector, tracker, and analytical accumulator work succeeds.
                    frames_processed += 1
                    if progress_sink is not None:
                        progress_sink.mark_frame_completed(
                            source_offset_ms=frame.offset_ms,
                        )
        except SourceSnapshotCancelled as exc:
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

        lease_guard.check_owned()
        if progress_sink is not None:
            progress_sink.mark_finalization_started()

        try:
            # End-of-stream is a lifecycle boundary of its own: every Track still
            # live is complete now and is finalised exactly once, in canonical
            # Track-id order.
            for track_id in sorted(live):
                finalised[track_id] = self._finalise_track(
                    track_id,
                    live.pop(track_id),
                    publisher,
                    lease_guard,
                )

            lease_guard.check_owned()
            if progress_sink is not None:
                progress_sink.mark_finalization_ready()
            # Tracks were finalised in retirement order; the result is canonical.
            return VisionProcessingResult(
                job_id=job_id,
                frames_processed=frames_processed,
                tracks=tuple(finalised[track_id] for track_id in sorted(finalised)),
            )
        except LeaseLostError:
            raise
        except ProcessingDependencyError:
            try:
                self._cleanup_best_effort(lease_guard)
            except LeaseLostError:
                pass
            raise
        except VideoProcessingError:
            self._cleanup_best_effort(lease_guard)
            raise
        except Exception as exc:
            self._cleanup_best_effort(lease_guard)
            raise VideoProcessingError("pipeline_processing_failed") from exc

    def _accumulate(
        self,
        live: dict[str, _TrackAccumulator],
        frame: DecodedFrame,
        candidate: TrackCandidate,
    ) -> None:
        accumulator = live.get(candidate.track_id)
        if accumulator is None:
            accumulator = _TrackAccumulator(
                object_class=candidate.object_class,
                start_offset_ms=frame.offset_ms,
                end_offset_ms=frame.offset_ms,
            )
            live[candidate.track_id] = accumulator
        elif accumulator.object_class is not candidate.object_class:
            raise ValueError("track_object_class_changed")

        accumulator.end_offset_ms = frame.offset_ms
        accumulator.confidence_sum += candidate.confidence
        accumulator.max_confidence = max(
            accumulator.max_confidence,
            candidate.confidence,
        )
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

    @staticmethod
    def _finalise_track(
        track_id: str,
        accumulator: _TrackAccumulator,
        publisher: ArtifactPublisher,
        lease_guard: LeaseGuard,
    ) -> ProcessedTrack:
        """Prepare and stage one complete Track: the only finalisation path."""
        lease_guard.check_owned()
        representative = accumulator.representative
        prepared = prepare_track(
            track_id=track_id,
            object_class=accumulator.object_class,
            start_offset_ms=accumulator.start_offset_ms,
            end_offset_ms=accumulator.end_offset_ms,
            confidence_sum=accumulator.confidence_sum,
            max_confidence=accumulator.max_confidence,
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
        processed = publisher.publish_track(prepared)
        lease_guard.check_owned()
        return processed

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
        lease_guard.check_owned()
        try:
            self._artifact_store.cleanup()
        except Exception:
            pass
