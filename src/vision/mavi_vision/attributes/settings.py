"""Settings of the ``attributes`` role process (S2b plan §9, §14).

The attribute executor never touches a platform filesystem, so unlike the vision worker it has
no media root: evidence is read, and predictions uploaded, only through lease-scoped HTTP. Its
composition is the same Component Binding v2 path as the vision role's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavi_vision.common.control_plane import WorkerId
from mavi_vision.common.settings import reject_v1_composition_environment

# The platform refuses any lease shorter than this (VisualAttributeOptions.MinimumLeaseSeconds);
# a renewal must start, and be able to finish, well inside it.
PLATFORM_MINIMUM_LEASE_SECONDS = 60.0


class AttributeWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAVI_", extra="ignore")

    api_base_url: str
    worker_id: WorkerId
    poll_interval_seconds: float = Field(default=5.0, ge=0.25, le=60.0)
    heartbeat_interval_seconds: float = Field(default=20.0, ge=1.0, le=45.0)
    request_timeout_seconds: float = Field(default=15.0, ge=1.0, le=30.0)
    # Bounded retries of one evidence read within the lease before the attempt fails as
    # retryable transport; never a Track-level Unavailable (plan §10).
    evidence_read_attempts: int = Field(default=3, ge=1, le=5)
    evidence_retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=5.0)
    ca_bundle: Path | None = None

    model_root: Path = Path("models")
    component_binding_path: Path = Path("src/vision/config/components/phase1-bindings-v2.json")
    role_id: Literal["attributes"] = "attributes"
    overlay_root: Path = Path(".")
    runtime_pack_manifest_path: Path | None = None
    # The attribute pipeline profile (not the vision pipeline profile).
    pipeline_profile_path: Path
    deployment_profile_policy_path: Path = Path("config/acceptance/phase1-deployment-profiles-v1.json")
    deployment_profile: Literal["P1", "P2", "P3"] | None = None
    build_id: str | None = None
    commit_sha: str | None = None
    device_policy: Literal["cpu", "cuda", "auto"] = "cpu"
    device_index: int = Field(default=0, ge=0, le=255)
    production_mode: bool = False

    @model_validator(mode="before")
    @classmethod
    def reject_v1_composition(cls, data: Any) -> Any:
        reject_v1_composition_environment()
        return data

    @model_validator(mode="after")
    def validate_operational_policy(self) -> "AttributeWorkerSettings":
        # A renewal is due every interval and may take a full request timeout: both must fit
        # inside the shortest lease the platform grants, with a margin for the clock.
        if self.heartbeat_interval_seconds + self.request_timeout_seconds >= PLATFORM_MINIMUM_LEASE_SECONDS * 0.75:
            raise ValueError("attribute_heartbeat_margin_invalid")
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


__all__ = ["AttributeWorkerSettings", "PLATFORM_MINIMUM_LEASE_SECONDS"]
