"""The two loops of the ``faces`` role (PoC S6; ADR-022 §1, §3, §7).

**Analysis** (one attempt per lease): lease -> concurrent heartbeat -> per leased Person Track, in lease order, each
crop read through the lease-scoped evidence endpoint with size + SHA-256 verification and decoded -> YuNet at the
profile's score threshold (at most 8 faces per crop, highest score first) -> a face is *usable* when its box's
shorter side reaches ``minimumFaceSide`` -> usable faces aligned to 112×112 and embedded -> ``face-complete-v1``.
The embeddings runner's lease discipline applies unchanged: a lost lease cancels the work and is never answered with
``/fail`` or ``/complete``; the completion body is serialised once and replayed byte for byte.

Track outcomes: ``observed`` when at least one usable face was found; otherwise ``unknown`` with ``no_evidence``
(nothing leased), ``evidence_unavailable`` (no crop could be read and decoded), ``no_face_detected`` or
``face_too_small`` (faces found, none usable; they are still reported, without vectors). Unknown is never "no
match" (ADR-022 §1). Evidence *transport* that persists fails the attempt as retryable.

**Query images** run as a second loop: lease -> image bytes (size + SHA-256) -> JPEG/PNG decode within bounds ->
faces as above, each usable face with a vector and an aligned 112×112 JPEG thumbnail -> ``face-query-complete-v1``.
An image the role cannot use fails the query as ``face_query_image_invalid`` (not retryable).
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

import numpy as np

from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.faces.align import align_face
from mavi_vision.faces.client import (
    EvidenceTransportError,
    EvidenceUnavailable,
    FaceApiError,
    FaceLeaseLost,
    LeasedAnalysis,
    LeasedQuery,
    QueryImageRefused,
)
from mavi_vision.faces.contracts import (
    COMPLETION_INVALID_CODE,
    CONTROL_VERSION,
    FAILURE_EVIDENCE_TRANSPORT,
    FAILURE_OUTPUT_INVALID,
    FAILURE_QUERY_IMAGE_INVALID,
    FAILURE_QUERY_RUNTIME,
    FAILURE_RUNTIME,
    MAXIMUM_FACES_PER_CROP,
    MAXIMUM_FACES_PER_QUERY,
    REASON_EVIDENCE_UNAVAILABLE,
    REASON_FACE_TOO_SMALL,
    REASON_NO_EVIDENCE,
    REASON_NO_FACE_DETECTED,
    TRACK_OBSERVED,
    TRACK_UNKNOWN,
    CompleteResponse,
    FaceLease,
    FailResponse,
    HeartbeatResponse,
    LeaseObservation,
    LeaseTrack,
    QueryCompleteResponse,
)
from mavi_vision.faces.detector import FaceDetection
from mavi_vision.faces.model import (
    FaceModel,
    OutputInvalid,
    QueryImageInvalid,
    decode_crop,
    decode_query_image,
    encode_vector,
    l2_normalise_rows,
    thumbnail_jpeg,
)

_LOGGER = logging.getLogger(__name__)
COMPLETION_REPLAY_ATTEMPTS = 3


class FaceApi(Protocol):
    async def lease(self) -> LeasedAnalysis | None: ...
    async def heartbeat(self, leased: LeasedAnalysis) -> HeartbeatResponse: ...
    async def fail(self, leased: LeasedAnalysis, failure_code: str, failure_message: str | None) -> FailResponse: ...
    async def read_evidence(self, leased: LeasedAnalysis, observation: LeaseObservation) -> bytes | EvidenceUnavailable: ...
    async def complete(self, leased: LeasedAnalysis, body: bytes) -> CompleteResponse: ...
    async def lease_query(self) -> LeasedQuery | None: ...
    async def read_query_image(self, leased: LeasedQuery) -> bytes: ...
    async def complete_query(self, leased: LeasedQuery, body: bytes) -> QueryCompleteResponse: ...
    async def fail_query(self, leased: LeasedQuery, failure_code: str, failure_message: str | None) -> FailResponse: ...


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """What one lease ended as, for logs and tests."""

    status: str  # "completed" | "superseded" | "failed" | "lease_lost" | "abandoned"
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class FoundFace:
    """One reported face: its detection, whether it is usable, and (usable only) its vector and aligned pixels."""

    detection: FaceDetection
    usable: bool
    embedding: str | None = None
    aligned: np.ndarray | None = None

    def document(self, *, thumbnail: bool = False) -> dict[str, object]:
        d = self.detection
        document: dict[str, object] = {
            "box": {"x": _r(d.x), "y": _r(d.y), "width": _r(d.width), "height": _r(d.height)},
            "landmarks": [[_r(x), _r(y)] for x, y in d.landmarks],
            "score": round(float(d.score), 6),
            "usable": self.usable,
        }
        if self.usable:
            document["embedding"] = self.embedding
            if thumbnail and self.aligned is not None:
                document["thumbnail"] = thumbnail_jpeg(self.aligned)
        return document


@dataclass(frozen=True, slots=True)
class TrackOutcome:
    track_id: str
    outcome: str
    faces: tuple[tuple[str, FoundFace], ...] = ()  # (observationId, face), lease order then score order
    reason: str | None = None

    def document(self) -> dict[str, object]:
        document: dict[str, object] = {"trackId": self.track_id, "outcome": self.outcome}
        if self.outcome == TRACK_UNKNOWN:
            document["reason"] = self.reason
        document["faces"] = [{"observationId": observation_id, **face.document()} for observation_id, face in self.faces]
        return document


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


def _r(value: float) -> float:
    return round(float(value), 3)


def _json(body: dict[str, object]) -> bytes:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def encode_completion(lease: FaceLease, worker_id: str, provenance: Mapping[str, object],
                      tracks: tuple[TrackOutcome, ...]) -> bytes:
    """The exact ``face-complete-v1`` request bytes (compact JSON, contract member order)."""
    return _json({
        "schemaVersion": CONTROL_VERSION,
        "analysisId": str(lease.analysis_id),
        "workerId": worker_id,
        "attemptCount": lease.attempt_count,
        "provenance": {key: provenance[key] for key in PROVENANCE_KEYS},
        "tracks": [track.document() for track in tracks],
    })


def encode_query_completion(leased: LeasedQuery, worker_id: str, faces: tuple[FoundFace, ...]) -> bytes:
    lease = leased.lease
    return _json({
        "schemaVersion": CONTROL_VERSION,
        "queryId": str(lease.query_id),
        "workerId": worker_id,
        "attemptCount": lease.attempt_count,
        "faces": [face.document(thumbnail=True) for face in faces],
    })


def is_usable(face: FaceDetection, minimum_face_side: int) -> bool:
    """Judged on the box as reported (3 decimals), so the platform can re-derive it from the completion exactly."""
    return min(_r(face.width), _r(face.height)) >= minimum_face_side


def find_faces(model: FaceModel, rgb: np.ndarray, *, minimum_face_side: int, dimension: int,
               maximum_faces: int, keep_aligned: bool = False) -> list[FoundFace]:
    """Detect, cap, classify and embed the faces of one decoded image (runs on the inference thread)."""
    detections = sorted(model.detect(rgb), key=lambda face: -face.score)[:maximum_faces]
    usable = [face for face in detections if is_usable(face, minimum_face_side)]
    aligned = [align_face(rgb, face.landmarks) for face in usable]
    vectors: list[str] = []
    if aligned:
        rows = model.embed(aligned)
        if getattr(rows, "shape", (None,))[0] != len(aligned):
            raise OutputInvalid("face embedding output row count does not match the faces")
        vectors = [encode_vector(row, dimension) for row in l2_normalise_rows(rows, dimension)]
    found: list[FoundFace] = []
    iterator = iter(zip(vectors, aligned))
    for face in detections:
        if is_usable(face, minimum_face_side):
            vector, pixels = next(iterator)
            found.append(FoundFace(face, True, vector, pixels if keep_aligned else None))
        else:
            found.append(FoundFace(face, False))
    return found


class FaceRunner:
    def __init__(
        self,
        api: FaceApi,
        *,
        worker_id: str,
        model: FaceModel,
        dimension: int,
        minimum_face_side: int,
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
        self._minimum_face_side = minimum_face_side
        self._provenance = dict(provenance)
        missing = [key for key in PROVENANCE_KEYS if key not in self._provenance]
        if missing:
            raise ValueError(f"face_provenance_incomplete:{missing[0]}")
        self._heartbeat_interval = heartbeat_interval_seconds
        self._request_timeout = request_timeout_seconds
        self._completion_retry = completion_retry_seconds
        self._now = now_utc or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        # One serial lane for inference: work that outlives a lost attempt finishes before the next may infer.
        self._inference = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-face-inference")
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

        attempt = asyncio.create_task(self._attempt(leased, guard, stop_heartbeat), name="mavi-face-attempt")
        heartbeat = asyncio.create_task(self._heartbeat_loop(leased, guard, attempt), name="mavi-face-heartbeat")
        try:
            try:
                return await asyncio.shield(attempt)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                caller_cancelling = current is not None and current.cancelling() > 0
                if attempt.cancelled() and guard.is_lost() and not caller_cancelling:
                    _LOGGER.warning("Face analysis %s attempt %s lost its lease", lease.analysis_id, lease.attempt_count)
                    return AttemptOutcome("lease_lost")
                attempt.cancel()
                raise
            except (LeaseLostError, FaceLeaseLost):
                guard.mark_lost()
                _LOGGER.warning("Face analysis %s attempt %s lost its lease", lease.analysis_id, lease.attempt_count)
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
            return TrackOutcome(track_id, TRACK_UNKNOWN, reason=REASON_NO_EVIDENCE)
        decoded_any = False
        faces: list[tuple[str, FoundFace]] = []
        for observation in track.observations:
            guard.check_owned()
            try:
                data = await self._api.read_evidence(leased, observation)
            except EvidenceTransportError as exc:
                # Transport is never evidence: the attempt fails as retryable.
                raise _AttemptFailed(FAILURE_EVIDENCE_TRANSPORT, "accepted evidence could not be read") from exc
            if isinstance(data, EvidenceUnavailable):
                continue
            rgb = await self._infer(decode_crop, data)
            if rgb is None:
                continue
            decoded_any = True
            guard.check_owned()
            try:
                found = await self._infer(self._find, rgb)
            except OutputInvalid:
                raise
            except Exception as exc:  # noqa: BLE001 - any model fault fails the attempt, retryable
                raise _AttemptFailed(FAILURE_RUNTIME, f"face analysis failed ({type(exc).__name__})") from exc
            faces.extend((str(observation.observation_id), face) for face in found)
        if not decoded_any:
            return TrackOutcome(track_id, TRACK_UNKNOWN, reason=REASON_EVIDENCE_UNAVAILABLE)
        if any(face.usable for _, face in faces):
            return TrackOutcome(track_id, TRACK_OBSERVED, tuple(faces))
        reason = REASON_FACE_TOO_SMALL if faces else REASON_NO_FACE_DETECTED
        return TrackOutcome(track_id, TRACK_UNKNOWN, tuple(faces), reason)

    def _find(self, rgb: np.ndarray) -> list[FoundFace]:
        return find_faces(self._model, rgb, minimum_face_side=self._minimum_face_side, dimension=self._dimension,
                          maximum_faces=MAXIMUM_FACES_PER_CROP)

    async def _infer(self, function, *args):
        # Off the event loop: the heartbeat keeps its schedule while crops are decoded and analysed.
        self._inflight = self._inference.submit(function, *args)
        return await asyncio.wrap_future(self._inflight)

    async def _complete(self, leased: LeasedAnalysis, body: bytes) -> AttemptOutcome:
        lease = leased.lease
        for attempt in range(COMPLETION_REPLAY_ATTEMPTS):
            if attempt:
                await self._sleep(self._completion_retry * attempt)
            try:
                response = await self._api.complete(leased, body)
            except FaceLeaseLost:
                raise
            except FaceApiError as exc:
                if exc.status_code == 422 and exc.code == COMPLETION_INVALID_CODE:
                    # The platform judged this output invalid: the one refusal that is the worker's own fault.
                    raise _AttemptFailed(FAILURE_OUTPUT_INVALID, f"completion refused ({exc.code})") from exc
                if exc.status_code is not None and exc.status_code < 500:
                    # Any other refusal is not evidence of bad output: abandon and let the platform reclaim it.
                    _LOGGER.warning("Face analysis %s attempt %s: completion refused (%s %s); abandoning the attempt",
                                    lease.analysis_id, lease.attempt_count, exc.status_code, exc.code)
                    return AttemptOutcome("abandoned")
                # Transport or an ambiguous outcome: the identical bytes are replayed.
                continue
            _LOGGER.info("Face analysis %s attempt %s %s: %s Tracks observed, %s unknown", lease.analysis_id,
                         lease.attempt_count, response.status, response.tracks_observed, response.tracks_unknown)
            return AttemptOutcome(response.status)
        _LOGGER.error("Face analysis %s attempt %s: completion outcome unknown; the platform reclaims it",
                      lease.analysis_id, lease.attempt_count)
        return AttemptOutcome("abandoned")

    async def _fail(self, leased: LeasedAnalysis, guard: LeaseGuard, code: str, message: str) -> AttemptOutcome:
        lease = leased.lease
        _LOGGER.warning("Face analysis %s attempt %s failed: %s", lease.analysis_id, lease.attempt_count, code)
        if guard.is_lost():
            return AttemptOutcome("lease_lost", code)
        try:
            await self._api.fail(leased, code, message)
        except FaceLeaseLost:
            return AttemptOutcome("lease_lost", code)
        except FaceApiError:
            _LOGGER.error("Face analysis %s attempt %s: failure could not be reported", lease.analysis_id, lease.attempt_count)
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
                except FaceLeaseLost:
                    raise LeaseLostError() from None
                except (FaceApiError, asyncio.TimeoutError):
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


class QueryRunner:
    """One transient query image per call: lease -> image -> faces on its own thread -> complete, or fail."""

    def __init__(
        self,
        api: FaceApi,
        *,
        worker_id: str,
        model: FaceModel,
        dimension: int,
        minimum_face_side: int,
        maximum_image_bytes: int,
        completion_retry_seconds: float = 0.25,
        now_utc: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api = api
        self._worker_id = worker_id
        self._model = model
        self._dimension = dimension
        self._minimum_face_side = minimum_face_side
        self._maximum_image_bytes = maximum_image_bytes
        self._completion_retry = completion_retry_seconds
        self._now = now_utc or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        self._inference = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-face-query")

    def close(self) -> None:
        self._inference.shutdown(wait=True, cancel_futures=True)

    def _analyse(self, data: bytes, mime_type: str) -> list[FoundFace]:
        rgb = decode_query_image(data, mime_type, self._maximum_image_bytes)
        return find_faces(self._model, rgb, minimum_face_side=self._minimum_face_side, dimension=self._dimension,
                          maximum_faces=MAXIMUM_FACES_PER_QUERY, keep_aligned=True)

    async def run_once(self) -> AttemptOutcome | None:
        leased = await self._api.lease_query()
        if leased is None:
            return None
        lease = leased.lease
        try:
            data = await self._api.read_query_image(leased)
        except FaceLeaseLost:
            _LOGGER.warning("Face query %s attempt %s lost its lease", lease.query_id, lease.attempt_count)
            return AttemptOutcome("lease_lost")
        except QueryImageRefused:
            return await self._fail(leased, FAILURE_QUERY_IMAGE_INVALID, "query image unavailable or not its recorded bytes")
        except FaceApiError:
            return await self._fail(leased, FAILURE_QUERY_RUNTIME, "query image could not be read")
        try:
            faces = await asyncio.wrap_future(self._inference.submit(self._analyse, data, lease.image.mime_type))
        except QueryImageInvalid as exc:
            return await self._fail(leased, FAILURE_QUERY_IMAGE_INVALID, str(exc))
        except Exception as exc:  # noqa: BLE001 - any model fault is retryable
            return await self._fail(leased, FAILURE_QUERY_RUNTIME, f"query analysis failed ({type(exc).__name__})")
        if lease.lease_expires_at_utc <= self._now():
            _LOGGER.warning("Face query %s attempt %s lost its lease", lease.query_id, lease.attempt_count)
            return AttemptOutcome("lease_lost")
        body = encode_query_completion(leased, self._worker_id, tuple(faces))
        for attempt in range(COMPLETION_REPLAY_ATTEMPTS):
            if attempt:
                await self._sleep(self._completion_retry * attempt)
            try:
                await self._api.complete_query(leased, body)
            except FaceLeaseLost:
                _LOGGER.warning("Face query %s attempt %s lost its lease", lease.query_id, lease.attempt_count)
                return AttemptOutcome("lease_lost")
            except FaceApiError as exc:
                if exc.status_code is not None and exc.status_code < 500:
                    return await self._fail(leased, FAILURE_QUERY_IMAGE_INVALID, f"query completion refused ({exc.code})")
                continue
            _LOGGER.info("Face query %s attempt %s completed: %s faces", lease.query_id, lease.attempt_count, len(faces))
            return AttemptOutcome("completed")
        return AttemptOutcome("abandoned")

    async def _fail(self, leased: LeasedQuery, code: str, message: str) -> AttemptOutcome:
        lease = leased.lease
        _LOGGER.warning("Face query %s attempt %s failed: %s", lease.query_id, lease.attempt_count, code)
        if lease.lease_expires_at_utc <= self._now():
            return AttemptOutcome("lease_lost", code)
        try:
            await self._api.fail_query(leased, code, message)
        except FaceLeaseLost:
            return AttemptOutcome("lease_lost", code)
        except FaceApiError:
            _LOGGER.error("Face query %s attempt %s: failure could not be reported", lease.query_id, lease.attempt_count)
        return AttemptOutcome("failed", code)


__all__ = [
    "AttemptOutcome",
    "COMPLETION_REPLAY_ATTEMPTS",
    "FaceRunner",
    "FoundFace",
    "PROVENANCE_KEYS",
    "QueryRunner",
    "TrackOutcome",
    "encode_completion",
    "encode_query_completion",
    "find_faces",
    "is_usable",
]
