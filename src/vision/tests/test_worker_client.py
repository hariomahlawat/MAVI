import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import VisionJobCompleteResponse, VisionJobLease
from mavi_vision.common.lease import LeaseLostError
from mavi_vision.common.settings import WorkerSettings
from mavi_vision.runtime.provenance import PlatformIdentity, RuntimeProvenance, TrackerParameters
from mavi_vision.worker.client import WorkerApiClient, WorkerApiError


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"
LEASE_TOKEN = "A" * 43


# Test helpers
def settings(tmp_path: Path) -> WorkerSettings:
    return WorkerSettings(
        api_base_url="https://mavi-api.local",
        worker_id="gpu-sdd-01",
        media_root=tmp_path,
    )


def lease() -> VisionJobLease:
    return VisionJobLease.model_validate_json(EXAMPLE.read_text())


def provenance() -> RuntimeProvenance:
    return RuntimeProvenance(
        model_id="rtmdet-m",
        model_version="1",
        model_manifest_sha256="1" * 64,
        checkpoint_sha256="2" * 64,
        resolved_config_sha256="3" * 64,
        pipeline_profile_id="phase1",
        pipeline_profile_version="1",
        pipeline_profile_sha256="4" * 64,
        qualification_id=None,
        qualification_sha256=None,
        verification_status="unverified",
        runtime_profile_id="runtime-v1",
        runtime_profile_sha256="5" * 64,
        runtime_variant="linux-x86_64-cpu",
        platform_lock_sha256="6" * 64,
        detector_backend="mmdetection",
        dependency_versions={"trackers": "2.6.0"},
        ffmpeg_version=None,
        platform=PlatformIdentity(
            system="Linux",
            release="6.8",
            version="qualified",
            machine="x86_64",
            processor="x86_64",
            python_version="3.12.14",
            python_implementation="CPython",
            python_build=("main", "Sep 2026"),
            python_compiler="GCC",
        ),
        configured_device_policy="cpu",
        configured_device_index=0,
        device_resolution_reason="explicit_cpu",
        actual_device="cpu",
        gpu=None,
        mavi_build="test-build",
        mavi_commit="a" * 40,
        frame_policy="every-frame",
        tracker_parameters=TrackerParameters(
            reference_frame_rate=30,
            track_activation_threshold=.25,
            high_confidence_threshold=.1,
            minimum_iou_threshold=.2,
            minimum_consecutive_frames=2,
            lost_track_buffer_seconds=1,
        ),
    )


def run_request(
    tmp_path: Path, handler: httpx.MockTransport, action: str
) -> object:
    async def invoke() -> object:
        injected = httpx.AsyncClient(transport=handler)
        client = WorkerApiClient(settings(tmp_path), injected)
        try:
            if action == "lease":
                return await client.lease()
            if action == "heartbeat":
                return await client.heartbeat(lease(), 5.0)
            if action == "complete":
                expected = lease()
                return await client.complete(
                    expected,
                    VisionProcessingResult(
                        job_id=expected.job_id,
                        frames_processed=1,
                        tracks=(),
                    ),
                    125,
                    provenance(),
                )
            return await client.fail(lease(), "dummy_processing_not_implemented", "Dummy only")
        finally:
            await client.aclose()

    return asyncio.run(invoke())


