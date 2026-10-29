"""The two loops of the ``embeddings`` role (PoC S4; ADR-021 §1, §3–§4).

**Analysis** (one attempt per lease): lease -> concurrent heartbeat -> per leased Track, in lease order, each crop
read through the lease-scoped evidence endpoint with size + SHA-256 verification, decoded, kept when its shorter side
meets the profile's ``minimumCropSide`` -> embed the kept crops -> ``mean-l2-v1`` -> ``embedding-complete-v1``. The
completion body is serialised once and the identical bytes are replayed on an ambiguous outcome. The plate runner's
lease discipline applies: a lost lease cancels the work and is never answered with ``/fail`` or ``/complete``.

Track outcomes: ``embedded`` with the observations actually used (lease order), or ``unavailable`` with
``no_evidence`` (nothing leased), ``evidence_too_small`` (some crop was read and decoded, none met the floor) or
``evidence_unavailable`` (no crop could be read and decoded: missing, integrity-failed or undecodable). Evidence
*transport* that persists fails the attempt as retryable; it is never a Track outcome.

**Text queries** run as a second asyncio loop beside the analysis loop, on their own inference thread, so a long
analysis never blocks an appearance query.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol

from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.embeddings.client import (
    EmbeddingApiError,
    EmbeddingLeaseLost,
    EvidenceTransportError,
    EvidenceUnavailable,
    LeasedAnalysis,
    LeasedTextQuery,
)
from mavi_vision.embeddings.contracts import (
    CONTROL_VERSION,
    FAILURE_EVIDENCE_TRANSPORT,
    FAILURE_OUTPUT_INVALID,
    FAILURE_RUNTIME,
    FAILURE_TEXT_INVALID,
    FAILURE_TEXT_RUNTIME,
    REASON_EVIDENCE_TOO_SMALL,
    REASON_EVIDENCE_UNAVAILABLE,
    REASON_NO_EVIDENCE,
    TRACK_EMBEDDED,
    TRACK_UNAVAILABLE,
    CompleteResponse,
    EmbeddingLease,
    FailResponse,
    HeartbeatResponse,
    LeaseObservation,
    LeaseTrack,
    TextQueryCompleteResponse,
)
from mavi_vision.embeddings.model import (
    EmbeddingModel,
    OutputInvalid,
    encode_vector,
    inspect_crop,
    l2_normalise_rows,
    mean_l2,
)

_LOGGER = logging.getLogger(__name__)
COMPLETION_REPLAY_ATTEMPTS = 3


class EmbeddingApi(Protocol):
    async def lease(self) -> LeasedAnalysis | None: ...
    async def heartbeat(self, leased: LeasedAnalysis) -> HeartbeatResponse: ...
    async def fail(self, leased: LeasedAnalysis, failure_code: str, failure_message: str | None) -> FailResponse: ...
    async def read_evidence(self, leased: LeasedAnalysis, observation: LeaseObservation) -> bytes | EvidenceUnavailable: ...
    async def complete(self, leased: LeasedAnalysis, body: bytes) -> CompleteResponse: ...
    async def lease_text_query(self) -> LeasedTextQuery | None: ...
    async def complete_text_query(self, leased: LeasedTextQuery, body: bytes) -> TextQueryCompleteResponse: ...
    async def fail_text_query(self, leased: LeasedTextQuery, failure_code: str, failure_message: str | None) -> FailResponse: ...


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """What one lease ended as, for logs and tests."""

    status: str  # "completed" | "superseded" | "failed" | "lease_lost" | "abandoned"
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class TrackOutcome:
    track_id: str
    outcome: str
    source_observation_ids: tuple[str, ...] = ()
    embedding: str | None = None
    reason: str | None = None

    def document(self) -> dict[str, object]:
        if self.outcome == TRACK_EMBEDDED:
            return {
                "trackId": self.track_id,
                "outcome": TRACK_EMBEDDED,
                "sourceObservationIds": list(self.source_observation_ids),
                "embedding": self.embedding,
            }
        return {"trackId": self.track_id, "outcome": TRACK_UNAVAILABLE, "reason": self.reason}


class _AttemptFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


PROVENANCE_KEYS = (
    "roleId",
    "identityFingerprint",
    "runtimeProfileId",
    "runtimeVariant",
    "executionProvider",
    "actualDevice",
    "deviceResolutionReason",
    "onnxRuntimeVersion",
    "workerVersion",
)


def encode_completion(lease: EmbeddingLease, worker_id: str, provenance: Mapping[str, object],
                      tracks: tuple[TrackOutcome, ...]) -> bytes:
    """The exact ``embedding-complete-v1`` request bytes (compact JSON, contract member order)."""
    body = {
        "schemaVersion": CONTROL_VERSION,
        "analysisId": str(lease.analysis_id),
        "workerId": worker_id,
        "attemptCount": lease.attempt_count,
        "provenance": {key: provenance[key] for key in PROVENANCE_KEYS},
        "tracks": [track.document() for track in tracks],
    }
    return json.dumps(body, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def encode_text_completion(leased: LeasedTextQuery, worker_id: str, embedding: str) -> bytes:
    lease = leased.lease
    body = {
        "schemaVersion": CONTROL_VERSION,
        "queryId": str(lease.query_id),
        "workerId": worker_id,
        "attemptCount": lease.attempt_count,
        "embedding": embedding,
    }
    return json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class EmbeddingRunner:
    def __init__(
        self,
        api: EmbeddingApi,
        *,
        worker_id: str,
        model: EmbeddingModel,
        dimension: int,
        minimum_crop_side: int,
        provenance: Mapping[str, object],
        heartbeat_interval_seconds: float,
        request_timeout_seconds: float,
        completion_retry_seconds: float = 1.0,
        now_utc: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api = api
        self._worker_id = worker_id
        self._model = model
        self._dimension = dimension
        self._minimum_crop_side = minimum_crop_side
        self._provenance = dict(provenance)
        missing = [key for key in PROVENANCE_KEYS if key not in self._provenance]
        if missing:
            raise ValueError(f"embedding_provenance_incomplete:{missing[0]}")
        self._heartbeat_interval = heartbeat_interval_seconds
        self._request_timeout = request_timeout_seconds
        self._completion_retry = completion_retry_seconds
        self._now = now_utc or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        # One serial lane for image inference: work that outlives a lost attempt finishes before the next may infer.
        self._inference = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-embedding-inference")
        self._inflight: Future | None = None

    def close(self) -> None:
        self._inference.shutdown(wait=True, cancel_futures=True)

    async def run_once(self) -> AttemptOutcome | None:
        """Lease and run one attempt; ``None`` when nothing was leasable."""
        if self._inflight is not None and not self._inflight.done():
            await asyncio.wrap_future(self._inflight)
        leased = await self._api.lease()
        if leased is None:
            return None
        lease = leased.lease
        guard = LeaseGuard(lease.lease_expires_at_utc, now_utc=self._now)
        heartbeat: asyncio.Task | None = None

        def stop_heartbeat() -> None:
            if heartbeat is not None:
                heartbeat.cancel()

        attempt = asyncio.create_task(self._attempt(leased, guard, stop_heartbeat), name="mavi-embedding-attempt")
        heartbeat = asyncio.create_task(self._heartbeat_loop(leased, guard, attempt), name="mavi-embedding-heartbeat")
        try:
            try:
                return await asyncio.shield(attempt)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                caller_cancelling = current is not None and current.cancelling() > 0
                if attempt.cancelled() and guard.is_lost() and not caller_cancelling:
                    _LOGGER.warning("Embedding analysis %s attempt %s lost its lease", lease.analysis_id, lease.attempt_count)
                    return AttemptOutcome("lease_lost")
                attempt.cancel()
                raise
            except (LeaseLostError, EmbeddingLeaseLost):
                guard.mark_lost()
                _LOGGER.warning("Embedding analysis %s attempt %s lost its lease", lease.analysis_id, lease.attempt_count)
                return AttemptOutcome("lease_lost")
            except _AttemptFailed as failure:
                return await self._fail(leased, guard, failure.code, failure.message)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            if not attempt.done():
                attempt.cancel()
                await asyncio.gather(attempt, return_exceptions=True)

    # --- the attempt ---------------------------------------------------------------------------------

    async def _attempt(self, leased: LeasedAnalysis, guard: LeaseGuard, stop_heartbeat: Callable[[], None]) -> AttemptOutcome:
        lease = leased.lease
        try:
            tracks = []
            for track in lease.tracks:
                tracks.append(await self._track(leased, guard, track))
            body = encode_completion(lease, self._worker_id, self._provenance, tuple(tracks))
        except OutputInvalid as exc:
            raise _AttemptFailed(FAILURE_OUTPUT_INVALID, str(exc)) from exc
        guard.check_owned()
        stop_heartbeat()
        return await self._complete(leased, body)

    async def _track(self, leased: LeasedAnalysis, guard: LeaseGuard, track: LeaseTrack) -> TrackOutcome:
        track_id = str(track.track_id)
        if not track.observations:
            return TrackOutcome(track_id, TRACK_UNAVAILABLE, reason=REASON_NO_EVIDENCE)
        decoded_any = False
        kept_ids: list[str] = []
        kept_crops: list[bytes] = []
        for observation in track.observations:
            guard.check_owned()
            try:
                data = await self._api.read_evidence(leased, observation)
            except EvidenceTransportError as exc:
                # Transport is never evidence: the attempt fails as retryable.
                raise _AttemptFailed(FAILURE_EVIDENCE_TRANSPORT, "accepted evidence could not be read") from exc
            if isinstance(data, EvidenceUnavailable):
                continue
            decoded = await self._infer(inspect_crop, data)
            if decoded is None:
                continue
            decoded_any = True
            if decoded.shorter_side >= self._minimum_crop_side:
                kept_ids.append(str(observation.observation_id))
                kept_crops.append(data)
        if not kept_crops:
            reason = REASON_EVIDENCE_TOO_SMALL if decoded_any else REASON_EVIDENCE_UNAVAILABLE
            return TrackOutcome(track_id, TRACK_UNAVAILABLE, reason=reason)
        guard.check_owned()
        try:
            rows = await self._infer(self._model.embed_images, kept_crops)
        except OutputInvalid:
            raise
        except Exception as exc:  # noqa: BLE001 - any model fault fails the attempt, retryable
            raise _AttemptFailed(FAILURE_RUNTIME, f"image embedding failed ({type(exc).__name__})") from exc
        if getattr(rows, "shape", (None,))[0] != len(kept_crops):
            raise OutputInvalid("embedding output row count does not match the crops")
        vector = mean_l2(rows, self._dimension)
        return TrackOutcome(track_id, TRACK_EMBEDDED, tuple(kept_ids), encode_vector(vector, self._dimension))

    async def _infer(self, function, *args):
        # Off the event loop: the heartbeat keeps its schedule while crops are decoded and embedded.
        self._inflight = self._inference.submit(function, *args)
        return await asyncio.wrap_future(self._inflight)

    async def _complete(self, leased: LeasedAnalysis, body: bytes) -> AttemptOutcome:
        lease = leased.lease
        for attempt in range(COMPLETION_REPLAY_ATTEMPTS):
            if attempt:
                await self._sleep(self._completion_retry * attempt)
            try:
                response = await self._api.complete(leased, body)
            except EmbeddingLeaseLost:
                raise
            except EmbeddingApiError as exc:
                if exc.status_code == 422 and exc.code == "embedding_completion_invalid":
                    # The platform judged this output invalid: the one refusal that is the worker's own fault.
                    raise _AttemptFailed(FAILURE_OUTPUT_INVALID, f"completion refused ({exc.code})") from exc
                if exc.status_code is not None and exc.status_code < 500:
                    # Any other refusal (an identity no longer preferred after a release change, a size limit, a
                    # stale attempt) is not evidence of bad output: abandon the attempt and let the platform reclaim
                    # it, never burn the unit with a non-retryable failure.
                    _LOGGER.warning("Embedding analysis %s attempt %s: completion refused (%s %s); abandoning the attempt",
                                    lease.analysis_id, lease.attempt_count, exc.status_code, exc.code)
                    return AttemptOutcome("abandoned")
                # Transport or an ambiguous outcome: the identical bytes are replayed.
                continue
            _LOGGER.info("Embedding analysis %s attempt %s %s: %s Tracks embedded, %s unavailable", lease.analysis_id,
                         lease.attempt_count, response.status, response.tracks_embedded, response.tracks_unavailable)
            return AttemptOutcome(response.status)
        _LOGGER.error("Embedding analysis %s attempt %s: completion outcome unknown; the platform reclaims it",
                      lease.analysis_id, lease.attempt_count)
        return AttemptOutcome("abandoned")

    async def _fail(self, leased: LeasedAnalysis, guard: LeaseGuard, code: str, message: str) -> AttemptOutcome:
        lease = leased.lease
        _LOGGER.warning("Embedding analysis %s attempt %s failed: %s", lease.analysis_id, lease.attempt_count, code)
        if guard.is_lost():
            return AttemptOutcome("lease_lost", code)
        try:
            await self._api.fail(leased, code, message)
        except EmbeddingLeaseLost:
            return AttemptOutcome("lease_lost", code)
        except EmbeddingApiError:
            _LOGGER.error("Embedding analysis %s attempt %s: failure could not be reported", lease.analysis_id, lease.attempt_count)
        return AttemptOutcome("failed", code)

    # --- heartbeat ---------------------------------------------------------------------------------------

    async def _heartbeat_loop(self, leased: LeasedAnalysis, guard: LeaseGuard, work: asyncio.Task | None) -> None:
        deadline = leased.lease.lease_expires_at_utc
        try:
            while True:
                await self._sleep(self._wait_seconds(deadline))
                remaining = (deadline - self._now()).total_seconds()
                if remaining <= 0:
                    raise LeaseLostError()
                try:
                    response = await asyncio.wait_for(self._api.heartbeat(leased), timeout=min(remaining, self._request_timeout))
                except EmbeddingLeaseLost:
                    raise LeaseLostError() from None
                except (EmbeddingApiError, asyncio.TimeoutError):
                    continue
                if response.lease_expires_at_utc <= self._now():
                    raise LeaseLostError()
                deadline = response.lease_expires_at_utc
                guard.update_deadline(deadline)
        except LeaseLostError:
            guard.mark_lost()
            if work is not None and not work.done():
                work.cancel()

    def _wait_seconds(self, deadline: datetime) -> float:
        remaining = (deadline - self._now()).total_seconds()
        if remaining <= 0:
            return 0.0
        return max(0.0, min(self._heartbeat_interval, remaining - min(self._request_timeout, remaining / 2.0)))


class TextQueryRunner:
    """One appearance text query per call: lease -> embed on its own thread -> complete, or fail."""

    def __init__(
        self,
        api: EmbeddingApi,
        *,
        worker_id: str,
        model: EmbeddingModel,
        dimension: int,
        maximum_characters: int,
        completion_retry_seconds: float = 0.25,
        now_utc: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api = api
        self._worker_id = worker_id
        self._model = model
        self._dimension = dimension
        self._maximum_characters = maximum_characters
        self._completion_retry = completion_retry_seconds
        self._now = now_utc or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        self._inference = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-embedding-text")

    def close(self) -> None:
        self._inference.shutdown(wait=True, cancel_futures=True)

    async def run_once(self) -> AttemptOutcome | None:
        leased = await self._api.lease_text_query()
        if leased is None:
            return None
        lease = leased.lease
        text = lease.text
        if text != text.strip() or not 1 <= len(text) <= self._maximum_characters:
            return await self._fail(leased, FAILURE_TEXT_INVALID, "text is not a normalised appearance query")
        try:
            rows = await asyncio.wrap_future(self._inference.submit(self._model.embed_texts, [text]))
            if getattr(rows, "shape", (None,))[0] != 1:
                raise OutputInvalid("text embedding output row count is not 1")
            embedding = encode_vector(l2_normalise_rows(rows, self._dimension)[0], self._dimension)
        except Exception as exc:  # noqa: BLE001 - any text-tower fault is retryable
            return await self._fail(leased, FAILURE_TEXT_RUNTIME, f"text embedding failed ({type(exc).__name__})")
        if lease.lease_expires_at_utc <= self._now():
            _LOGGER.warning("Embedding text query %s attempt %s lost its lease", lease.query_id, lease.attempt_count)
            return AttemptOutcome("lease_lost")
        body = encode_text_completion(leased, self._worker_id, embedding)
        for attempt in range(COMPLETION_REPLAY_ATTEMPTS):
            if attempt:
                await self._sleep(self._completion_retry * attempt)
            try:
                await self._api.complete_text_query(leased, body)
            except EmbeddingLeaseLost:
                _LOGGER.warning("Embedding text query %s attempt %s lost its lease", lease.query_id, lease.attempt_count)
                return AttemptOutcome("lease_lost")
            except EmbeddingApiError as exc:
                if exc.status_code is not None and exc.status_code < 500:
                    return await self._fail(leased, FAILURE_TEXT_INVALID, f"text completion refused ({exc.code})")
                continue
            _LOGGER.info("Embedding text query %s attempt %s completed", lease.query_id, lease.attempt_count)
            return AttemptOutcome("completed")
        return AttemptOutcome("abandoned")

    async def _fail(self, leased: LeasedTextQuery, code: str, message: str) -> AttemptOutcome:
        lease = leased.lease
        _LOGGER.warning("Embedding text query %s attempt %s failed: %s", lease.query_id, lease.attempt_count, code)
        if lease.lease_expires_at_utc <= self._now():
            return AttemptOutcome("lease_lost", code)
        try:
            await self._api.fail_text_query(leased, code, message)
        except EmbeddingLeaseLost:
            return AttemptOutcome("lease_lost", code)
        except EmbeddingApiError:
            _LOGGER.error("Embedding text query %s attempt %s: failure could not be reported", lease.query_id, lease.attempt_count)
        return AttemptOutcome("failed", code)


__all__ = [
    "AttemptOutcome",
    "COMPLETION_REPLAY_ATTEMPTS",
    "EmbeddingRunner",
    "PROVENANCE_KEYS",
    "TextQueryRunner",
    "TrackOutcome",
    "encode_completion",
    "encode_text_completion",
]
