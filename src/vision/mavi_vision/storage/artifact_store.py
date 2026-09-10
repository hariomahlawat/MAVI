from __future__ import annotations

import os
import re
import shutil
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from mavi_vision.common.analytical import ArtifactDescriptor


_TRACK_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


class StagingArtifactError(RuntimeError):
    pass


class StagingArtifactStore:
    def __init__(self, media_root: Path, job_id: UUID) -> None:
        self._media_root = media_root.resolve()
        self._job_id = job_id
        self._job_root = (self._media_root / "staging" / str(job_id)).resolve()
        if not self._job_root.is_relative_to(self._media_root):
            raise StagingArtifactError("staging_path_escape")

    @property
    def job_id(self) -> UUID:
        return self._job_id

    def thumbnail_key(self, track_id: str) -> str:
        self._validate_track_id(track_id)
        return f"staging/{self._job_id}/thumbnails/{track_id}.jpg"

    def trajectory_key(self, track_id: str) -> str:
        self._validate_track_id(track_id)
        return f"staging/{self._job_id}/trajectories/{track_id}.msgpack"

    def write_bytes(
        self,
        relative_name: str,
        content: bytes,
        media_type: str,
    ) -> ArtifactDescriptor:
        parts = self._validate_relative_name(relative_name)
        candidate = self._job_root.joinpath(*parts)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = candidate.parent.resolve()
        if not resolved_parent.is_relative_to(self._job_root):
            raise StagingArtifactError("staging_path_escape")

        destination = resolved_parent / candidate.name
        if destination.is_symlink():
            raise StagingArtifactError("staging_path_escape")

        temp_path = resolved_parent / f".{candidate.name}.{uuid4().hex}.tmp"
        try:
            with open(temp_path, "xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, destination)
        except OSError as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise StagingArtifactError("staging_write_failed") from exc

        storage_key = f"staging/{self._job_id}/{'/'.join(parts)}"
        return ArtifactDescriptor(
            storage_key=storage_key,
            media_type=media_type,
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
        )

    def cleanup(self) -> None:
        if self._job_root.exists():
            resolved = self._job_root.resolve()
            if not resolved.is_relative_to(self._media_root):
                raise StagingArtifactError("staging_path_escape")
            shutil.rmtree(resolved)

    @staticmethod
    def _validate_track_id(track_id: str) -> None:
        if _TRACK_ID_PATTERN.fullmatch(track_id) is None:
            raise StagingArtifactError("track_id_invalid")

    @staticmethod
    def _validate_relative_name(relative_name: str) -> tuple[str, ...]:
        if (
            not relative_name
            or relative_name.startswith(("/", "\\"))
            or "\\" in relative_name
        ):
            raise StagingArtifactError("staging_relative_name_invalid")
        parts = tuple(relative_name.split("/"))
        if any(part in {"", ".", ".."} for part in parts):
            raise StagingArtifactError("staging_relative_name_invalid")
        if ":" in parts[0]:
            raise StagingArtifactError("staging_relative_name_invalid")
        return parts
