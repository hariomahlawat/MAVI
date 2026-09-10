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
