from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from mavi_vision.common.analytical import (
    MAXIMUM_TRACKS_PER_RESULT,
    ObjectClass,
    ProcessedTrack,
    VisionProcessingResult,
)
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.detection.interfaces import DetectionCandidate, Detector
from mavi_vision.evidence.admission import admit
from mavi_vision.evidence.encoder import EvidenceEncoder, JpegLadderEncoder
from mavi_vision.evidence.policy import EvidencePolicy
from mavi_vision.evidence.quality import FrameContext, QualityScorer, scorer_for_policy
from mavi_vision.evidence.selector import EvidenceSelector
from mavi_vision.pipeline.finalization import prepare_track
from mavi_vision.runtime.errors import ProcessingDependencyError, TrackerError
from mavi_vision.runtime.progress import ProcessingProgressSink
from mavi_vision.storage.artifact_publisher import ArtifactPublisher
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.storage.integrity import (
    SourceIntegrityError,
    SourceSnapshotCancelled,
    open_verified_source,
)
from mavi_vision.tracking.interfaces import TrackCandidate, Tracker, TrackerUpdate
from mavi_vision.video.reader import DecodedFrame, VideoReadError, iter_frames
from mavi_vision.video.trajectory_spool import DEFAULT_CHUNK_POINTS, TrajectorySpool


class VideoProcessingError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(slots=True)
class _TrackAccumulator:
    """Live state of one Track; discarded when the Track is finalised.

    Everything here is bounded independently of the Track's duration: scalars,
    an evidence selector holding at most one encoded JPEG per role (never raw
    pixels), and a trajectory spool that holds at most one chunk of points in
    memory (the rest is spilled to attempt-scoped staging).
    """

    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    trajectory: TrajectorySpool
    evidence: EvidenceSelector
    confidence_sum: float = 0.0
    max_confidence: float = 0.0
    observation_count: int = 0


