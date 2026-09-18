from __future__ import annotations

from mavi_vision.common.analytical import ProcessedTrack
from mavi_vision.common.lease import LeaseGuard
from mavi_vision.pipeline.finalization import PreparedTrack
from mavi_vision.storage.artifact_store import StagingArtifactStore


class ArtifactPublisher:
    """Publish prepared track artifacts only while the lease attempt is owned.

    The publisher is the sole pipeline-level gateway for filesystem side effects.
    The low-level store receives the same guard callback so ownership is checked
    again immediately before each atomic destination replacement.
    """

    def __init__(
        self,
        store: StagingArtifactStore,
        lease_guard: LeaseGuard,
    ) -> None:
        self._store = store
        self._lease_guard = lease_guard

    def publish_track(self, prepared: PreparedTrack) -> ProcessedTrack:
        # Validate the logical track identifier before creating any directories or
        # temporary files. This preserves the canonical staging-key contract.
        self._store.thumbnail_key(prepared.track_id)
        self._store.trajectory_key(prepared.track_id)

        self._lease_guard.check_owned()
        thumbnail = self._store.write_bytes(
            f"thumbnails/{prepared.track_id}.jpg",
            prepared.thumbnail_payload,
            "image/jpeg",
            authorize_publish=self._lease_guard.check_owned,
        )

        self._lease_guard.check_owned()
        trajectory_artifact = self._store.write_bytes(
            f"trajectories/{prepared.track_id}.msgpack",
            prepared.trajectory_payload,
            "application/msgpack",
            authorize_publish=self._lease_guard.check_owned,
        )

        self._lease_guard.check_owned()
        return ProcessedTrack(
            track_id=prepared.track_id,
            object_class=prepared.object_class,
            start_offset_ms=prepared.start_offset_ms,
            end_offset_ms=prepared.end_offset_ms,
            detection_count=prepared.detection_count,
            mean_confidence=prepared.mean_confidence,
            max_confidence=prepared.max_confidence,
            representative=prepared.representative,
            trajectory=prepared.trajectory,
            thumbnail=thumbnail,
            trajectory_artifact=trajectory_artifact,
        )
