"""One attribute attempt, end to end, through the platform's lease plane (S2b plan §9–§14).

lease -> (concurrent heartbeat) -> per crop: authorised read, size + SHA-256 verification,
decode, score -> aggregate -> canonical artefact -> upload -> completion. The heartbeat is its
own task from the moment of the lease: a slow crop or a slow upload never starves renewal,
and a lost lease cancels the work at once. A lost lease is never answered with ``/fail``: the
attempt is no longer this worker's to end.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol

from mavi_vision.attributes.client import (
    AttributeApiError,
    AttributeLeaseLost,
    EvidenceTransportError,
    EvidenceUnavailable,
    LeasedAnalysis,
)
from mavi_vision.attributes.contracts import CompleteResponse, FailResponse, HeartbeatResponse, LeaseObservation, UploadResponse
from mavi_vision.attributes.inference import AttributeInferencer, CropDecodeError, VerifiedCrop
from mavi_vision.attributes.pipeline import AttributePipelineProfile
from mavi_vision.attributes.predictions import (
    ObservationResult,
    OutputInvalid,
    TrackResult,
    aggregate_track,
    encode_completion,
    encode_predictions,
)
from mavi_vision.common.lease import LeaseGuard, LeaseLostError

_LOGGER = logging.getLogger(__name__)
COMPLETION_REPLAY_ATTEMPTS = 3
_ARTIFACT_INTEGRITY_FAILED = "vision_result_artifact_integrity_failed"


class AttributeApi(Protocol):
    async def lease(self) -> LeasedAnalysis | None: ...
    async def heartbeat(self, leased: LeasedAnalysis) -> HeartbeatResponse: ...
    async def fail(self, leased: LeasedAnalysis, failure_code: str, failure_message: str | None) -> FailResponse: ...
    async def read_evidence(self, leased: LeasedAnalysis, observation: LeaseObservation) -> bytes | EvidenceUnavailable: ...
    async def upload(self, leased: LeasedAnalysis, content: bytes) -> UploadResponse: ...
    async def complete(self, leased: LeasedAnalysis, body: bytes) -> CompleteResponse: ...


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """What one lease ended as, for logs and tests."""

    status: str  # "completed" | "superseded" | "failed" | "lease_lost" | "abandoned"
    failure_code: str | None = None


class _AttemptFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


class AttributeRunner:
    def __init__(
        self,
        api: AttributeApi,
        *,
        worker_id: str,
        profile: AttributePipelineProfile,
        inferencer: AttributeInferencer,
        provenance: Mapping[str, object],
        heartbeat_interval_seconds: float,
        request_timeout_seconds: float,
        completion_retry_seconds: float = 1.0,
        now_utc: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api = api
        self._worker_id = worker_id
        self._profile = profile
        self._inferencer = inferencer
        self._provenance = dict(provenance)
        self._heartbeat_interval = heartbeat_interval_seconds
        self._request_timeout = request_timeout_seconds
        self._completion_retry = completion_retry_seconds
        self._now = now_utc or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        # One serial lane for inference: a scoring call that outlives a lost attempt finishes
        # before the next attempt may score, so a model is never entered concurrently.
        self._inference = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-attribute-inference")
        self._inflight: Future | None = None

    def close(self) -> None:
        self._inference.shutdown(wait=True, cancel_futures=True)

    async def run_once(self) -> AttemptOutcome | None:
        """Lease and run one attempt; ``None`` when nothing was leasable."""
        # Never lease while the previous attempt's scoring is still running.
        if self._inflight is not None and not self._inflight.done():
            await asyncio.wrap_future(self._inflight)
        leased = await self._api.lease()
        if leased is None:
            return None
        lease = leased.lease
        guard = LeaseGuard(lease.lease_expires_at_utc, now_utc=self._now)
        heartbeat: asyncio.Task | None = None

        def stop_heartbeat() -> None:
            # Called before /complete: from then on ownership is the platform's Phase C
            # re-fence to decide, and a renewal must neither cancel the publication nor turn
            # its "not running" answer into a false lease loss.
            if heartbeat is not None:
                heartbeat.cancel()

        # The attempt is its own task, so a lost lease cancels exactly the attempt and nothing
        # of the caller's.
        attempt = asyncio.create_task(self._attempt(leased, guard, stop_heartbeat), name="mavi-attribute-attempt")
        heartbeat = asyncio.create_task(self._heartbeat_loop(leased, guard, attempt), name="mavi-attribute-heartbeat")
        try:
            try:
                return await asyncio.shield(attempt)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                caller_cancelling = current is not None and current.cancelling() > 0
                if attempt.cancelled() and guard.is_lost() and not caller_cancelling:
                    # Our own heartbeat cancelled the attempt: the lease is gone.
                    _LOGGER.warning("Attribute analysis %s attempt %s lost its lease", lease.analysis_id, lease.attempt_count)
                    return AttemptOutcome("lease_lost")
                # The caller is being cancelled (shutdown): stop the attempt too, and propagate.
                attempt.cancel()
                raise
            except (LeaseLostError, AttributeLeaseLost):
                guard.mark_lost()
                _LOGGER.warning("Attribute analysis %s attempt %s lost its lease", lease.analysis_id, lease.attempt_count)
                return AttemptOutcome("lease_lost")
            except _AttemptFailed as failure:
                return await self._fail(leased, guard, failure.code, failure.message)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            if not attempt.done():
                attempt.cancel()
                await asyncio.gather(attempt, return_exceptions=True)

    # --- the attempt -------------------------------------------------------------------

    async def _attempt(self, leased: LeasedAnalysis, guard: LeaseGuard, stop_heartbeat: Callable[[], None]) -> AttemptOutcome:
        lease = leased.lease
        schema = self._profile.schema
        tracks: list[TrackResult] = []
        for track in lease.tracks:
            attributes = schema.for_object_class(track.object_class)
            if not attributes:
                raise _AttemptFailed("visual_attribute_contract_violation", "lease names a Track of an inapplicable class")
            observations: list[ObservationResult] = []
            for observation in track.observations:
                guard.check_owned()
                observations.append(await self._observe(leased, observation, attributes))
            try:
                tracks.append(aggregate_track(track, tuple(observations), attributes, self._profile.aggregation))
            except OutputInvalid as exc:
                raise _AttemptFailed("visual_attribute_output_invalid", str(exc)) from exc
        result = tuple(tracks)
        try:
            artefact = encode_predictions(lease, result)
        except OutputInvalid as exc:
            raise _AttemptFailed("visual_attribute_output_invalid", str(exc)) from exc

        guard.check_owned()
        try:
            await self._api.upload(leased, artefact)
        except AttributeLeaseLost:
            raise
        except AttributeApiError as exc:
            # The worker hashes exactly the bytes it sends, so a digest the platform does not
            # reproduce means the bytes changed in transit: transport, retryable.
            if exc.status_code is None or exc.status_code >= 500 or exc.code == _ARTIFACT_INTEGRITY_FAILED:
                raise _AttemptFailed("visual_attribute_upload_transport_failed", "prediction upload failed") from exc
            raise _AttemptFailed("visual_attribute_contract_violation", f"prediction upload refused ({exc.code})") from exc

        body = encode_completion(
            lease,
            self._worker_id,
            self._provenance,
            result,
            prediction_size_bytes=len(artefact),
            prediction_sha256=hashlib.sha256(artefact).hexdigest(),
        )
        guard.check_owned()
        stop_heartbeat()
        return await self._complete(leased, body)

    async def _observe(self, leased: LeasedAnalysis, observation: LeaseObservation, attributes) -> ObservationResult:
        try:
            data = await self._api.read_evidence(leased, observation)
        except EvidenceTransportError as exc:
            # Transport is never evidence: the attempt fails as retryable (plan §10).
            raise _AttemptFailed("visual_attribute_evidence_transport_failed", "accepted evidence could not be read") from exc
        if isinstance(data, EvidenceUnavailable):
            return ObservationResult(observation.observation_id, observation.evidence_rank, reason=data.reason)
        crop = VerifiedCrop(str(observation.observation_id), observation.evidence_rank, observation.sha256, data)
        try:
            # Off the event loop: the heartbeat keeps its schedule while a crop is scored.
            self._inflight = self._inference.submit(self._inferencer.score, crop, attributes)
            scores = await asyncio.wrap_future(self._inflight)
        except CropDecodeError:
            return ObservationResult(observation.observation_id, observation.evidence_rank, reason="evidence_decode_failed")
        except Exception as exc:
            raise _AttemptFailed("visual_attribute_inference_failed", type(exc).__name__) from exc
        return ObservationResult(observation.observation_id, observation.evidence_rank, scores=scores)

    async def _complete(self, leased: LeasedAnalysis, body: bytes) -> AttemptOutcome:
        lease = leased.lease
        for attempt in range(COMPLETION_REPLAY_ATTEMPTS):
            if attempt:
                await self._sleep(self._completion_retry * attempt)
            try:
                response = await self._api.complete(leased, body)
            except AttributeLeaseLost:
                raise
            except AttributeApiError as exc:
                if exc.status_code is not None and exc.status_code < 500:
                    raise _AttemptFailed("visual_attribute_output_invalid", f"completion refused ({exc.code})") from exc
                # Transport or an ambiguous outcome: the identical body is replayed, and the
                # platform answers a committed one from its digest, even after expiry.
                continue
            _LOGGER.info(
                "Attribute analysis %s attempt %s %s: %s Tracks analysed, %s unavailable",
                lease.analysis_id, lease.attempt_count, response.status, response.tracks_analysed, response.tracks_unavailable,
            )
            return AttemptOutcome(response.status)
        _LOGGER.error("Attribute analysis %s attempt %s: completion outcome unknown; the platform reclaims it", lease.analysis_id, lease.attempt_count)
        return AttemptOutcome("abandoned")

    async def _fail(self, leased: LeasedAnalysis, guard: LeaseGuard, code: str, message: str) -> AttemptOutcome:
        lease = leased.lease
        _LOGGER.warning("Attribute analysis %s attempt %s failed: %s", lease.analysis_id, lease.attempt_count, code)
        if guard.is_lost():
            return AttemptOutcome("lease_lost", code)
        try:
            await self._api.fail(leased, code, message)
        except AttributeLeaseLost:
            return AttemptOutcome("lease_lost", code)
        except AttributeApiError:
            # The lease expires and the platform reclaims the attempt; nothing else to do.
            _LOGGER.error("Attribute analysis %s attempt %s: failure could not be reported", lease.analysis_id, lease.attempt_count)
        return AttemptOutcome("failed", code)

    # --- heartbeat -------------------------------------------------------------------------

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
                except AttributeLeaseLost:
                    raise LeaseLostError() from None
                except (AttributeApiError, asyncio.TimeoutError):
                    # A missed renewal is not a lost lease until the deadline says so.
                    continue
                if self._now() >= deadline:
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
        # Start early enough that a full request timeout still ends before the deadline.
        return max(0.0, min(self._heartbeat_interval, remaining - min(self._request_timeout, remaining / 2.0)))


__all__ = ["AttemptOutcome", "AttributeRunner", "COMPLETION_REPLAY_ATTEMPTS"]