# Lease protocol
def test_lease_request_uses_exact_canonical_json(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/vision/jobs/lease"
        assert request.headers["content-type"] == "application/json"
        assert request.content == b'{"schemaVersion":"2.0","workerId":"gpu-sdd-01"}'
        return httpx.Response(204)

    assert run_request(tmp_path, httpx.MockTransport(handler), "lease") is None


def test_lease_parses_canonical_response(tmp_path: Path) -> None:
    result = run_request(
        tmp_path,
        httpx.MockTransport(lambda _: httpx.Response(200, content=EXAMPLE.read_bytes())),
        "lease",
    )
    assert isinstance(result, VisionJobLease)


@pytest.mark.parametrize(
    "change",
    [
        {"source_storage_key": "video/input.mp4"},
        {"leaseExpiresAtUtc": "2026-09-09T03:00:00+00:00"},
    ],
)
def test_lease_rejects_noncanonical_response(tmp_path: Path, change: dict[str, str]) -> None:
    payload = json.loads(EXAMPLE.read_text())
    if "source_storage_key" in change:
        payload.pop("sourceStorageKey")
    payload.update(change)
    with pytest.raises(ValidationError):
        run_request(
            tmp_path,
            httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
            "lease",
        )


# Lifecycle protocol
def test_heartbeat_uses_canonical_path_and_body(tmp_path: Path) -> None:
    expected = lease()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/vision/jobs/{expected.job_id}/heartbeat"
        assert json.loads(request.content) == {
            "schemaVersion": "2.0",
            "workerId": expected.worker_id,
            "leaseToken": expected.lease_token,
            "progressPercent": 5.0,
        }
        return httpx.Response(
            200,
            json={
                "schemaVersion": "2.0",
                "progressPercent": 5.0,
                "leaseExpiresAtUtc": "2026-09-09T03:00:00Z",
            },
        )

    response = run_request(tmp_path, httpx.MockTransport(handler), "heartbeat")
    assert response.progress_percent == 5.0


def test_fail_uses_canonical_path_and_body(tmp_path: Path) -> None:
    expected = lease()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/vision/jobs/{expected.job_id}/fail"
        assert json.loads(request.content) == {
            "schemaVersion": "2.0",
            "workerId": expected.worker_id,
            "leaseToken": expected.lease_token,
            "failureCode": "dummy_processing_not_implemented",
            "failureMessage": "Dummy only",
        }
        return httpx.Response(204)

    assert run_request(tmp_path, httpx.MockTransport(handler), "fail") is None


def test_complete_uses_canonical_path_and_projects_runtime_provenance(tmp_path: Path) -> None:
    expected = lease()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/vision/jobs/{expected.job_id}/complete"
        payload = json.loads(request.content)
        assert payload["schemaVersion"] == "2.0"
        assert payload["jobId"] == str(expected.job_id)
        assert payload["workerId"] == expected.worker_id
        assert payload["leaseToken"] == expected.lease_token
        assert payload["attemptCount"] == expected.attempt_count
        assert payload["framesProcessed"] == 1
        assert payload["processingDurationMs"] == 125
        assert payload["tracks"] == []
        assert payload["provenance"]["modelId"] == "rtmdet-m"
        assert payload["provenance"]["dependencyVersions"]["trackers"] == "2.6.0"
        assert payload["provenance"]["inputColourSpace"] == "RGB"
        return httpx.Response(
            200,
            json={
                "schemaVersion": "2.0",
                "jobId": str(expected.job_id),
                "processingRunId": str(expected.processing_run_id),
                "tracksAccepted": 0,
                "completedAtUtc": "2026-09-13T08:00:00Z",
            },
        )

    response = run_request(tmp_path, httpx.MockTransport(handler), "complete")

    assert isinstance(response, VisionJobCompleteResponse)
    assert response.processing_run_id == expected.processing_run_id


def test_complete_rechecks_authority_after_payload_projection_before_http(
    tmp_path: Path,
) -> None:
    expected = lease()
    published = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal published
        published = True
        return httpx.Response(500)

    async def invoke() -> None:
        injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = WorkerApiClient(settings(tmp_path), injected)
        try:
            with pytest.raises(LeaseLostError):
                await client.complete(
                    expected,
                    VisionProcessingResult(
                        job_id=expected.job_id,
                        frames_processed=1,
                        tracks=(),
                    ),
                    125,
                    provenance(),
                    authorize_publish=lambda: (_ for _ in ()).throw(LeaseLostError()),
                )
        finally:
            await client.aclose()

    asyncio.run(invoke())
    assert published is False


def test_api_error_never_surfaces_lease_token_or_raw_body(tmp_path: Path) -> None:
    secret = lease().lease_token
    transport = httpx.MockTransport(
        lambda _: httpx.Response(409, json={"code": "lease_conflict", "detail": secret})
    )
    with pytest.raises(WorkerApiError) as captured:
        run_request(tmp_path, transport, "heartbeat")
    message = str(captured.value)
    assert secret not in message
    assert "detail" not in message
    assert "lease_conflict" in message
