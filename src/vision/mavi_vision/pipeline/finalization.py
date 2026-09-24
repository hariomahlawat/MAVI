from __future__ import annotations

from dataclasses import dataclass
import sys

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole, role_cap_bytes
from mavi_vision.evidence.selector import ResolvedEvidence
from mavi_vision.video.trajectory_spool import TrajectorySummary


@dataclass(frozen=True, slots=True)
class PreparedTrack:
    """Filesystem-independent, deterministic representation of a finalized track.

    It carries the trajectory's summary, not its points: the canonical v1 payload
    is streamed from the Track's spool straight into staging at publication. The
    resolved Evidence Set holds the Track's (at most four) encoded crops; they
    are written once at publication and are not kept afterwards.
    """

    track_id: str
    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    detection_count: int
    mean_confidence: float
    max_confidence: float
    evidence: tuple[ResolvedEvidence, ...]
    trajectory: TrajectorySummary

    @property
    def confidence(self) -> float:
        """Backward-compatible read alias for historical tests/callers."""
        return self.mean_confidence


def prepare_track(
    *,
    track_id: str,
    object_class: ObjectClass,
    start_offset_ms: int,
    end_offset_ms: int,
    confidence_sum: float,
    max_confidence: float,
    observation_count: int,
    evidence: tuple[ResolvedEvidence, ...],
    trajectory: TrajectorySummary,
) -> PreparedTrack:
    """Prepare deterministic track payloads without performing external side effects.

    The trajectory's points never reach this function. Strict monotonicity is
    enforced as each point enters the spool and again while its v1 payload is
    streamed; here the summary must agree with the Track's scalars: one point
    per observation, all inside the Track's offsets. The resulting
    ``ProcessedTrack`` keeps only the staged descriptor.
    """

    if observation_count <= 0:
        raise ValueError("track_observation_missing")

    if trajectory.point_count <= 0 or trajectory.point_count != observation_count:
        raise ValueError("track_observation_missing")
    # Strictly increasing offsets span a positive interval exactly when there is
    # more than one point.
    single_point = trajectory.point_count == 1
    if (
        trajectory.first_offset_ms > trajectory.last_offset_ms
        or (trajectory.first_offset_ms == trajectory.last_offset_ms) != single_point
    ):
        raise ValueError("trajectory_offsets_not_monotonic")
    if (
        trajectory.first_offset_ms < start_offset_ms
        or trajectory.last_offset_ms > end_offset_ms
    ):
        raise ValueError("trajectory_offsets_outside_track")

    mean_confidence = confidence_sum / observation_count
    # Every observation is bounded by the observed maximum, so the true mean
    # cannot exceed it. The running `+=` sum can still round a mean above it: 250
    # additions of 0.9 give 0.9000000000000038. Recursive summation of n terms errs
    # by at most about (n - 1) * u * sum (u = 2**-53), so the mean errs by at most
    # about n * u * max. The tolerance below is twice that bound: it scales with
    # the track's length, so long constant-confidence tracks still finalize, and it
    # is far narrower than any real inconsistency. Only an excess inside it is
    # rounding and is normalized to the maximum. Anything larger, and any NaN,
    # infinity or out-of-range value, still fails the check that follows.
    excess = mean_confidence - max_confidence
    if 0.0 < excess <= observation_count * max_confidence * sys.float_info.epsilon:
        mean_confidence = max_confidence
    if not 0.0 <= mean_confidence <= max_confidence <= 1.0:
        raise ValueError("track_confidence_invalid")


    _validate_evidence(evidence, start_offset_ms, end_offset_ms, max_confidence)

    return PreparedTrack(
        track_id=track_id,
        object_class=object_class,
        start_offset_ms=start_offset_ms,
        end_offset_ms=end_offset_ms,
        detection_count=observation_count,
        mean_confidence=mean_confidence,
        max_confidence=max_confidence,
        evidence=evidence,
        trajectory=trajectory,
    )


def _validate_evidence(
    evidence: tuple[ResolvedEvidence, ...],
    start_offset_ms: int,
    end_offset_ms: int,
    max_confidence: float,
) -> None:
    """The resolved Evidence Set must be canonical before anything is staged."""
    if not evidence:
        # No admissible candidate at all (qualified or fallback) was seen for this Track.
        raise EvidenceError("evidence_representative_missing")
    if len(evidence) > len(ROLE_ORDER) or evidence[0].role is not EvidenceRole.REPRESENTATIVE:
        raise EvidenceError("evidence_set_invalid")
    previous = -1
    frames: set[int] = set()
    for rank, item in enumerate(evidence):
        role_index = ROLE_ORDER.index(item.role)
        held = item.evidence
        if (
            item.rank != rank
            or role_index <= previous
            or held.source_frame_number in frames
            or not start_offset_ms <= held.offset_ms <= end_offset_ms
            or held.confidence > max_confidence
            or not 0 < held.image.size_bytes <= role_cap_bytes(item.role)
        ):
            raise EvidenceError("evidence_set_invalid")
        previous = role_index
        frames.add(held.source_frame_number)
