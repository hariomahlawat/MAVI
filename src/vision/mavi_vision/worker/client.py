import json
import re
from typing import Final

import httpx

from mavi_vision.common.control_plane import (
    VisionJobFail,
    VisionJobHeartbeat,
    VisionJobHeartbeatResponse,
    VisionJobLease,
    VisionJobLeaseRequest,
)
from mavi_vision.common.settings import WorkerSettings


# Error handling
_SAFE_PROBLEM_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$", re.ASCII)


class WorkerApiError(RuntimeError):
    """A sanitized worker control-plane transport or status error."""


# Canonical control-plane client
class WorkerApiClient:
    def __init__(
        self,
        settings: WorkerSettings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            verify=str(settings.ca_bundle) if settings.ca_bundle is not None else True,
        )

    async def lease(self) -> VisionJobLease | None:
        request = VisionJobLeaseRequest(
            schemaVersion="2.0",
            workerId=self._settings.worker_id,
        )
        response = await self._post("/api/vision/jobs/lease", request.model_dump_json(by_alias=True))
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        self._raise_for_status(response)
        return VisionJobLease.model_validate_json(response.content)

    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        request = VisionJobHeartbeat(
            schemaVersion="2.0",
            workerId=self._settings.worker_id,
            leaseToken=lease.lease_token,
            progressPercent=progress_percent,
        )
        response = await self._post(
            f"/api/vision/jobs/{lease.job_id}/heartbeat",
            request.model_dump_json(by_alias=True),
        )
        self._raise_for_status(response)
        return VisionJobHeartbeatResponse.model_validate_json(response.content)

    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        request = VisionJobFail(
            schemaVersion="2.0",
            workerId=self._settings.worker_id,
            leaseToken=lease.lease_token,
            failureCode=failure_code,
            failureMessage=failure_message,
        )
        response = await self._post(
            f"/api/vision/jobs/{lease.job_id}/fail",
            request.model_dump_json(by_alias=True),
        )
        self._raise_for_status(response)

    async def aclose(self) -> None:
        await self._http_client.aclose()

    # HTTP internals
    async def _post(self, path: str, body: str) -> httpx.Response:
        try:
            return await self._http_client.post(
                f"{self._settings.api_base_url}{path}",
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=self._settings.request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise WorkerApiError("worker API request failed") from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        code = WorkerApiClient._safe_problem_code(response)
        suffix = f" ({code})" if code is not None else ""
        raise WorkerApiError(f"worker API returned HTTP {response.status_code}{suffix}")

    @staticmethod
    def _safe_problem_code(response: httpx.Response) -> str | None:
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        code = payload.get("code") if isinstance(payload, dict) else None
        if isinstance(code, str) and _SAFE_PROBLEM_CODE.fullmatch(code):
            return code
        return None
