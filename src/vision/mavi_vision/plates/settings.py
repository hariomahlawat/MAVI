"""Settings of the ``plates`` role process (Stage 4 plan §2.1, §2.4).

The plates executor never touches a platform filesystem: evidence is read, and predictions uploaded,
only through lease-scoped HTTP. Its composition is the same Component Binding v2 path as every role's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavi_vision.common.control_plane import WorkerId
from mavi_vision.common.settings import reject_v1_composition_environment

# The platform refuses any lease shorter than this (PlateOptions.MinimumLeaseSeconds).
PLATFORM_MINIMUM_LEASE_SECONDS = 60.0


class PlateWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAVI_", extra="ignore")

    api_base_url: str
    worker_id: WorkerId
    poll_interval_seconds: float = Field(default=5.0, ge=0.25, le=60.0)
    heartbeat_interval_seconds: float = Field(default=20.0, ge=1.0, le=45.0)
    request_timeout_seconds: float = Field(default=15.0, ge=1.0, le=30.0)
    # Bounded retries of one evidence read within the lease before the attempt fails as retryable
    # transport; never a Track-level Unavailable (ADR-013 amendment 2026-09-28, item 3).
    evidence_read_attempts: int = Field(default=3, ge=1, le=5)
    evidence_retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=5.0)
    ca_bundle: Path | None = None

    model_root: Path = Path("models")
    component_binding_path: Path = Path("src/vision/config/components/phase1-bindings-v2.json")
    role_id: Literal["plates"] = "plates"
    overlay_root: Path = Path(".")
    runtime_pack_manifest_path: Path | None = None
    # The plate pipeline profile (not the vision or attribute profile).
    pipeline_profile_path: Path
    deployment_profile_policy_path: Path = Path("config/acceptance/phase1-deployment-profiles-v1.json")
    deployment_profile: Literal["P1", "P2", "P3"] | None = None
    build_id: str | None = None
    commit_sha: str | None = None
    # The plates role defaults to CPU (plan §2.5); CUDA co-residency is a measured profile decision.
    device_policy: Literal["cpu", "cuda", "auto"] = "cpu"
    device_index: int = Field(default=0, ge=0, le=255)
    production_mode: bool = False

    @model_validator(mode="before")
    @classmethod
    def reject_v1_composition(cls, data: Any) -> Any:
        reject_v1_composition_environment()
        return data

    @model_validator(mode="after")
    def validate_operational_policy(self) -> "PlateWorkerSettings":
        if self.heartbeat_interval_seconds + self.request_timeout_seconds >= PLATFORM_MINIMUM_LEASE_SECONDS * 0.75:
            raise ValueError("plate_heartbeat_margin_invalid")
        if self.production_mode and self.device_policy == "auto":
            raise ValueError("MAVI_DEVICE_POLICY=auto is development-only")
        if self.production_mode and self.deployment_profile is None:
            raise ValueError("MAVI_DEPLOYMENT_PROFILE is required in production mode")
        return self

    @field_validator("api_base_url")
    @classmethod
    def validate_api_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parts = urlsplit(normalized)
        if parts.scheme not in {"http", "https"} or not parts.netloc or "?" in normalized or "#" in normalized:
            raise ValueError("MAVI_API_BASE_URL must be an absolute HTTP(S) URL")
        return normalized


__all__ = ["PLATFORM_MINIMUM_LEASE_SECONDS", "PlateWorkerSettings"]
