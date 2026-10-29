"""HTTP client of the face control plane ``mavi-face-control-v1`` (PoC S6; ADR-022).

The transport rules of the S4 embeddings client, applied to the face plane.

The lease capability is read from, and sent in, the ``X-Mavi-Lease-Capability`` header only. It is never part of a
URL, a body, an exception message or a log line: errors carry the HTTP status and the platform's validated problem
code, nothing else.

Evidence reads distinguish **transport** from **authority** (ADR-013 amendment 2026-09-28, item 3). A timeout, a
connection reset, a 5xx, a short body or a body that fails its digest once is transport: it is retried within the
lease and, if it persists, fails the *attempt* as retryable (``face_evidence_transport_failed``). Only the
platform's explicit 422 (``face_evidence_missing`` / ``face_evidence_integrity_failed``) or bytes that fail
their accepted SHA-256 on every bounded read make the crop unavailable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from mavi_vision.common.control_plane import _lease_token
from mavi_vision.faces.contracts import (
    ANALYSIS_ROUTE_PREFIX,
    ATTEMPT_HEADER,
    CAPABILITY_HEADER,
    CONTROL_VERSION,
    EVIDENCE_INTEGRITY_FAILED_CODE,
    EVIDENCE_MISSING_CODE,
    LEASE_LOST_CODES,
    MAXIMUM_COMPLETION_REQUEST_BYTES,
    MAXIMUM_FAILURE_MESSAGE_LENGTH,
    MAXIMUM_LEASE_RESPONSE_BYTES,
    MAXIMUM_QUERY_LEASE_BYTES,
    QUERY_IMAGE_MISSING_CODE,
    QUERY_ROUTE_PREFIX,
    WORKER_HEADER,
    CompleteResponse,
    FaceLease,
    FaceQueryLease,
    FailResponse,
    HeartbeatResponse,
    LeaseObservation,
    QueryCompleteResponse,
)
from mavi_vision.faces.identity import FaceIdentity

_SAFE_PROBLEM_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,95}$", re.ASCII)
_MAXIMUM_CONTROL_RESPONSE_BYTES: Final = 64 * 1024
_Model = TypeVar("_Model", bound=BaseModel)


class FaceApiError(RuntimeError):
    """A sanitised control-plane error: the status and a validated code, never free text."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class FaceLeaseLost(FaceApiError):
    """The platform no longer recognises this attempt's ownership: stop, never retry, never /fail."""


class EvidenceTransportError(FaceApiError):
    """An evidence read that did not produce an authoritative answer (retryable)."""


class ResponseTooLarge(FaceApiError):
    """A body past its bound: reading stopped at the bound, nothing beyond it was buffered."""


@dataclass(frozen=True, slots=True)
class EvidenceUnavailable:
    """An authoritative, platform-attested condition of one accepted crop."""

    reason: str


@dataclass(frozen=True, slots=True)
class LeasedAnalysis:
    """A lease and its capability, held apart so the capability is never serialised with it."""

    lease: FaceLease
    capability: str

    def __repr__(self) -> str:  # never let a repr or traceback print the capability
        return f"LeasedAnalysis(analysis_id={self.lease.analysis_id}, attempt={self.lease.attempt_count})"


@dataclass(frozen=True, slots=True)
class LeasedQuery:
    lease: FaceQueryLease
    capability: str

    def __repr__(self) -> str:
        return f"LeasedQuery(query_id={self.lease.query_id}, attempt={self.lease.attempt_count})"


class QueryImageRefused(FaceApiError):
    """The platform holds no readable image for this query, or its bytes never match the leased digest."""


class FaceApiClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        worker_id: str,
        identity: FaceIdentity,
        request_timeout_seconds: float,
        evidence_read_attempts: int = 3,
        evidence_retry_backoff_seconds: float = 0.5,
        http_client: httpx.AsyncClient | None = None,
        verify: str | bool = True,
    ) -> None:
        self._base = api_base_url.rstrip("/")
        self._worker_id = worker_id
        self._identity = identity
        self._timeout = request_timeout_seconds
        self._evidence_attempts = evidence_read_attempts
        self._evidence_backoff = evidence_retry_backoff_seconds
        self._http = http_client or httpx.AsyncClient(timeout=request_timeout_seconds, verify=verify)

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- analysis lease ---------------------------------------------------------------------------

    async def lease(self) -> LeasedAnalysis | None:
        payload, capability = await self._lease(f"{ANALYSIS_ROUTE_PREFIX}/lease", MAXIMUM_LEASE_RESPONSE_BYTES)
        if payload is None:
            return None
        lease = _parse(FaceLease, payload, "lease")
        if lease.worker_id != self._worker_id or not self._identity.matches(lease.identity):
            raise FaceApiError("lease response names another worker or identity")
        return LeasedAnalysis(lease, capability)

    async def heartbeat(self, leased: LeasedAnalysis) -> HeartbeatResponse:
        lease = leased.lease
        body = {
            "schemaVersion": CONTROL_VERSION,
            "analysisId": str(lease.analysis_id),
            "workerId": self._worker_id,
            "attemptCount": lease.attempt_count,
        }
        payload = await self._post(leased.capability, f"{ANALYSIS_ROUTE_PREFIX}/{lease.analysis_id}/heartbeat", _json(body), "heartbeat")
        return _parse(HeartbeatResponse, payload, "heartbeat")

    async def fail(self, leased: LeasedAnalysis, failure_code: str, failure_message: str | None) -> FailResponse:
        lease = leased.lease
        body = {
            "schemaVersion": CONTROL_VERSION,
            "analysisId": str(lease.analysis_id),
            "workerId": self._worker_id,
            "attemptCount": lease.attempt_count,
            "failureCode": failure_code,
            "failureMessage": None if failure_message is None else _sanitise(failure_message, leased.capability),
        }
        payload = await self._post(leased.capability, f"{ANALYSIS_ROUTE_PREFIX}/{lease.analysis_id}/fail", _json(body), "fail")
        return _parse(FailResponse, payload, "fail")

    async def complete(self, leased: LeasedAnalysis, body: bytes) -> CompleteResponse:
        if len(body) > MAXIMUM_COMPLETION_REQUEST_BYTES:
            raise FaceApiError("completion body outside its bound")
        payload = await self._post(leased.capability, f"{ANALYSIS_ROUTE_PREFIX}/{leased.lease.analysis_id}/complete", body, "complete")
        return _parse(CompleteResponse, payload, "complete")

    # --- evidence -----------------------------------------------------------------------------------

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
            # The full recorded size, a wrong digest, on every bounded read: the accepted object itself disagrees.
            return EvidenceUnavailable("evidence_integrity_failed")
        raise last_error or EvidenceTransportError("evidence read failed")

    async def _read_evidence_once(self, leased: LeasedAnalysis, observation: LeaseObservation) -> bytes | EvidenceUnavailable:
        lease = leased.lease
        url = f"{self._base}{ANALYSIS_ROUTE_PREFIX}/{lease.analysis_id}/evidence/{observation.observation_id}"
        headers = {
            CAPABILITY_HEADER: leased.capability,
            WORKER_HEADER: self._worker_id,
            ATTEMPT_HEADER: str(lease.attempt_count),
        }
        try:
            async with self._http.stream("GET", url, headers=headers, timeout=self._timeout) as response:
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
                try:
                    payload = await _read_bounded(response, _MAXIMUM_CONTROL_RESPONSE_BYTES)
                except ResponseTooLarge as exc:
                    raise EvidenceTransportError("evidence error body exceeds its bound", status_code=response.status_code) from exc
                code = _problem_code(payload)
                if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
                    if code == EVIDENCE_MISSING_CODE:
                        return EvidenceUnavailable("evidence_missing")
                    if code == EVIDENCE_INTEGRITY_FAILED_CODE:
                        return EvidenceUnavailable("evidence_integrity_failed")
                if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.CONFLICT) and code in LEASE_LOST_CODES:
                    raise FaceLeaseLost("evidence refused: lease lost", status_code=response.status_code, code=code)
                raise EvidenceTransportError("evidence read refused", status_code=response.status_code, code=code)
        except httpx.HTTPError as exc:
            raise EvidenceTransportError("evidence request failed") from exc

    # --- transient query images ----------------------------------------------------------------------

    async def lease_query(self) -> LeasedQuery | None:
        payload, capability = await self._lease(f"{QUERY_ROUTE_PREFIX}/lease", MAXIMUM_QUERY_LEASE_BYTES)
        if payload is None:
            return None
        lease = _parse(FaceQueryLease, payload, "query lease")
        if lease.worker_id != self._worker_id or not self._identity.matches(lease.identity):
            raise FaceApiError("query lease names another worker or identity")
        return LeasedQuery(lease, capability)

    async def read_query_image(self, leased: LeasedQuery) -> bytes:
        """The query image, verified against its leased size and SHA-256; transport is retried within the lease.

        A 422 ``face_query_image_missing``, or the recorded size with a wrong digest on every bounded read, is
        :class:`QueryImageRefused` (the query cannot be served); anything else that persists is transport.
        """
        lease = leased.lease
        url = f"{self._base}{QUERY_ROUTE_PREFIX}/{lease.query_id}/image"
        headers = {CAPABILITY_HEADER: leased.capability, WORKER_HEADER: self._worker_id, ATTEMPT_HEADER: str(lease.attempt_count)}
        mismatches = 0
        last_error: FaceApiError | None = None
        for attempt in range(self._evidence_attempts):
            if attempt:
                await asyncio.sleep(self._evidence_backoff * attempt)
            try:
                async with self._http.stream("GET", url, headers=headers, timeout=self._timeout) as response:
                    if response.status_code != httpx.codes.OK:
                        payload = await _read_bounded(response, _MAXIMUM_CONTROL_RESPONSE_BYTES)
                        code = _problem_code(payload)
                        if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY and code == QUERY_IMAGE_MISSING_CODE:
                            raise QueryImageRefused("query image missing", status_code=422, code=code)
                        error = _error_from(response.status_code, payload, "query image refused")
                        if isinstance(error, FaceLeaseLost):
                            raise error
                        last_error = EvidenceTransportError("query image refused", status_code=response.status_code, code=code)
                        continue
                    data = await _read_bounded(response, lease.image.size_bytes)
            except ResponseTooLarge:
                last_error = EvidenceTransportError("query image exceeds its recorded size")
                continue
            except httpx.HTTPError:
                last_error = EvidenceTransportError("query image request failed")
                continue
            if len(data) == lease.image.size_bytes and hashlib.sha256(data).hexdigest() == lease.image.sha256:
                return data
            if len(data) == lease.image.size_bytes:
                mismatches += 1
            last_error = EvidenceTransportError("query image digest mismatch")
        if mismatches == self._evidence_attempts:
            raise QueryImageRefused("query image never matches its digest")
        raise last_error or EvidenceTransportError("query image read failed")

    async def complete_query(self, leased: LeasedQuery, body: bytes) -> QueryCompleteResponse:
        payload = await self._post(leased.capability, f"{QUERY_ROUTE_PREFIX}/{leased.lease.query_id}/complete", body, "query complete")
        return _parse(QueryCompleteResponse, payload, "query complete")

    async def fail_query(self, leased: LeasedQuery, failure_code: str, failure_message: str | None) -> FailResponse:
        lease = leased.lease
        body = {
            "schemaVersion": CONTROL_VERSION,
            "queryId": str(lease.query_id),
            "workerId": self._worker_id,
            "attemptCount": lease.attempt_count,
            "failureCode": failure_code,
            "failureMessage": None if failure_message is None else _sanitise(failure_message, leased.capability),
        }
        payload = await self._post(leased.capability, f"{QUERY_ROUTE_PREFIX}/{lease.query_id}/fail", _json(body), "query fail")
        return _parse(FailResponse, payload, "query fail")

    # --- shared ---------------------------------------------------------------------------------------

    async def _lease(self, path: str, limit: int) -> tuple[bytes | None, str]:
        body = {"schemaVersion": CONTROL_VERSION, "workerId": self._worker_id, "identityFingerprint": self._identity.fingerprint}
        try:
            async with self._http.stream("POST", f"{self._base}{path}", content=_json(body),
                                         headers={"Content-Type": "application/json"}, timeout=self._timeout) as response:
                if response.status_code == httpx.codes.NO_CONTENT:
                    return None, ""
                payload = await _read_bounded(response, limit)
                if response.status_code != httpx.codes.OK:
                    raise _error_from(response.status_code, payload, "lease refused")
                values = response.headers.get_list(CAPABILITY_HEADER)
        except httpx.HTTPError as exc:
            raise FaceApiError("lease request failed") from exc
        if len(values) != 1:
            raise FaceApiError("lease response carried no single capability")
        try:
            capability = _lease_token(values[0])
        except ValueError as exc:
            raise FaceApiError("lease response capability is malformed") from exc
        return payload, capability

    async def _post(self, capability: str, path: str, body: bytes, operation: str) -> bytes:
        headers = {CAPABILITY_HEADER: capability, "Content-Type": "application/json"}
        try:
            async with self._http.stream("POST", f"{self._base}{path}", content=body, headers=headers, timeout=self._timeout) as response:
                status = response.status_code
                payload = await _read_bounded(response, _MAXIMUM_CONTROL_RESPONSE_BYTES)
        except httpx.HTTPError as exc:
            raise FaceApiError(f"{operation} request failed") from exc
        if status != httpx.codes.OK:
            raise _error_from(status, payload, f"{operation} refused")
        return payload


