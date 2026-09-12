from pathlib import Path

import pytest
from pydantic import ValidationError

from mavi_vision.common.settings import WorkerSettings


# Test helpers
def seed_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAVI_API_BASE_URL", "https://mavi-api.local:62152/")
    monkeypatch.setenv("MAVI_WORKER_ID", "dev-worker-01")
    monkeypatch.setenv("MAVI_MEDIA_ROOT", str(tmp_path))


# Settings behavior
def test_settings_load_and_normalize(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_required(monkeypatch, tmp_path)
    settings = WorkerSettings()
    assert settings.api_base_url == "https://mavi-api.local:62152"
    assert settings.worker_id == "dev-worker-01"
    assert settings.media_root == tmp_path
    assert settings.poll_interval_seconds == 2.0
    assert settings.heartbeat_interval_seconds == 30.0
    assert settings.model_root == Path("models")
    assert settings.model_manifest_path == Path(
        "models/manifests/rtmdet-m-coco-phase1-v1.json"
    )
    assert settings.pipeline_profile_path == Path(
        "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
    )
    assert settings.runtime_profile_path == Path(
        "src/vision/runtime/mmdetection-phase1-v1/runtime.json"
    )
    assert settings.device_policy == "auto"
    assert settings.device_index == 0
    assert settings.production_mode is False
    assert settings.inference_watchdog_seconds == 120.0
    assert settings.watchdog_grace_seconds == 15.0


def test_settings_reject_unsafe_worker_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_WORKER_ID", "bad/worker")
    with pytest.raises(ValidationError):
        WorkerSettings()


@pytest.mark.parametrize(
    "url",
    [
        "mavi-api.local",
        "ftp://mavi-api.local",
        "https:///missing-host",
        "https://mavi-api.local?tenant=a",
        "https://mavi-api.local/#worker",
        "https://mavi-api.local?",
        "https://mavi-api.local#",
    ],
)
def test_settings_reject_invalid_api_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_API_BASE_URL", url)
    with pytest.raises(ValidationError):
        WorkerSettings()

def test_settings_load_runtime_operational_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setenv(
        "MAVI_MODEL_MANIFEST_PATH",
        str(tmp_path / "release" / "manifest.json"),
    )
    monkeypatch.setenv(
        "MAVI_PIPELINE_PROFILE_PATH",
        str(tmp_path / "release" / "profile.json"),
    )
    monkeypatch.setenv(
        "MAVI_RUNTIME_PROFILE_PATH",
        str(tmp_path / "release" / "runtime.json"),
    )
    monkeypatch.setenv("MAVI_DEVICE_POLICY", "cuda")
    monkeypatch.setenv("MAVI_DEVICE_INDEX", "2")
    monkeypatch.setenv("MAVI_PRODUCTION_MODE", "true")
    monkeypatch.setenv("MAVI_INFERENCE_WATCHDOG_SECONDS", "180")
    monkeypatch.setenv("MAVI_WATCHDOG_GRACE_SECONDS", "20")

    settings = WorkerSettings()

    assert settings.model_root == tmp_path / "models"
    assert settings.model_manifest_path == tmp_path / "release" / "manifest.json"
    assert settings.pipeline_profile_path == tmp_path / "release" / "profile.json"
    assert settings.runtime_profile_path == tmp_path / "release" / "runtime.json"
    assert settings.device_policy == "cuda"
    assert settings.device_index == 2
    assert settings.production_mode is True
    assert settings.inference_watchdog_seconds == 180.0
    assert settings.watchdog_grace_seconds == 20.0


def test_production_settings_reject_auto_device_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_PRODUCTION_MODE", "true")
    monkeypatch.setenv("MAVI_DEVICE_POLICY", "auto")

    with pytest.raises(ValidationError, match="development-only"):
        WorkerSettings()


@pytest.mark.parametrize("device_policy", ["gpu", "CUDA", ""])
def test_settings_reject_invalid_device_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    device_policy: str,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_DEVICE_POLICY", device_policy)

    with pytest.raises(ValidationError):
        WorkerSettings()


def test_settings_reject_negative_device_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_DEVICE_INDEX", "-1")

    with pytest.raises(ValidationError):
        WorkerSettings()


@pytest.mark.parametrize(
    ("watchdog", "grace"),
    [
        ("10", "10"),
        ("10", "11"),
        ("4", "1"),
        ("120", "0"),
    ],
)
def test_settings_reject_invalid_watchdog_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    watchdog: str,
    grace: str,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_INFERENCE_WATCHDOG_SECONDS", watchdog)
    monkeypatch.setenv("MAVI_WATCHDOG_GRACE_SECONDS", grace)

    with pytest.raises(ValidationError):
        WorkerSettings()


def test_worker_settings_do_not_expose_analytical_tuning_knobs() -> None:
    forbidden = {
        "detector_inference_floor",
        "track_activation_threshold",
        "high_confidence_threshold",
        "reference_frame_rate",
        "minimum_iou_threshold",
        "minimum_matching_threshold",
        "minimum_consecutive_frames",
        "lost_track_buffer_seconds",
        "max_detections",
    }

    assert forbidden.isdisjoint(WorkerSettings.model_fields)

