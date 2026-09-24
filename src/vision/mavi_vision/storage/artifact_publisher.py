from __future__ import annotations

from collections.abc import Iterable, Sequence

from mavi_vision.common.analytical import ObservationDescriptor, ProcessedTrack
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

    def publish_track(
        self,
        prepared: PreparedTrack,
        trajectory_chunks: Iterable[bytes],
    ) -> ProcessedTrack:
        """Stage the trajectory, then each Evidence Set crop once, all lease-fenced.

        ``trajectory_chunks`` is the canonical v1 payload as bounded buffers; it
        is consumed exactly once, while the temp file is written, and never
        joined in memory. Crops are written in rank order under
        ``evidence/{trackId}-{role}.jpg``; the returned Track keeps only their
        descriptors.
        """
        # Validate every logical name before creating any directory or file.
        self._store.trajectory_key(prepared.track_id)
        crop_names = tuple(
            self._store.evidence_relative_name(prepared.track_id, item.role.value)
            for item in prepared.evidence
        )

        self._lease_guard.check_owned()
        trajectory_artifact = self._store.write_stream(
            f"trajectories/{prepared.track_id}.msgpack",
            trajectory_chunks,
            "application/msgpack",
            authorize_publish=self._lease_guard.check_owned,
        )

        observations: list[ObservationDescriptor] = []
        for name, item in zip(crop_names, prepared.evidence, strict=True):
            self._lease_guard.check_owned()
            evidence = item.evidence
            crop = self._store.write_bytes(
                name,
                evidence.image.payload,
                "image/jpeg",
                authorize_publish=self._lease_guard.check_owned,
            )
            observations.append(
                ObservationDescriptor(
                    role=item.role,
                    rank=item.rank,
                    offset_ms=evidence.offset_ms,
                    source_frame_number=evidence.source_frame_number,
                    confidence=evidence.confidence,
                    bounding_box=evidence.bounding_box,
                    quality_micro=evidence.quality_micro,
                    selection_micro=evidence.selection_micro,
                    crop=crop,
                )
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
            observations=tuple(observations),
            trajectory_artifact=trajectory_artifact,
        )

    def remove_omitted(
        self,
        omitted: Sequence[tuple[str, ObservationDescriptor]],
    ) -> None:
        """Remove staged crops that run-level admission omitted (plan §6.2).

        Lease-fenced: a stale attempt deletes nothing (its staging belongs to the
        next attempt's cleanup or the platform janitor). Each removal is one
        regular-file leaf through the hardened store.
        """
        for track_id, observation in omitted:
            self._lease_guard.check_owned()
            self._store.remove(self._store.evidence_relative_name(track_id, observation.role.value))
