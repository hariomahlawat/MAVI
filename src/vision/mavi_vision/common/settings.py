from collections.abc import Mapping
import os
from pathlib import Path
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavi_vision.common.control_plane import WorkerId


# Composition inputs retired at the Stage 2 S2a.3 cut-over (plan P-9, P-16). The
# component binding is the one composition source: a per-path v1 variable, or the
# S1.4 completion-version setting, fails closed instead of being silently ignored
# (``extra="ignore"`` would otherwise drop it). ``MAVI_PIPELINE_PROFILE_PATH`` stays:
# pipeline policy is not a component.
RETIRED_COMPOSITION_ENVIRONMENT = (
    "MAVI_MODEL_MANIFEST_PATH",
    "MAVI_QUALIFICATION_RECORD_PATH",
    "MAVI_RUNTIME_PROFILE_PATH",
    "MAVI_COMPLETION_SCHEMA_VERSION",
)
_RETIRED_COMPOSITION_FIELDS = frozenset(
    name.removeprefix("MAVI_").lower() for name in RETIRED_COMPOSITION_ENVIRONMENT
)


def reject_v1_composition_environment(environ: Mapping[str, str] | None = None) -> None:
    """Fail closed on any retired composition variable (``settings_v1_composition_rejected``).

    Environment names are matched case-insensitively, as pydantic-settings reads them.
    """
    source = os.environ if environ is None else environ
    retired = {name.upper() for name in RETIRED_COMPOSITION_ENVIRONMENT}
    present = sorted(name.upper() for name in source if name.upper() in retired)
    if present:
        raise ValueError("settings_v1_composition_rejected:" + ",".join(present))


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

    # Model Pack store root: every artefact resolves at <model_root>/<relativePath>,
    # one self-contained <packDirectory> per pack (P-10).
    model_root: Path = Path("models")
    # The one composition source (ADR-014; S2a plan §5.2, P-9). Manifests and
    # qualification records are found under the overlay by derived id, never by a
    # configured path; the runtime profile is the bound family's runtime.json.
    component_binding_path: Path = Path(
        "src/vision/config/components/phase1-bindings-v2.json"
    )
    role_id: Literal["vision"] = "vision"
    overlay_root: Path = Path(".")
    # Set by the launcher to the installed Runtime Pack's runtime-pack-manifest.json.
    # Absent: the worker runs from an unpacked environment and names no Runtime Pack.
    runtime_pack_manifest_path: Path | None = None
    pipeline_profile_path: Path = Path(
        "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
    )
    deployment_profile_policy_path: Path = Path(
        "config/acceptance/phase1-deployment-profiles-v1.json"
    )
    deployment_profile: Literal["P1", "P2", "P3"] | None = None
    build_id: str | None = None
    commit_sha: str | None = None
    device_policy: Literal["cpu", "cuda", "auto"] = "auto"
    device_index: int = Field(default=0, ge=0, le=255)
    device_resolution_reason: str | None = None
    production_mode: bool = False
    # The completion schema is the role's declared provenance contract (3.2, P-16).
    # The only way to run another version is this explicit, Development-only,
    # non-qualifying override: "3.1" for a platform with asynchronous finalization
    # enabled, "3.0" for one held at VisionFinalization:Enabled=false. It is refused
    # in production_mode, forces verificationStatus "unverified", drops the 3.2-only
    # component identity from completions and is logged at startup and on every
    # completion (completion_schema_override_active).
    completion_schema_override: Literal["3.0", "3.1"] | None = None
    inference_watchdog_seconds: float = Field(default=120.0, ge=5.0, le=3600.0)
    watchdog_grace_seconds: float = Field(default=15.0, ge=1.0, le=300.0)

    @model_validator(mode="before")
    @classmethod
    def reject_v1_composition(cls, data: Any) -> Any:
        reject_v1_composition_environment()
        if isinstance(data, Mapping):
            retired = sorted(name for name in data if str(name).lower() in _RETIRED_COMPOSITION_FIELDS)
            if retired:
                raise ValueError("settings_v1_composition_rejected:" + ",".join(retired))
        return data

    @model_validator(mode="after")
    def validate_runtime_operational_policy(self) -> "WorkerSettings":
        if self.production_mode and self.completion_schema_override is not None:
            raise ValueError("completion_override_forbidden_in_production")
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
