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
        self._staging_root = self._media_root / "staging"
        self._job_root = self._staging_root / str(job_id)

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
        parent = self._ensure_safe_parent(parts[:-1])
        destination = parent / parts[-1]
        if destination.is_symlink():
            raise StagingArtifactError("staging_path_escape")

        temp_path = parent / f".{destination.name}.{uuid4().hex}.tmp"
        try:
            with open(temp_path, "xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if destination.is_symlink():
                raise StagingArtifactError("staging_path_escape")
            os.replace(temp_path, destination)
        except StagingArtifactError:
            temp_path.unlink(missing_ok=True)
            raise
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
        self._assert_existing_chain_safe(include_job_root=True)
        if self._job_root.exists():
            shutil.rmtree(self._job_root)

    def _ensure_safe_parent(self, relative_parts: tuple[str, ...]) -> Path:
        self._media_root.mkdir(parents=True, exist_ok=True)
        current = self._media_root
        for part in ("staging", str(self._job_id), *relative_parts):
            candidate = current / part
            if candidate.is_symlink():
                raise StagingArtifactError("staging_path_escape")
            if candidate.exists():
                if not candidate.is_dir():
                    raise StagingArtifactError("staging_path_escape")
            else:
                try:
                    candidate.mkdir()
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise StagingArtifactError("staging_write_failed") from exc
                if candidate.is_symlink() or not candidate.is_dir():
                    raise StagingArtifactError("staging_path_escape")
            resolved = candidate.resolve()
            if not resolved.is_relative_to(self._media_root):
                raise StagingArtifactError("staging_path_escape")
            current = candidate
        return current

    def _assert_existing_chain_safe(self, *, include_job_root: bool) -> None:
        current = self._media_root
        parts = ["staging"]
        if include_job_root:
            parts.append(str(self._job_id))
        for part in parts:
            candidate = current / part
            if candidate.is_symlink():
                raise StagingArtifactError("staging_path_escape")
            if not candidate.exists():
                return
            if not candidate.is_dir():
                raise StagingArtifactError("staging_path_escape")
            resolved = candidate.resolve()
            if not resolved.is_relative_to(self._media_root):
                raise StagingArtifactError("staging_path_escape")
            current = candidate

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
