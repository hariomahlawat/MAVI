from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
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
