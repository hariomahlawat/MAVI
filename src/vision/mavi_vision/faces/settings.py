"""Settings of the ``faces`` role process (PoC S6; ADR-022 §2–§3).

Like the embeddings role (ADR-021 §2), the role is composed from explicit paths (Model Pack root, model manifest,
pipeline profile), not from a Component Binding: it is Development-only (ADR-020 ``poc-single-host``; ADR-022 §9
refuses it under P1–P3), its identity is pinned by the manifest and profile bytes, and every manifest artefact is
SHA-256 verified before anything is loaded. Production mode is refused at configuration time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavi_vision.common.control_plane import WorkerId

# The platform refuses any analysis lease shorter than this; the heartbeat must fit well inside it.
PLATFORM_MINIMUM_LEASE_SECONDS = 60.0


class FaceWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAVI_", extra="ignore")

    api_base_url: str
    worker_id: WorkerId
    poll_interval_seconds: float = Field(default=5.0, ge=0.25, le=60.0)
    # Query images are pulled faster: an operator waits for the faces of an uploaded image.
    query_poll_interval_seconds: float = Field(default=0.5, ge=0.1, le=10.0)
    heartbeat_interval_seconds: float = Field(default=20.0, ge=1.0, le=45.0)
    request_timeout_seconds: float = Field(default=15.0, ge=1.0, le=30.0)
    evidence_read_attempts: int = Field(default=3, ge=1, le=5)
    evidence_retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=5.0)
    ca_bundle: Path | None = None

    # The directory that holds <packDirectory>/ (faces-yunet-<embedder>-dev-v1/).
    model_root: Path
    face_manifest_path: Path
    face_pipeline_profile_path: Path
    device_policy: Literal["cpu", "cuda", "auto"] = "cpu"
    device_index: int = Field(default=0, ge=0, le=99)
    # Optional directory of CUDA/cuDNN DLLs put on the DLL search path before onnxruntime is imported (Windows).
    cuda_dll_directory: Path | None = None
    production_mode: bool = False

    @model_validator(mode="after")
    def validate_operational_policy(self) -> "FaceWorkerSettings":
        if self.production_mode:
            raise ValueError("face_role_development_only")
        if self.heartbeat_interval_seconds + self.request_timeout_seconds >= PLATFORM_MINIMUM_LEASE_SECONDS * 0.75:
            raise ValueError("face_heartbeat_margin_invalid")
        return self

    @field_validator("api_base_url")
    @classmethod
    def validate_api_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parts = urlsplit(normalized)
        if parts.scheme not in {"http", "https"} or not parts.netloc or "?" in normalized or "#" in normalized:
            raise ValueError("MAVI_API_BASE_URL must be an absolute HTTP(S) URL")
        return normalized


__all__ = ["FaceWorkerSettings", "PLATFORM_MINIMUM_LEASE_SECONDS"]
