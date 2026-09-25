from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavi_vision.common.control_plane import WorkerId


# Worker configuration
class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAVI_", extra="ignore")

    api_base_url: str
    worker_id: WorkerId
    media_root: Path
    poll_interval_seconds: float = Field(default=2.0, ge=0.25, le=60.0)
    heartbeat_interval_seconds: float = Field(default=30.0, ge=1.0, le=60.0)
    request_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    ca_bundle: Path | None = None

    model_root: Path = Path("models")
    model_manifest_path: Path = Path(
        "models/manifests/rtmdet-m-coco-phase1-v1.json"
    )
    pipeline_profile_path: Path = Path(
        "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
    )
    runtime_profile_path: Path = Path(
        "src/vision/runtime/mmdetection-phase1-v1/runtime.json"
    )
    deployment_profile_policy_path: Path = Path(
        "config/acceptance/phase1-deployment-profiles-v1.json"
    )
    deployment_profile: Literal["P1", "P2", "P3"] | None = None
    qualification_record_path: Path | None = Path(
        "models/qualifications/rtmdet-m-coco-phase1-v1.json"
    )
    build_id: str | None = None
    commit_sha: str | None = None
    device_policy: Literal["cpu", "cuda", "auto"] = "auto"
    device_index: int = Field(default=0, ge=0, le=255)
    device_resolution_reason: str | None = None
    production_mode: bool = False
    # The worker side of the S1.4 B3 activation gate (plan §15.2). "3.0" is the
    # synchronous completion the platform accepts until the F3 finalizer exists;
    # the F3 release sets MAVI_COMPLETION_SCHEMA_VERSION=3.1 together with the
    # platform's VisionFinalization:Enabled. The probe requires exactly this
    # version, so a mismatched pair fails closed before any lease.
    completion_schema_version: Literal["3.0", "3.1"] = "3.0"
    inference_watchdog_seconds: float = Field(default=120.0, ge=5.0, le=3600.0)
    watchdog_grace_seconds: float = Field(default=15.0, ge=1.0, le=300.0)

    @model_validator(mode="after")
    def validate_runtime_operational_policy(self) -> "WorkerSettings":
        if self.production_mode and self.device_policy == "auto":
            raise ValueError("MAVI_DEVICE_POLICY=auto is development-only")
        if self.production_mode and self.deployment_profile is None:
            raise ValueError(
                "MAVI_DEPLOYMENT_PROFILE is required in production mode"
            )
        if self.watchdog_grace_seconds >= self.inference_watchdog_seconds:
            raise ValueError(
                "MAVI_WATCHDOG_GRACE_SECONDS must be less than "
                "MAVI_INFERENCE_WATCHDOG_SECONDS"
            )
        return self

    @field_validator("device_resolution_reason")
    @classmethod
    def validate_device_resolution_reason(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        if (
            not value
            or value != value.strip()
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) is None
        ):
            raise ValueError(
                "MAVI_DEVICE_RESOLUTION_REASON is invalid"
            )
        return value

    @field_validator("api_base_url")
    @classmethod
    def validate_api_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parts = urlsplit(normalized)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or "?" in normalized
            or "#" in normalized
        ):
            raise ValueError("MAVI_API_BASE_URL must be an absolute HTTP(S) URL")
        return normalized
