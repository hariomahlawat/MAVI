"""HTTP client of the embedding control plane ``mavi-embedding-control-v1`` (PoC S4; ADR-021 §3–§4).

The plate client's transport rules, applied to the embedding plane.

The lease capability is read from, and sent in, the ``X-Mavi-Lease-Capability`` header only. It is never part of a
URL, a body, an exception message or a log line: errors carry the HTTP status and the platform's validated problem
code, nothing else.

Evidence reads distinguish **transport** from **authority** (ADR-013 amendment 2026-09-28, item 3). A timeout, a
connection reset, a 5xx, a short body or a body that fails its digest once is transport: it is retried within the
lease and, if it persists, fails the *attempt* as retryable (``embedding_evidence_transport_failed``). Only the
platform's explicit 422 (``embedding_evidence_missing`` / ``embedding_evidence_integrity_failed``) or bytes that fail
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
from mavi_vision.embeddings.contracts import (
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
    MAXIMUM_TEXT_QUERY_LEASE_BYTES,
    TEXT_QUERY_ROUTE_PREFIX,
    WORKER_HEADER,
    CompleteResponse,
    EmbeddingLease,
    FailResponse,
    HeartbeatResponse,
    LeaseObservation,
    TextQueryCompleteResponse,
    TextQueryLease,
)
from mavi_vision.embeddings.identity import EmbeddingIdentity

_SAFE_PROBLEM_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,95}$", re.ASCII)
_MAXIMUM_CONTROL_RESPONSE_BYTES: Final = 64 * 1024
_Model = TypeVar("_Model", bound=BaseModel)


class EmbeddingApiError(RuntimeError):
    """A sanitised control-plane error: the status and a validated code, never free text."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class EmbeddingLeaseLost(EmbeddingApiError):
    """The platform no longer recognises this attempt's ownership: stop, never retry, never /fail."""


class EvidenceTransportError(EmbeddingApiError):
    """An evidence read that did not produce an authoritative answer (retryable)."""


class ResponseTooLarge(EmbeddingApiError):
    """A body past its bound: reading stopped at the bound, nothing beyond it was buffered."""


@dataclass(frozen=True, slots=True)
class EvidenceUnavailable:
    """An authoritative, platform-attested condition of one accepted crop."""

    reason: str


@dataclass(frozen=True, slots=True)
class LeasedAnalysis:
    """A lease and its capability, held apart so the capability is never serialised with it."""

    lease: EmbeddingLease
    capability: str

    def __repr__(self) -> str:  # never let a repr or traceback print the capability
        return f"LeasedAnalysis(analysis_id={self.lease.analysis_id}, attempt={self.lease.attempt_count})"


@dataclass(frozen=True, slots=True)
class LeasedTextQuery:
    lease: TextQueryLease
    capability: str

    def __repr__(self) -> str:
        return f"LeasedTextQuery(query_id={self.lease.query_id}, attempt={self.lease.attempt_count})"


class EmbeddingApiClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        worker_id: str,
        identity: EmbeddingIdentity,
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
        lease = _parse(EmbeddingLease, payload, "lease")
        if lease.worker_id != self._worker_id or not self._identity.matches(lease.identity):
            raise EmbeddingApiError("lease response names another worker or identity")
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
            raise EmbeddingApiError("completion body outside its bound")
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
                    raise EmbeddingLeaseLost("evidence refused: lease lost", status_code=response.status_code, code=code)
                raise EvidenceTransportError("evidence read refused", status_code=response.status_code, code=code)
        except httpx.HTTPError as exc:
            raise EvidenceTransportError("evidence request failed") from exc

    # --- appearance text queries --------------------------------------------------------------------

    async def lease_text_query(self) -> LeasedTextQuery | None:
        payload, capability = await self._lease(f"{TEXT_QUERY_ROUTE_PREFIX}/lease", MAXIMUM_TEXT_QUERY_LEASE_BYTES)
        if payload is None:
            return None
        lease = _parse(TextQueryLease, payload, "text query lease")
        if lease.worker_id != self._worker_id or lease.identity_fingerprint != self._identity.fingerprint:
            raise EmbeddingApiError("text query lease names another worker or identity")
        return LeasedTextQuery(lease, capability)

    async def complete_text_query(self, leased: LeasedTextQuery, body: bytes) -> TextQueryCompleteResponse:
        payload = await self._post(leased.capability, f"{TEXT_QUERY_ROUTE_PREFIX}/{leased.lease.query_id}/complete", body, "text complete")
        return _parse(TextQueryCompleteResponse, payload, "text complete")

    async def fail_text_query(self, leased: LeasedTextQuery, failure_code: str, failure_message: str | None) -> FailResponse:
        lease = leased.lease
        body = {
            "schemaVersion": CONTROL_VERSION,
            "queryId": str(lease.query_id),
            "workerId": self._worker_id,
            "attemptCount": lease.attempt_count,
            "failureCode": failure_code,
            "failureMessage": None if failure_message is None else _sanitise(failure_message, leased.capability),
        }
        payload = await self._post(leased.capability, f"{TEXT_QUERY_ROUTE_PREFIX}/{lease.query_id}/fail", _json(body), "text fail")
        return _parse(FailResponse, payload, "text fail")

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
            raise EmbeddingApiError("lease request failed") from exc
        if len(values) != 1:
            raise EmbeddingApiError("lease response carried no single capability")
        try:
            capability = _lease_token(values[0])
        except ValueError as exc:
            raise EmbeddingApiError("lease response capability is malformed") from exc
        return payload, capability

    async def _post(self, capability: str, path: str, body: bytes, operation: str) -> bytes:
        headers = {CAPABILITY_HEADER: capability, "Content-Type": "application/json"}
        try:
            async with self._http.stream("POST", f"{self._base}{path}", content=body, headers=headers, timeout=self._timeout) as response:
                status = response.status_code
                payload = await _read_bounded(response, _MAXIMUM_CONTROL_RESPONSE_BYTES)
        except httpx.HTTPError as exc:
            raise EmbeddingApiError(f"{operation} request failed") from exc
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


def _error_from(status: int, payload: bytes, message: str) -> EmbeddingApiError:
    code = _problem_code(payload)
    if status in (httpx.codes.NOT_FOUND, httpx.codes.CONFLICT) and code in LEASE_LOST_CODES:
        return EmbeddingLeaseLost(message, status_code=status, code=code)
    return EmbeddingApiError(message, status_code=status, code=code)


def _parse(model: type[_Model], payload: bytes, operation: str) -> _Model:
    try:
        return model.model_validate_json(payload)
    except ValidationError as exc:
        raise EmbeddingApiError(f"{operation} response is invalid") from exc


def _sanitise(message: str, capability: str) -> str:
    """Bounded diagnostics that can never carry the capability into a persisted field."""
    return message.replace(capability, "[capability]")[:MAXIMUM_FAILURE_MESSAGE_LENGTH]


__all__ = [
    "EmbeddingApiClient",
    "EmbeddingApiError",
    "EmbeddingLeaseLost",
    "EvidenceTransportError",
    "EvidenceUnavailable",
    "LeasedAnalysis",
    "LeasedTextQuery",
    "ResponseTooLarge",
]
