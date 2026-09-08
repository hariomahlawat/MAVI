from datetime import datetime, timezone
from uuid import UUID

import pytest

from mavi_vision.common.contracts import VisionJob


def test_vision_job_serializes_to_stable_camel_case_contract() -> None:
    job = VisionJob(
        job_id=UUID("11111111-1111-1111-1111-111111111111"),
        video_asset_id=UUID("22222222-2222-2222-2222-222222222222"),
        camera_id="CAM-001",
        media_uri="media://camera/CAM-001/sample.mp4",
        start_utc=datetime(2026, 9, 8, 4, 30, tzinfo=timezone.utc),
    )

    assert job.to_dict() == {
        "schemaVersion": "1.0",
        "jobId": "11111111-1111-1111-1111-111111111111",
        "videoAssetId": "22222222-2222-2222-2222-222222222222",
        "cameraId": "CAM-001",
        "mediaUri": "media://camera/CAM-001/sample.mp4",
        "startUtc": "2026-09-08T04:30:00Z",
    }


def test_vision_job_rejects_naive_cross_system_timestamp() -> None:
    job = VisionJob(
        job_id=UUID("11111111-1111-1111-1111-111111111111"),
        video_asset_id=UUID("22222222-2222-2222-2222-222222222222"),
        camera_id="CAM-001",
        media_uri="media://camera/CAM-001/sample.mp4",
        start_utc=datetime(2026, 9, 8, 4, 30),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        job.to_dict()
