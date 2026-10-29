"""Settings of the ``embeddings`` role process (PoC S4; ADR-021 §3).

The role is composed from explicit paths (Model Pack root, model manifest, pipeline profile), not from a Component
Binding: it is a Development-only role (ADR-020 ``poc-single-host``) whose identity is pinned by the manifest and
profile bytes, and every manifest artefact is SHA-256 verified before anything is loaded. Production mode is
refused at configuration time.

The manifest path is ``MAVI_EMBEDDING_MANIFEST_PATH``: the generic ``MAVI_MODEL_MANIFEST_PATH`` is a retired v1
composition variable that the other roles refuse (``common.settings.RETIRED_COMPOSITION_ENVIRONMENT``).
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


class EmbeddingWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAVI_", extra="ignore")

    api_base_url: str
    worker_id: WorkerId
    poll_interval_seconds: float = Field(default=5.0, ge=0.25, le=60.0)
    # Appearance text queries are pulled faster: the API waits a bounded ~10 s for a new text's vector.
    text_query_poll_interval_seconds: float = Field(default=0.5, ge=0.1, le=10.0)
    heartbeat_interval_seconds: float = Field(default=20.0, ge=1.0, le=45.0)
    request_timeout_seconds: float = Field(default=15.0, ge=1.0, le=30.0)
    evidence_read_attempts: int = Field(default=3, ge=1, le=5)
    evidence_retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=5.0)
    ca_bundle: Path | None = None

    # The directory that holds <packDirectory>/ (embeddings-siglip2-base-p16-224-dev-v1/).
    model_root: Path
    embedding_manifest_path: Path
    pipeline_profile_path: Path
    device_policy: Literal["cpu", "cuda", "auto"] = "cpu"
    device_index: int = Field(default=0, ge=0, le=99)
    # Optional directory of CUDA/cuDNN DLLs put on the DLL search path before onnxruntime is imported (Windows).
    cuda_dll_directory: Path | None = None
    production_mode: bool = False

    @model_validator(mode="after")
    def validate_operational_policy(self) -> "EmbeddingWorkerSettings":
        if self.production_mode:
            raise ValueError("embedding_role_development_only")
        if self.heartbeat_interval_seconds + self.request_timeout_seconds >= PLATFORM_MINIMUM_LEASE_SECONDS * 0.75:
            raise ValueError("embedding_heartbeat_margin_invalid")
        return self

    @field_validator("api_base_url")
    @classmethod
    def validate_api_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parts = urlsplit(normalized)
        if parts.scheme not in {"http", "https"} or not parts.netloc or "?" in normalized or "#" in normalized:
            raise ValueError("MAVI_API_BASE_URL must be an absolute HTTP(S) URL")
        return normalized


__all__ = ["EmbeddingWorkerSettings", "PLATFORM_MINIMUM_LEASE_SECONDS"]
