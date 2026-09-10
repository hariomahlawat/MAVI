import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import VisionJobLease
from mavi_vision.common.settings import WorkerSettings
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