def _json(body: dict[str, object]) -> bytes:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("ascii")


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


def _problem_code(payload: bytes) -> str | None:
    try:
        document = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    code = document.get("code") if isinstance(document, dict) else None
    return code if isinstance(code, str) and _SAFE_PROBLEM_CODE.fullmatch(code) else None


def _error_from(status: int, payload: bytes, message: str) -> FaceApiError:
    code = _problem_code(payload)
    if status in (httpx.codes.NOT_FOUND, httpx.codes.CONFLICT) and code in LEASE_LOST_CODES:
        return FaceLeaseLost(message, status_code=status, code=code)
    return FaceApiError(message, status_code=status, code=code)


def _parse(model: type[_Model], payload: bytes, operation: str) -> _Model:
    try:
        return model.model_validate_json(payload)
    except ValidationError as exc:
        raise FaceApiError(f"{operation} response is invalid") from exc


def _sanitise(message: str, capability: str) -> str:
    """Bounded diagnostics that can never carry the capability into a persisted field."""
    return message.replace(capability, "[capability]")[:MAXIMUM_FAILURE_MESSAGE_LENGTH]


__all__ = [
    "FaceApiClient",
    "FaceApiError",
    "FaceLeaseLost",
    "EvidenceTransportError",
    "EvidenceUnavailable",
    "LeasedAnalysis",
    "LeasedQuery",
    "QueryImageRefused",
    "ResponseTooLarge",
]
