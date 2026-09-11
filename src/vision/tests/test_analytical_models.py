from __future__ import annotations

from uuid import UUID

import pytest

from mavi_vision.common.analytical import (
    ArtifactDescriptor,
    NormalizedBoundingBox,
    ObjectClass,
    ProcessedTrack,
    RepresentativeObservation,
    TrajectoryPoint,
    VisionProcessingResult,
)


def _artifact(storage_key: str, sha_char: str = "a") -> ArtifactDescriptor:
    return ArtifactDescriptor(
        storage_key=storage_key,
        media_type="application/octet-stream",
        size_bytes=10,
        sha256=sha_char * 64,
    )


def _representative() -> RepresentativeObservation:
    return RepresentativeObservation(
        offset_ms=500,
        source_frame_number=12,
        confidence=0.9,
        bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.4),
        quality_score=0.8,
    )


def test_normalized_bbox_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        NormalizedBoundingBox(x=-0.01, y=0.0, width=0.2, height=0.2)

    with pytest.raises(ValueError):
        NormalizedBoundingBox(x=0.9, y=0.0, width=0.2, height=0.2)


def test_processing_result_is_track_oriented() -> None:
    track = ProcessedTrack(
        track_id="fixture-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=1000,
        confidence=0.9,
        representative=_representative(),
        trajectory=(
            TrajectoryPoint(0, 0.2, 0.3),
            TrajectoryPoint(1000, 0.4, 0.3),
        ),
        thumbnail=_artifact("staging/job/thumbnails/fixture-0001.jpg"),
        trajectory_artifact=_artifact(
            "staging/job/trajectories/fixture-0001.msgpack", "b"
        ),
    )

    result = VisionProcessingResult(
        job_id=UUID(int=1), frames_processed=25, tracks=(track,)
    )

    assert result.tracks == (track,)


def test_trajectory_offsets_must_be_monotonic() -> None:
    with pytest.raises(ValueError, match="trajectory_offsets_not_monotonic"):
        ProcessedTrack(
            track_id="fixture-0001",
            object_class=ObjectClass.PERSON,
            start_offset_ms=0,
            end_offset_ms=1000,
            confidence=0.9,
            representative=_representative(),
            trajectory=(
                TrajectoryPoint(1000, 0.4, 0.3),
                TrajectoryPoint(500, 0.2, 0.3),
            ),
            thumbnail=_artifact("staging/job/thumbnails/fixture-0001.jpg"),
            trajectory_artifact=_artifact(
                "staging/job/trajectories/fixture-0001.msgpack", "b"
            ),
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
        RepresentativeObservation(
            offset_ms=0,
            source_frame_number=-1,
            confidence=0.5,
            bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.2),
            quality_score=0.5,
        )
    with pytest.raises(ValueError):
        ArtifactDescriptor(
            storage_key="staging/job/path.jpg",
            media_type="image/jpeg",
            size_bytes=-1,
            sha256="a" * 64,
        )
