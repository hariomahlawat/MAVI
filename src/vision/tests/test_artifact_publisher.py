from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.evidence.roles import EvidenceRole
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.pipeline.finalization import PreparedTrack
from mavi_vision.storage.artifact_publisher import ArtifactPublisher
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.video.trajectory_spool import TrajectorySummary
from tests.evidence_fixtures import resolved


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")


def _future_guard() -> LeaseGuard:
    return LeaseGuard(datetime.now(timezone.utc) + timedelta(minutes=5))


EVIDENCE = resolved(
    (EvidenceRole.REPRESENTATIVE, 0, 0),
    (EvidenceRole.NEAR_VIEW, 1, 40),
    (EvidenceRole.LATE_DIVERSE, 2, 80),
)


def _prepared_track() -> PreparedTrack:
    return PreparedTrack(
        track_id="person-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=80,
        detection_count=3,
        mean_confidence=0.9,
        max_confidence=0.9,
        evidence=EVIDENCE,
        trajectory=TrajectorySummary(3, 0, 80),
    )


def _crop(root: Path, role: str, attempt: int = 1) -> Path:
    return _attempt_root(root, attempt) / "evidence" / f"person-0001-{role}.jpg"


TRAJECTORY_CHUNKS = (b"trajectory-", b"payload")


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
        publisher.publish_track(_prepared_track(), TRAJECTORY_CHUNKS)

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
        publisher.publish_track(_prepared_track(), TRAJECTORY_CHUNKS)

    # The trajectory and the first crop were published; nothing after the loss.
    trajectory = _attempt_root(tmp_path) / "trajectories" / "person-0001.msgpack"
    assert trajectory.read_bytes() == b"trajectory-payload"
    assert _crop(tmp_path, "representative").read_bytes() == EVIDENCE[0].evidence.image.payload
    assert not _crop(tmp_path, "near-view").exists()
    assert not _crop(tmp_path, "late-diverse").exists()


def test_low_level_authorization_blocks_destination_before_atomic_replace(tmp_path: Path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    checks = 0

    def deny_publish() -> None:
        nonlocal checks
        checks += 1
        raise LeaseLostError()

    with pytest.raises(LeaseLostError, match="lease_lost"):
        store.write_bytes(
            "thumbnails/person-0001.jpg",
            b"jpeg-payload",
            "image/jpeg",
            authorize_publish=deny_publish,
        )

    parent = _attempt_root(tmp_path) / "thumbnails"
    assert checks == 1
    assert not (parent / "person-0001.jpg").exists()
    assert list(parent.glob(".*.tmp")) == []


def test_successful_publication_returns_processed_track_with_attempt_keys(tmp_path: Path) -> None:
    publisher = ArtifactPublisher(
        StagingArtifactStore(tmp_path, JOB_ID, 2),
        _future_guard(),
    )

    track = publisher.publish_track(_prepared_track(), TRAJECTORY_CHUNKS)

    assert track.track_id == "person-0001"
    assert track.detection_count == 3
    assert track.mean_confidence == pytest.approx(0.9)
    assert track.max_confidence == pytest.approx(0.9)
    assert [(o.rank, o.role) for o in track.observations] == [
        (0, EvidenceRole.REPRESENTATIVE),
        (1, EvidenceRole.NEAR_VIEW),
        (2, EvidenceRole.LATE_DIVERSE),
    ]
    for observation, item in zip(track.observations, EVIDENCE, strict=True):
        path = _crop(tmp_path, observation.role.value, attempt=2)
        assert observation.crop.storage_key.endswith(f"/attempt-0002/evidence/person-0001-{observation.role.value}.jpg")
        assert path.read_bytes() == item.evidence.image.payload
        assert observation.crop.size_bytes == item.evidence.image.size_bytes
        assert (observation.source_frame_number, observation.offset_ms) == (
            item.evidence.source_frame_number,
            item.evidence.offset_ms,
        )
    assert not (_attempt_root(tmp_path, 2) / "thumbnails").exists()
    assert "/attempt-0002/trajectories/" in track.trajectory_artifact.storage_key
    trajectory_path = tmp_path.joinpath(*track.trajectory_artifact.storage_key.split("/"))
    assert trajectory_path.read_bytes() == b"trajectory-payload"
    assert track.trajectory_artifact.size_bytes == len(b"trajectory-payload")


def test_lease_lost_while_trajectory_streams_publishes_no_trajectory(tmp_path: Path) -> None:
    guard = _future_guard()
    publisher = ArtifactPublisher(StagingArtifactStore(tmp_path, JOB_ID, 1), guard)

    def chunks_then_lose_lease():
        yield b"trajectory-"
        guard.mark_lost()
        yield b"payload"

    with pytest.raises(LeaseLostError, match="lease_lost"):
        publisher.publish_track(_prepared_track(), chunks_then_lose_lease())

    trajectories = _attempt_root(tmp_path) / "trajectories"
    assert list(trajectories.iterdir()) == []


def test_remove_omitted_deletes_exactly_the_named_crops(tmp_path: Path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    publisher = ArtifactPublisher(store, _future_guard())
    track = publisher.publish_track(_prepared_track(), TRAJECTORY_CHUNKS)

    publisher.remove_omitted([(track.track_id, track.observations[1])])

    assert not _crop(tmp_path, "near-view").exists()
    assert _crop(tmp_path, "representative").exists()
    assert _crop(tmp_path, "late-diverse").exists()


def test_remove_omitted_after_lease_loss_deletes_nothing(tmp_path: Path) -> None:
    guard = _future_guard()
    publisher = ArtifactPublisher(StagingArtifactStore(tmp_path, JOB_ID, 1), guard)
    track = publisher.publish_track(_prepared_track(), TRAJECTORY_CHUNKS)
    guard.mark_lost()

    with pytest.raises(LeaseLostError, match="lease_lost"):
        publisher.remove_omitted([(track.track_id, track.observations[1])])

    assert _crop(tmp_path, "near-view").exists()
