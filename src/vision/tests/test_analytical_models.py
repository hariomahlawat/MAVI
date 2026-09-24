from __future__ import annotations

from uuid import UUID

import pytest

from mavi_vision.common.analytical import (
    ArtifactDescriptor,
    NormalizedBoundingBox,
    ObjectClass,
    EvidenceAccounting,
    ObservationDescriptor,
    ProcessedTrack,
    RoleAccounting,
    TrajectoryPoint,
    VisionProcessingResult,
)
from mavi_vision.evidence.roles import EvidenceRole


def _artifact(storage_key: str, sha_char: str = "a") -> ArtifactDescriptor:
    return ArtifactDescriptor(
        storage_key=storage_key,
        media_type="application/octet-stream",
        size_bytes=10,
        sha256=sha_char * 64,
    )


def _observation(
    role: EvidenceRole = EvidenceRole.REPRESENTATIVE,
    rank: int = 0,
    *,
    frame: int = 12,
    offset: int = 500,
    confidence: float = 0.9,
    size: int = 1000,
) -> ObservationDescriptor:
    return ObservationDescriptor(
        role=role,
        rank=rank,
        offset_ms=offset,
        source_frame_number=frame,
        confidence=confidence,
        bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.4),
        quality_micro=800_000,
        selection_micro=800_000,
        crop=ArtifactDescriptor(
            storage_key=f"staging/job/evidence/fixture-0001-{role.value}.jpg",
            media_type="image/jpeg",
            size_bytes=size,
            sha256="c" * 64,
        ),
    )


def _track(*, mean: float = 0.85, maximum: float = 0.9, observations=None) -> ProcessedTrack:
    return ProcessedTrack(
        track_id="fixture-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=1000,
        detection_count=2,
        mean_confidence=mean,
        max_confidence=maximum,
        observations=observations if observations is not None else (_observation(),),
        trajectory_artifact=_artifact(
            "staging/job/trajectories/fixture-0001.msgpack", "b"
        ),
    )


def test_normalized_bbox_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        NormalizedBoundingBox(x=-0.01, y=0.0, width=0.2, height=0.2)

    with pytest.raises(ValueError):
        NormalizedBoundingBox(x=0.9, y=0.0, width=0.2, height=0.2)


def test_processing_result_is_track_oriented_and_has_complete_confidence_facts() -> None:
    track = _track()

    result = VisionProcessingResult(
        job_id=UUID(int=1),
        frames_processed=25,
        tracks=(track,),
        evidence_accounting=EvidenceAccounting(representative=RoleAccounting(1, 1, 0, 1000, 1000)),
    )

    assert result.tracks == (track,)
    assert track.detection_count == 2
    assert track.mean_confidence == pytest.approx(0.85)
    assert track.max_confidence == pytest.approx(0.9)
    assert track.confidence == track.mean_confidence


def test_track_rejects_invalid_confidence_order() -> None:
    with pytest.raises(ValueError, match="track_confidence_order_invalid"):
        _track(mean=0.95, maximum=0.9)


def test_processed_track_is_descriptor_only() -> None:
    """A finalised Track keeps no trajectory points or payloads.

    Tracks are finalised when they retire and are held until completion; a point
    list here would make completion memory grow with every detection. Trajectory
    invariants are enforced by ``prepare_track`` instead.
    """
    fields = set(ProcessedTrack.__dataclass_fields__)

    assert "trajectory" not in fields
    assert not any("payload" in name or "image" in name for name in fields)
    assert {"observations", "trajectory_artifact"} <= fields
    assert not any(
        "payload" in name or "image" in name for name in ObservationDescriptor.__dataclass_fields__
    )


def test_artifact_descriptor_rejects_noncanonical_storage_key_and_sha() -> None:
    with pytest.raises(ValueError, match="artifact_storage_key_invalid"):
        ArtifactDescriptor(
            storage_key="/absolute/path.jpg",
            media_type="image/jpeg",
            size_bytes=1,
            sha256="a" * 64,
        )

    with pytest.raises(ValueError, match="artifact_sha256_invalid"):
        ArtifactDescriptor(
            storage_key="staging/job/path.jpg",
            media_type="image/jpeg",
            size_bytes=1,
            sha256="A" * 64,
        )


def test_offsets_scores_and_sizes_are_bounded() -> None:
    with pytest.raises(ValueError):
        TrajectoryPoint(-1, 0.2, 0.3)
    with pytest.raises(ValueError):
        _observation(frame=-1)
    with pytest.raises(ValueError):
        ArtifactDescriptor(
            storage_key="staging/job/path.jpg",
            media_type="image/jpeg",
            size_bytes=-1,
            sha256="a" * 64,
        )


def test_track_observations_must_be_canonical() -> None:
    near = _observation(EvidenceRole.NEAR_VIEW, 1, frame=13, offset=600)
    late = _observation(EvidenceRole.LATE_DIVERSE, 2, frame=20, offset=900)
    assert _track(observations=(_observation(), near, late)).representative.role is EvidenceRole.REPRESENTATIVE

    for bad, code in (
        ((), "track_observations_invalid"),
        ((near,), "observation_rank_invalid"),
        ((_observation(), _observation(EvidenceRole.LATE_DIVERSE, 1, frame=20), _observation(EvidenceRole.NEAR_VIEW, 2, frame=13)), "track_observation_order_invalid"),
        ((_observation(), _observation(EvidenceRole.NEAR_VIEW, 2, frame=13)), "track_observation_rank_invalid"),
        ((_observation(), _observation(EvidenceRole.NEAR_VIEW, 1, frame=12)), "track_observation_frame_duplicate"),
        ((_observation(), _observation(EvidenceRole.NEAR_VIEW, 1, frame=13, offset=1001)), "observation_outside_track"),
        ((_observation(confidence=0.95),), "observation_confidence_exceeds_track_max"),
    ):
        with pytest.raises(ValueError, match=code):
            _track(observations=bad)


def test_observation_crop_is_bounded_by_its_role_cap() -> None:
    with pytest.raises(ValueError, match="observation_crop_size_invalid"):
        _observation(size=65537)
    assert _observation(EvidenceRole.NEAR_VIEW, 1, size=163840).crop.size_bytes == 163840
    with pytest.raises(ValueError, match="observation_crop_size_invalid"):
        _observation(EvidenceRole.NEAR_VIEW, 1, size=163841)


def test_result_accounting_must_describe_the_observations_present() -> None:
    track = _track()
    with pytest.raises(ValueError, match="evidence_accounting_mismatch"):
        VisionProcessingResult(UUID(int=1), 25, (track,))
    with pytest.raises(ValueError, match="evidence_accounting_mismatch"):
        VisionProcessingResult(
            UUID(int=1),
            25,
            (track,),
            EvidenceAccounting(representative=RoleAccounting(1, 1, 0, 1000, 999)),
        )
    with pytest.raises(ValueError, match="evidence_accounting_invalid"):
        RoleAccounting(2, 1, 0, 10, 5)  # omitted must equal candidates - admitted
