"""One plate attempt, end to end, through the platform's lease plane (Stage 4 plan §2.1).

lease -> (concurrent heartbeat) -> per Vehicle Track, per leased crop: excluded by the profile, or an
authorised read with size + SHA-256 verification, one decode, detection, recognition -> Track summary
-> canonical ``PlatePredictions`` -> upload -> completion. The attribute runner's lease discipline:
the heartbeat is its own task from the lease on, a lost lease cancels the work, and a lost lease is never
answered with ``/fail``. A model that emits more than its configured bound fails the attempt
(``plate_output_invalid``); nothing is truncated.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol

from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.plates.client import (
    EvidenceTransportError,
    EvidenceUnavailable,
    LeasedAnalysis,
    PlateApiError,
    PlateLeaseLost,
)
from mavi_vision.plates.contracts import (
    EVIDENCE_CLAIM_CONTRADICTED,
    CompleteResponse,
    FailResponse,
    HeartbeatResponse,
    LeaseObservation,
    UploadResponse,
)
from mavi_vision.plates.inference import PlateDetector, PlateRecogniser, VerifiedCrop
from mavi_vision.plates.parameters import PlateParameters
from mavi_vision.plates.pipeline import (
    CropRecord,
    OutputInvalid,
    TrackRecord,
    analyse_crop,
    excluded_crop,
    summarise_track,
    unavailable_crop,
)
from mavi_vision.plates.predictions import encode_completion, encode_predictions

_LOGGER = logging.getLogger(__name__)
COMPLETION_REPLAY_ATTEMPTS = 3
_ARTIFACT_INTEGRITY_FAILED = "vision_result_artifact_integrity_failed"


class PlateApi(Protocol):
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


class PlateRunner:
    def __init__(
        self,
        api: PlateApi,
        *,
        worker_id: str,
        parameters: PlateParameters,
        detector: PlateDetector,
        recogniser: PlateRecogniser,
        provenance: Mapping[str, object],
        heartbeat_interval_seconds: float,
        request_timeout_seconds: float,
        completion_retry_seconds: float = 1.0,
        now_utc: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api = api
        self._worker_id = worker_id
        self._parameters = parameters
        self._detector = detector
        self._recogniser = recogniser
        self._provenance = dict(provenance)
        self._heartbeat_interval = heartbeat_interval_seconds
        self._request_timeout = request_timeout_seconds
        self._completion_retry = completion_retry_seconds
        self._now = now_utc or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        # One serial lane for inference: a model is never entered concurrently, and work that
        # outlives a lost attempt finishes before the next attempt may infer.
        self._inference = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-plate-inference")
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

        attempt = asyncio.create_task(self._attempt(leased, guard, stop_heartbeat), name="mavi-plate-attempt")
        heartbeat = asyncio.create_task(self._heartbeat_loop(leased, guard, attempt), name="mavi-plate-heartbeat")
        try:
            try:
                return await asyncio.shield(attempt)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                caller_cancelling = current is not None and current.cancelling() > 0
                if attempt.cancelled() and guard.is_lost() and not caller_cancelling:
                    _LOGGER.warning("Plate analysis %s attempt %s lost its lease", lease.analysis_id, lease.attempt_count)
                    return AttemptOutcome("lease_lost")
                attempt.cancel()
                raise
            except (LeaseLostError, PlateLeaseLost):
                guard.mark_lost()
                _LOGGER.warning("Plate analysis %s attempt %s lost its lease", lease.analysis_id, lease.attempt_count)
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
        tracks: list[TrackRecord] = []
        try:
            for track in lease.tracks:
                crops: list[CropRecord] = []
                for observation in track.observations:
                    guard.check_owned()
                    crops.append(await self._crop(leased, observation))
                tracks.append(summarise_track(track, tuple(crops)))
            artefact = encode_predictions(lease, tuple(tracks))
        except OutputInvalid as exc:
            raise _AttemptFailed("plate_output_invalid", str(exc)) from exc

        guard.check_owned()
        try:
            await self._api.upload(leased, artefact)
        except PlateLeaseLost:
            raise
        except PlateApiError as exc:
            if exc.status_code is None or exc.status_code >= 500 or exc.code == _ARTIFACT_INTEGRITY_FAILED:
                raise _AttemptFailed("plate_upload_transport_failed", "prediction upload failed") from exc
            raise _AttemptFailed("plate_contract_violation", f"prediction upload refused ({exc.code})") from exc

        try:
            body = encode_completion(lease, self._worker_id, self._provenance, tuple(tracks), self._parameters,
                                     prediction_size_bytes=len(artefact), prediction_sha256=hashlib.sha256(artefact).hexdigest())
        except OutputInvalid as exc:
            raise _AttemptFailed("plate_output_invalid", str(exc)) from exc
        guard.check_owned()
        stop_heartbeat()
        return await self._complete(leased, body)

    async def _crop(self, leased: LeasedAnalysis, observation: LeaseObservation) -> CropRecord:
        # A role the profile excludes is never read: it is recorded, not inferred.
        if observation.role in self._parameters.excluded_roles:
            return excluded_crop(observation)
        try:
            data = await self._api.read_evidence(leased, observation)
        except EvidenceTransportError as exc:
            # Transport is never evidence: the attempt fails as retryable.
            raise _AttemptFailed("plate_evidence_transport_failed", "accepted evidence could not be read") from exc
        if isinstance(data, EvidenceUnavailable):
            return unavailable_crop(observation, data.reason)
        crop = VerifiedCrop(str(observation.observation_id), observation.role, observation.evidence_rank, observation.sha256, data)
        # Off the event loop: the heartbeat keeps its schedule while a crop is analysed. Decode,
        # detector and OCR faults come back as abstentions; a bound violation as OutputInvalid.
        self._inflight = self._inference.submit(analyse_crop, observation, crop, self._detector, self._recogniser, self._parameters)
        return await asyncio.wrap_future(self._inflight)

    async def _complete(self, leased: LeasedAnalysis, body: bytes) -> AttemptOutcome:
        lease = leased.lease
        for attempt in range(COMPLETION_REPLAY_ATTEMPTS):
            if attempt:
                await self._sleep(self._completion_retry * attempt)
            try:
                response = await self._api.complete(leased, body)
            except PlateLeaseLost:
                raise
            except PlateApiError as exc:
                if exc.code == EVIDENCE_CLAIM_CONTRADICTED:
                    raise _AttemptFailed(EVIDENCE_CLAIM_CONTRADICTED, "the platform found reported-unavailable evidence intact") from exc
                if exc.status_code is not None and exc.status_code < 500:
                    raise _AttemptFailed("plate_output_invalid", f"completion refused ({exc.code})") from exc
                # Transport or an ambiguous outcome: the identical body is replayed.
                continue
            _LOGGER.info("Plate analysis %s attempt %s %s: %s Tracks analysed, %s unavailable",
                         lease.analysis_id, lease.attempt_count, response.status, response.tracks_analysed, response.tracks_unavailable)
            return AttemptOutcome(response.status)
        _LOGGER.error("Plate analysis %s attempt %s: completion outcome unknown; the platform reclaims it", lease.analysis_id, lease.attempt_count)
        return AttemptOutcome("abandoned")

    async def _fail(self, leased: LeasedAnalysis, guard: LeaseGuard, code: str, message: str) -> AttemptOutcome:
        lease = leased.lease
        _LOGGER.warning("Plate analysis %s attempt %s failed: %s", lease.analysis_id, lease.attempt_count, code)
        if guard.is_lost():
            return AttemptOutcome("lease_lost", code)
        try:
            await self._api.fail(leased, code, message)
        except PlateLeaseLost:
            return AttemptOutcome("lease_lost", code)
        except PlateApiError:
            _LOGGER.error("Plate analysis %s attempt %s: failure could not be reported", lease.analysis_id, lease.attempt_count)
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
                except PlateLeaseLost:
                    raise LeaseLostError() from None
                except (PlateApiError, asyncio.TimeoutError):
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


__all__ = ["AttemptOutcome", "COMPLETION_REPLAY_ATTEMPTS", "PlateRunner"]
