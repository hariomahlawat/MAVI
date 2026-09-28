"""HTTP client of the attribute control plane (S2b plan §9–§13).

The lease capability is read from, and sent in, the ``X-Mavi-Lease-Capability`` header only.
It is never part of a URL, a body, an exception message or a log line: errors carry the
HTTP status and the platform's validated problem code, nothing else.

Evidence reads distinguish **transport** from **authority** (ADR-013 amendment 2026-09-28,
item 3). A timeout, a connection reset, a 5xx, a short body or a body that fails its digest
once is transport: it is retried within the lease and, if it persists, fails the *attempt*
as retryable. Only the platform's explicit 422 (the accepted object is missing, or its size
disagrees with its record) or bytes that fail their accepted SHA-256 on every bounded read
make the crop Unavailable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Final

import httpx
from pydantic import ValidationError

from mavi_vision.attributes.contracts import (
    ATTEMPT_HEADER,
    CAPABILITY_HEADER,
    CONTENT_SHA256_HEADER,
    CONTROL_VERSION,
    MAXIMUM_COMPLETION_REQUEST_BYTES,
    MAXIMUM_FAILURE_MESSAGE_LENGTH,
    MAXIMUM_LEASE_RESPONSE_BYTES,
    MAXIMUM_PREDICTION_ARTIFACT_BYTES,
    PREDICTIONS_MEDIA_TYPE,
    ROUTE_PREFIX,
    WORKER_HEADER,
    AttributeLease,
    CompleteResponse,
    FailResponse,
    HeartbeatResponse,
    LeaseObservation,
    UploadResponse,
)
from mavi_vision.common.control_plane import _lease_token

_LOGGER = logging.getLogger(__name__)
_SAFE_PROBLEM_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,95}$", re.ASCII)
# Small control responses; anything larger is not a response of this contract.
_MAXIMUM_CONTROL_RESPONSE_BYTES: Final = 64 * 1024
_LEASE_CODES: Final = frozenset(
    {
        "visual_attribute_lease_invalid",
        "visual_attribute_not_running",
        "visual_attribute_attempt_stale",
        "visual_attribute_analysis_not_found",
        "visual_attribute_evidence_forbidden",
    }
)


class AttributeApiError(RuntimeError):
    """A sanitised control-plane error: the status and a validated code, never free text."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class AttributeLeaseLost(AttributeApiError):
    """The platform no longer recognises this attempt's ownership: stop, never retry."""


class EvidenceTransportError(AttributeApiError):
    """An evidence read that did not produce an authoritative answer (retryable)."""


@dataclass(frozen=True, slots=True)
class EvidenceUnavailable:
    """An authoritative, platform-attested condition of one accepted crop."""

    reason: str


@dataclass(frozen=True, slots=True)
class LeasedAnalysis:
    """A lease and its capability, held apart so the capability is never serialised with it."""

    lease: AttributeLease
    capability: str

    def __repr__(self) -> str:  # never let a repr or traceback print the capability
        return f"LeasedAnalysis(analysis_id={self.lease.analysis_id}, attempt={self.lease.attempt_count})"


class AttributeApiClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        worker_id: str,
        identity_fingerprint: str,
        request_timeout_seconds: float,
        evidence_read_attempts: int = 3,
        evidence_retry_backoff_seconds: float = 0.5,
        http_client: httpx.AsyncClient | None = None,
        verify: str | bool = True,
    ) -> None:
        self._base = api_base_url.rstrip("/")
        self._worker_id = worker_id
        self._fingerprint = identity_fingerprint
        self._timeout = request_timeout_seconds
        self._evidence_attempts = evidence_read_attempts
        self._evidence_backoff = evidence_retry_backoff_seconds
        self._http = http_client or httpx.AsyncClient(timeout=request_timeout_seconds, verify=verify)

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- lease ------------------------------------------------------------------------

    async def lease(self) -> LeasedAnalysis | None:
        body = {"schemaVersion": CONTROL_VERSION, "workerId": self._worker_id, "identityFingerprint": self._fingerprint}
        try:
            async with self._http.stream("POST", f"{self._base}{ROUTE_PREFIX}/lease", json=body, timeout=self._timeout) as response:
                if response.status_code == httpx.codes.NO_CONTENT:
                    return None
                payload = await _read_bounded(response, MAXIMUM_LEASE_RESPONSE_BYTES)
                if response.status_code != httpx.codes.OK:
                    raise _error(response, payload, "lease refused")
                capability = _single_header(response, CAPABILITY_HEADER)
        except httpx.HTTPError as exc:
            raise AttributeApiError("lease request failed") from exc
        if capability is None:
            raise AttributeApiError("lease response carried no capability")
        try:
            capability = _lease_token(capability)
            lease = AttributeLease.model_validate_json(payload)
        except (ValueError, ValidationError) as exc:
            raise AttributeApiError("lease response is not a valid lease") from exc
        if lease.worker_id != self._worker_id or lease.identity.fingerprint != self._fingerprint:
            raise AttributeApiError("lease response names another worker or identity")
        return LeasedAnalysis(lease, capability)

    # --- heartbeat and failure --------------------------------------------------------

    async def heartbeat(self, leased: LeasedAnalysis) -> HeartbeatResponse:
        lease = leased.lease
        body = {
            "schemaVersion": CONTROL_VERSION,
            "analysisId": str(lease.analysis_id),
            "workerId": self._worker_id,
            "attemptCount": lease.attempt_count,
        }
        payload = await self._post_json(leased, f"{lease.analysis_id}/heartbeat", body, "heartbeat")
        return _parse(HeartbeatResponse, payload, "heartbeat")

    async def fail(self, leased: LeasedAnalysis, failure_code: str, failure_message: str | None) -> FailResponse:
        lease = leased.lease
        message = None if failure_message is None else _sanitise(failure_message, leased.capability)
        body = {
            "schemaVersion": CONTROL_VERSION,
            "analysisId": str(lease.analysis_id),
            "workerId": self._worker_id,
            "attemptCount": lease.attempt_count,
            "failureCode": failure_code,
            "failureMessage": message,
        }
        payload = await self._post_json(leased, f"{lease.analysis_id}/fail", body, "fail")
        return _parse(FailResponse, payload, "fail")

    # --- evidence -----------------------------------------------------------------------

    async def read_evidence(self, leased: LeasedAnalysis, observation: LeaseObservation) -> bytes | EvidenceUnavailable:
        """The crop's bytes, verified against its accepted size and SHA-256 before any decode."""
        mismatches = 0
        last_error: EvidenceTransportError | None = None
        for attempt in range(self._evidence_attempts):
            if attempt:
                await asyncio.sleep(self._evidence_backoff * attempt)
            try:
                data = await self._read_evidence_once(leased, observation)
            except EvidenceTransportError as exc:
                last_error = exc
                continue
            if isinstance(data, EvidenceUnavailable):
                return data
            if hashlib.sha256(data).hexdigest() == observation.sha256:
                return data
            mismatches += 1
            last_error = EvidenceTransportError("evidence digest mismatch")
        if mismatches == self._evidence_attempts:
            # The full recorded size, a wrong digest, on every bounded read: the accepted
            # object itself disagrees with its record.
            return EvidenceUnavailable("evidence_integrity_failed")
        raise last_error or EvidenceTransportError("evidence read failed")

    async def _read_evidence_once(self, leased: LeasedAnalysis, observation: LeaseObservation) -> bytes | EvidenceUnavailable:
        lease = leased.lease
        url = f"{self._base}{ROUTE_PREFIX}/{lease.analysis_id}/evidence/{observation.observation_id}"
        try:
            async with self._http.stream("GET", url, headers=self._headers(leased), timeout=self._timeout) as response:
                if response.status_code == httpx.codes.OK:
                    declared = response.headers.get("content-length")
                    if declared is not None and declared != str(observation.size_bytes):
                        raise EvidenceTransportError("evidence length disagrees with the lease", status_code=200)
                    try:
                        data = await _read_bounded(response, observation.size_bytes)
                    except ResponseTooLarge as exc:
                        raise EvidenceTransportError("evidence body exceeds the recorded size", status_code=200) from exc
                    if len(data) != observation.size_bytes:
                        raise EvidenceTransportError("evidence body is not the recorded size", status_code=200)
                    return data
                payload = await _read_bounded(response, _MAXIMUM_CONTROL_RESPONSE_BYTES)
                code = _problem_code(payload)
                if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
                    if code == "visual_attribute_evidence_missing":
                        return EvidenceUnavailable("evidence_missing")
                    if code == "visual_attribute_evidence_integrity_failed":
                        return EvidenceUnavailable("evidence_integrity_failed")
                if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.CONFLICT) and code in _LEASE_CODES:
                    raise AttributeLeaseLost("evidence refused: lease lost", status_code=response.status_code, code=code)
                raise EvidenceTransportError("evidence read refused", status_code=response.status_code, code=code)
        except httpx.HTTPError as exc:
            raise EvidenceTransportError("evidence request failed") from exc

    # --- upload and completion ----------------------------------------------------------

    async def upload(self, leased: LeasedAnalysis, content: bytes) -> UploadResponse:
        if not 1 <= len(content) <= MAXIMUM_PREDICTION_ARTIFACT_BYTES:
            raise AttributeApiError("prediction artefact outside its bound")
        lease = leased.lease
        headers = self._headers(leased) | {
            CONTENT_SHA256_HEADER: hashlib.sha256(content).hexdigest(),
            "Content-Type": PREDICTIONS_MEDIA_TYPE,
        }
        try:
            response = await self._http.put(
                f"{self._base}{ROUTE_PREFIX}/{lease.analysis_id}/predictions", content=content, headers=headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise AttributeApiError("upload request failed") from exc
        payload = response.content[:_MAXIMUM_CONTROL_RESPONSE_BYTES]
        if response.status_code != httpx.codes.OK:
            raise _error(response, payload, "upload refused")
        return _parse(UploadResponse, payload, "upload")

    async def complete(self, leased: LeasedAnalysis, body: bytes) -> CompleteResponse:
        if len(body) > MAXIMUM_COMPLETION_REQUEST_BYTES:
            raise AttributeApiError("completion body outside its bound")
        payload = await self._post_raw(leased, f"{leased.lease.analysis_id}/complete", body, "complete")
        return _parse(CompleteResponse, payload, "complete")

    # --- shared -----------------------------------------------------------------------

    def _headers(self, leased: LeasedAnalysis) -> dict[str, str]:
        return {
            CAPABILITY_HEADER: leased.capability,
            WORKER_HEADER: self._worker_id,
            ATTEMPT_HEADER: str(leased.lease.attempt_count),
        }

    async def _post_json(self, leased: LeasedAnalysis, path: str, body: dict[str, object], operation: str) -> bytes:
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return await self._post_raw(leased, path, encoded, operation)

    async def _post_raw(self, leased: LeasedAnalysis, path: str, body: bytes, operation: str) -> bytes:
        headers = {CAPABILITY_HEADER: leased.capability, "Content-Type": "application/json"}
        try:
            response = await self._http.post(f"{self._base}{ROUTE_PREFIX}/{path}", content=body, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise AttributeApiError(f"{operation} request failed") from exc
        payload = response.content[:_MAXIMUM_CONTROL_RESPONSE_BYTES]
        if response.status_code != httpx.codes.OK:
            raise _error(response, payload, f"{operation} refused")
        return payload


class ResponseTooLarge(AttributeApiError):
    """A body past its bound: reading stopped at the bound, nothing beyond it was buffered."""


async def _read_bounded(response: httpx.Response, limit: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ResponseTooLarge("response exceeds its bound", status_code=response.status_code)
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            raise ResponseTooLarge("response exceeds its bound", status_code=response.status_code)
        chunks.append(chunk)
    return b"".join(chunks)


def _single_header(response: httpx.Response, name: str) -> str | None:
    values = response.headers.get_list(name)
    return values[0] if len(values) == 1 else None


def _problem_code(payload: bytes) -> str | None:
    try:
        document = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    code = document.get("code") if isinstance(document, dict) else None
    return code if isinstance(code, str) and _SAFE_PROBLEM_CODE.fullmatch(code) else None


def _error(response: httpx.Response, payload: bytes, message: str) -> AttributeApiError:
    code = _problem_code(payload)
    if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.CONFLICT) and code in _LEASE_CODES:
        return AttributeLeaseLost(message, status_code=response.status_code, code=code)
    return AttributeApiError(message, status_code=response.status_code, code=code)


def _parse(model, payload: bytes, operation: str):
    try:
        return model.model_validate_json(payload)
    except ValidationError as exc:
        raise AttributeApiError(f"{operation} response is invalid") from exc


def _sanitise(message: str, capability: str) -> str:
    """Bounded diagnostics that can never carry the capability into a persisted field."""
    return message.replace(capability, "[capability]")[:MAXIMUM_FAILURE_MESSAGE_LENGTH]


__all__ = [
    "AttributeApiClient",
    "AttributeApiError",
    "AttributeLeaseLost",
    "EvidenceTransportError",
    "EvidenceUnavailable",
    "LeasedAnalysis",
    "ResponseTooLarge",
]