class VideoProcessor:
    """Deterministic, model-independent processing for one leased job attempt.

    Track lifecycle (ADR-013 §5). A Track is *live* from its first tracker
    candidate and is finalised exactly once: when the tracker reports it retired,
    or at end-of-stream if it is still live then. Finalisation prepares and stages
    the whole Track -- trajectory, summary and Representative -- and replaces the
    live accumulator with a descriptor-only ``ProcessedTrack``, so live memory is
    bounded by the Tracks currently live rather than by every Track seen. Within
    a live Track, the trajectory is held in a ``TrajectorySpool``, so a Track's
    memory does not grow with its duration either.

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
        *,
        evidence_policy: EvidencePolicy,
        evidence_scorer: QualityScorer | None = None,
        evidence_encoder: EvidenceEncoder | None = None,
        evidence_quota_bytes: int | None = None,
        trajectory_chunk_points: int = DEFAULT_CHUNK_POINTS,
        frame_reader: Callable[[BinaryIO], Iterable[DecodedFrame]] = iter_frames,
    ) -> None:
        self._detector = detector
        self._tracker = tracker
        self._artifact_store = artifact_store
        self._evidence_policy = evidence_policy
        # The scorer and encoder are chosen by the profile's versions; the
        # arguments are replacement seams (a future scorer, a test stub).
        self._evidence_scorer = evidence_scorer or scorer_for_policy(evidence_policy)
        self._evidence_encoder = evidence_encoder or JpegLadderEncoder(evidence_policy.encoder)
        # Test seams, deliberately not operator configuration: the quota is the
        # profile's ADR-013 bound in production, and the chunk size changes
        # memory and I/O cadence, never the bytes produced.
        self._evidence_quota_bytes = (
            evidence_policy.run_evidence_crop_quota_bytes
            if evidence_quota_bytes is None
            else evidence_quota_bytes
        )
        self._trajectory_chunk_points = trajectory_chunk_points
        # Qualification seam (S1.4 plan §6.2), not operator configuration:
        # decodes the verified source stream into frames. Production always
        # uses ``iter_frames``; the B2 memory harness substitutes a declared
        # synthetic frame source so a long, lossless, high-entropy workload
        # runs through the real tracker, selector, encoder, staging and
        # finalisation without a multi-gigabyte video file.
        self._frame_reader = frame_reader

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

                for frame in self._frame_reader(verified.stream):
                    lease_guard.check_owned()

                    detections = self._detector.detect(frame)
                    lease_guard.check_owned()

                    update = self._tracker.update(frame, detections)
                    if not isinstance(update, TrackerUpdate):
                        raise TrackerError("tracker_update_invalid")
                    lease_guard.check_owned()

                    # Every detection the tracker was given, both classes: the
                    # evidence occlusion proxy needs all concurrent boxes.
                    context = FrameContext(frame, _detections_tuple(detections))
                    for candidate in update.candidates:
                        if candidate.track_id in finalised:
                            raise TrackerError(
                                "tracker_track_reappeared_after_retirement"
                            )
                        if (
                            candidate.track_id not in live
                            and len(live) + len(finalised) >= MAXIMUM_TRACKS_PER_RESULT
                        ):
                            # Fail before staging anything for a Track the
                            # completion could never carry (bounds staging disk).
                            raise ValueError("track_limit_exceeded")
                        self._accumulate(live, context, candidate)

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

            # Run-level admission needs every candidate of the run, so it
            # happens once, after the drain (ADR-013 §6). Omitted supplemental
            # crops are removed from staging before completion; admitted ones
            # keep contiguous ranks.
            lease_guard.check_owned()
            admission = admit(tuple(finalised.values()), self._evidence_quota_bytes)
            publisher.remove_omitted(
                tuple((item.track_id, item.observation) for item in admission.omitted)
            )

            lease_guard.check_owned()
            if progress_sink is not None:
                progress_sink.mark_finalization_ready()
            # Admission returns Tracks in canonical Track-id order.
            return VisionProcessingResult(
                job_id=job_id,
                frames_processed=frames_processed,
                tracks=admission.tracks,
                evidence_accounting=admission.accounting,
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
        context: FrameContext,
        candidate: TrackCandidate,
    ) -> None:
        frame = context.frame
        accumulator = live.get(candidate.track_id)
        if accumulator is None:
            accumulator = _TrackAccumulator(
                object_class=candidate.object_class,
                start_offset_ms=frame.offset_ms,
                end_offset_ms=frame.offset_ms,
                trajectory=TrajectorySpool(
                    self._artifact_store,
                    candidate.track_id,
                    chunk_points=self._trajectory_chunk_points,
                ),
                evidence=EvidenceSelector(
                    policy=self._evidence_policy,
                    scorer=self._evidence_scorer,
                    encoder=self._evidence_encoder,
                    track_start_ms=frame.offset_ms,
                ),
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
            frame.offset_ms,
            bbox.x + bbox.width / 2.0,
            bbox.y + bbox.height / 2.0,
        )
        accumulator.evidence.observe(context, candidate)

    @staticmethod
    def _finalise_track(
        track_id: str,
        accumulator: _TrackAccumulator,
        publisher: ArtifactPublisher,
        lease_guard: LeaseGuard,
    ) -> ProcessedTrack:
        """Prepare and stage one complete Track: the only finalisation path."""
        lease_guard.check_owned()
        prepared = prepare_track(
            track_id=track_id,
            object_class=accumulator.object_class,
            start_offset_ms=accumulator.start_offset_ms,
            end_offset_ms=accumulator.end_offset_ms,
            confidence_sum=accumulator.confidence_sum,
            max_confidence=accumulator.max_confidence,
            observation_count=accumulator.observation_count,
            evidence=accumulator.evidence.resolve(),
            trajectory=accumulator.trajectory.summary(),
        )
        lease_guard.check_owned()
        # The spool streams its canonical v1 payload into the publication and is
        # removed only after that publication succeeded. Finalisations run one at
        # a time, so at most one Track's spool, temp file and published artefact
        # coexist on disk (about 3 x 24 bytes per point, transiently).
        processed = accumulator.trajectory.finalise(
            lambda chunks: publisher.publish_track(prepared, chunks)
        )
        lease_guard.check_owned()
        return processed

    def _cleanup_best_effort(self, lease_guard: LeaseGuard) -> None:
        lease_guard.check_owned()
        try:
            self._artifact_store.cleanup()
        except Exception:
            pass


def _detections_tuple(detections: object) -> tuple[DetectionCandidate, ...]:
    """The frame's detections as an immutable tuple of the detector contract type."""
    values = tuple(detections)  # type: ignore[arg-type]
    if not all(isinstance(detection, DetectionCandidate) for detection in values):
        raise ValueError("detector_output_invalid")
    return values
