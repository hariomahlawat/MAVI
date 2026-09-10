from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from mavi_vision.common.analytical import (
    NormalizedBoundingBox,
    ObjectClass,
    RepresentativeObservation,
    TrajectoryPoint,
)
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.pipeline.finalization import PreparedTrack
from mavi_vision.storage.artifact_publisher import ArtifactPublisher
from mavi_vision.storage.artifact_store import StagingArtifactStore


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")


def _future_guard() -> LeaseGuard:
    return LeaseGuard(datetime.now(timezone.utc) + timedelta(minutes=5))


def _prepared_track() -> PreparedTrack:
    representative = RepresentativeObservation(
        offset_ms=0,
        source_frame_number=0,
        confidence=0.9,
        bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.4, 0.5),
        quality_score=0.8,
    )
    trajectory = (TrajectoryPoint(0, 0.3, 0.4),)
    return PreparedTrack(
        track_id="person-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=0,
        confidence=0.9,
        representative=representative,
        trajectory=trajectory,
        thumbnail_payload=b"jpeg-payload",
        trajectory_payload=b"trajectory-payload",
    )


def _attempt_root(root: Path, attempt: int = 1) -> Path:
    return root / "staging" / str(JOB_ID) / f"attempt-{attempt:04d}"


def test_loss_before_first_publish_creates_no_artifacts(tmp_path: Path) -> None:
    guard = _future_guard()
    guard.mark_lost()
    publisher = ArtifactPublisher(
        StagingArtifactStore(tmp_path, JOB_ID, 1),
        guard,
    )

    with pytest.raises(LeaseLostError, match="lease_lost"):
        publisher.publish_track(_prepared_track())

    assert not _attempt_root(tmp_path).exists()


def test_loss_between_artifact_publications_stops_second_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _future_guard()
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    publisher = ArtifactPublisher(store, guard)
    real_write = store.write_bytes
    writes = 0

    def write_then_lose_lease(relative_name, content, media_type, *, authorize_publish=None):
        nonlocal writes
        descriptor = real_write(
            relative_name,
            content,
            media_type,
            authorize_publish=authorize_publish,
        )
        writes += 1
        if writes == 1:
            guard.mark_lost()
        return descriptor

    monkeypatch.setattr(store, "write_bytes", write_then_lose_lease)

    with pytest.raises(LeaseLostError, match="lease_lost"):
        publisher.publish_track(_prepared_track())

    thumbnail = _attempt_root(tmp_path) / "thumbnails" / "person-0001.jpg"
    trajectory = _attempt_root(tmp_path) / "trajectories" / "person-0001.msgpack"
    assert thumbnail.read_bytes() == b"jpeg-payload"
    assert not trajectory.exists()


def test_successful_publication_returns_processed_track_with_attempt_keys(tmp_path: Path) -> None:
    publisher = ArtifactPublisher(
        StagingArtifactStore(tmp_path, JOB_ID, 2),
        _future_guard(),
    )

    track = publisher.publish_track(_prepared_track())

    assert track.track_id == "person-0001"
    assert "/attempt-0002/thumbnails/" in track.thumbnail.storage_key
    assert "/attempt-0002/trajectories/" in track.trajectory_artifact.storage_key
