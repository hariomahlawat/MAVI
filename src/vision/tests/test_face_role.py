"""The ``faces`` role end to end against a fake platform (PoC S6; ADR-022 §1, §3).

The real :class:`FaceApiClient` talks to an in-process fake of the ``mavi-face-control-v1`` routes through
``httpx.MockTransport``; the model is the fixture, whose detections are chosen per crop size. Covered: the completion
body against its JSON Schema, observed/unknown and the four reasons, usable versus too-small faces, the per-crop cap,
identical-byte replay, lease loss (no ``/fail`` and no ``/complete``), the capability confined to headers, and the
query-image loop (digest check, bounds, thumbnails only for usable faces).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from mavi_vision.faces.client import FaceApiClient
from mavi_vision.faces.detector import FaceDetection
from mavi_vision.faces.identity import resolve_face_pack
from mavi_vision.faces.main import RUNTIME_UNAVAILABLE_EXIT, run_worker
from mavi_vision.faces.model import FixtureFaceModel, decode_vector
from mavi_vision.faces.runner import FaceRunner, QueryRunner
from mavi_vision.faces.settings import FaceWorkerSettings
from mavi_vision.faces.supervisor import FaceRuntimeState, FaceSupervisor

VISION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = VISION_ROOT.parents[1]
SCHEMAS = REPOSITORY_ROOT / "contracts" / "schemas"
FIXTURE_MANIFEST = VISION_ROOT / "tests" / "fixtures" / "model-manifests" / "embedding-fixture-v2.json"
FIXTURE_PROFILE = VISION_ROOT / "tests" / "fixtures" / "faces" / "fixture-pipeline-v1.json"
RESOLVED = resolve_face_pack(FIXTURE_MANIFEST, FIXTURE_PROFILE)
IDENTITY = RESOLVED.identity
DIMENSION = IDENTITY.dimension
FLOOR = RESOLVED.profile.minimum_face_side
WORKER = "mavi-faces-1"
BASE = "http://platform.test"
PROVENANCE = {
    "roleId": "faces",
    "identityFingerprint": IDENTITY.fingerprint,
    "runtimeProfileId": "embeddings-onnx-v1",
    "runtimeVariant": "windows-x86_64-cpu",
    "executionProvider": "CPUExecutionProvider",
    "actualDevice": "cpu",
    "deviceResolutionReason": "explicit_cpu",
    "onnxRuntimeVersion": "1.31.0",
    "workerVersion": "1.0.0",
}


def _face(x: float, y: float, side_w: float, side_h: float, score: float) -> FaceDetection:
    marks = ((x + 0.3 * side_w, y + 0.4 * side_h), (x + 0.7 * side_w, y + 0.4 * side_h), (x + 0.5 * side_w, y + 0.6 * side_h),
             (x + 0.35 * side_w, y + 0.8 * side_h), (x + 0.65 * side_w, y + 0.8 * side_h))
    return FaceDetection(x, y, side_w, side_h, score, marks)


# Detections the fixture model "finds", keyed by the decoded crop's (width, height).
DETECTIONS = {
    (100, 140): [_face(30, 10, 40, 48, 0.95)],                          # one usable face
    (101, 140): [_face(30, 10, 20, 24, 0.97), _face(5, 5, 40, 44, 0.91)],  # one small, one usable (score order kept)
    (60, 120): [_face(20, 5, 20, 24, 0.93)],                           # too small
    (70, 120): [],                                                     # nothing
    (300, 300): [_face(10 * i, 10, 33, 33, 0.9 + i / 1000) for i in range(12)],  # more than the per-crop cap
}


def _detections(rgb: np.ndarray) -> list[FaceDetection]:
    return DETECTIONS.get((rgb.shape[1], rgb.shape[0]), [])


def _model() -> FixtureFaceModel:
    return FixtureFaceModel(DIMENSION, _detections)


def _utc(delta_seconds: float = 60.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _image(width: int, height: int, seed: int, fmt: str = "JPEG") -> bytes:
    rng = np.random.default_rng(seed)
    buffer = io.BytesIO()
    Image.fromarray(rng.integers(0, 255, (height, width, 3), dtype=np.uint8)).save(buffer, fmt, quality=90)
    return buffer.getvalue()


def _id() -> str:
    return str(uuid.uuid4())


def _token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def _identity_document() -> dict:
    return {"fingerprint": IDENTITY.fingerprint, **IDENTITY.document()}


class FakePlatform:
    """The face control plane as a ``httpx.MockTransport`` handler; records every request."""

    def __init__(self) -> None:
        self.capability = _token()
        self.query_capability = _token()
        self.analysis_id = _id()
        self.tracks: list[dict] = []
        self.evidence: dict[str, bytes | tuple[int, str]] = {}
        self.leases_left = 1
        self.complete_statuses: list = [200]
        self.heartbeat_status = 200
        self.requests: list[httpx.Request] = []
        self.completions: list[bytes] = []
        self.failures: list[dict] = []
        self.queries: list[dict] = []
        self.query_images: dict[str, bytes | tuple[int, str]] = {}
        self.query_completions: list[dict] = []
        self.query_failures: list[dict] = []

    def add_track(self, crops: list[bytes | tuple[int, str]]) -> tuple[str, list[str]]:
        track_id, observations = _id(), []
        for rank, crop in enumerate(crops):
            observation_id = _id()
            data = crop if isinstance(crop, bytes) else b"\xff\xd8placeholder"
            observations.append({"observationId": observation_id, "role": "representative" if rank == 0 else "near-view",
                                 "evidenceRank": rank, "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            self.evidence[observation_id] = crop
        self.tracks.append({"trackId": track_id, "objectClass": "Person", "observations": observations})
        return track_id, [item["observationId"] for item in observations]

    def add_query(self, image: bytes, mime_type: str = "image/jpeg", *, served: bytes | tuple[int, str] | None = None) -> str:
        query_id = _id()
        self.queries.append({
            "schemaVersion": "mavi-face-control-v1", "queryId": query_id, "workerId": WORKER, "attemptCount": 1,
            "leaseExpiresAtUtc": _utc(), "identity": _identity_document(),
            "image": {"mimeType": mime_type, "sizeBytes": len(image), "sha256": hashlib.sha256(image).hexdigest()},
        })
        self.query_images[query_id] = image if served is None else served
        return query_id

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/faces/analyses/lease":
            if self.leases_left <= 0:
                return httpx.Response(204)
            self.leases_left -= 1
            body = {
                "schemaVersion": "mavi-face-control-v1", "analysisId": self.analysis_id, "processingRunId": _id(),
                "workerId": WORKER, "attemptCount": 1, "leaseExpiresAtUtc": _utc(), "deadlineAtUtc": _utc(3600),
                "identity": _identity_document(), "tracks": self.tracks,
            }
            return httpx.Response(200, json=body, headers={"X-Mavi-Lease-Capability": self.capability})
        if path == "/api/faces/queries/lease":
            if not self.queries:
                return httpx.Response(204)
            return httpx.Response(200, json=self.queries.pop(0), headers={"X-Mavi-Lease-Capability": self.query_capability})
        if path.startswith("/api/faces/queries/"):
            assert request.headers["X-Mavi-Lease-Capability"] == self.query_capability
            query_id, operation = path[len("/api/faces/queries/"):].split("/", 1)
            if operation == "image":
                assert request.headers["X-Mavi-Worker-Id"] == WORKER and request.headers["X-Mavi-Attempt"] == "1"
                served = self.query_images[query_id]
                if isinstance(served, tuple):
                    return httpx.Response(served[0], json={"code": served[1]})
                return httpx.Response(200, content=served)
            body = json.loads(request.content)
            if operation == "complete":
                self.query_completions.append(body)
                return httpx.Response(200, json={"schemaVersion": "mavi-face-control-v1", "status": "completed"})
            self.query_failures.append(body)
            return httpx.Response(200, json={"schemaVersion": "mavi-face-control-v1", "outcome": "failed"})
        assert request.headers["X-Mavi-Lease-Capability"] == self.capability
        prefix = f"/api/faces/analyses/{self.analysis_id}/"
        assert path.startswith(prefix)
        operation = path[len(prefix):]
        if operation.startswith("evidence/"):
            assert request.headers["X-Mavi-Worker-Id"] == WORKER and request.headers["X-Mavi-Attempt"] == "1"
            crop = self.evidence[operation.split("/", 1)[1]]
            if isinstance(crop, tuple):
                return httpx.Response(crop[0], json={"code": crop[1]})
            return httpx.Response(200, content=crop, headers={"Content-Type": "image/jpeg"})
        if operation == "heartbeat":
            if self.heartbeat_status != 200:
                return httpx.Response(self.heartbeat_status, json={"code": "face_lease_invalid"})
            return httpx.Response(200, json={"schemaVersion": "mavi-face-control-v1", "leaseExpiresAtUtc": _utc()})
        if operation == "fail":
            self.failures.append(json.loads(request.content))
            return httpx.Response(200, json={"schemaVersion": "mavi-face-control-v1", "outcome": "requeued"})
        if operation == "complete":
            self.completions.append(request.content)
            status = self.complete_statuses.pop(0) if self.complete_statuses else 200
            status, code = status if isinstance(status, tuple) else (status, "transient")
            if status != 200:
                return httpx.Response(status, json={"code": code})
            body = json.loads(request.content)
            observed = sum(1 for track in body["tracks"] if track["outcome"] == "observed")
            return httpx.Response(200, json={
                "schemaVersion": "mavi-face-control-v1", "analysisId": self.analysis_id, "processingRunId": _id(),
                "status": "completed", "completedAtUtc": _utc(0), "tracksObserved": observed,
                "tracksUnknown": len(body["tracks"]) - observed})
        raise AssertionError(f"unexpected route {path}")


def _client(platform: FakePlatform) -> FaceApiClient:
    return FaceApiClient(api_base_url=BASE, worker_id=WORKER, identity=IDENTITY, request_timeout_seconds=5.0,
                         evidence_read_attempts=2, evidence_retry_backoff_seconds=0.0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(platform)))


async def _run_analysis(platform: FakePlatform, model=None, **overrides):
    client = _client(platform)
    options = dict(worker_id=WORKER, model=model or _model(), dimension=DIMENSION, minimum_face_side=FLOOR,
                   provenance=PROVENANCE, heartbeat_interval_seconds=0.05, request_timeout_seconds=1.0,
                   completion_retry_seconds=0.0)
    options.update(overrides)
    runner = FaceRunner(client, **options)
    try:
        return await runner.run_once()
    finally:
        runner.close()
        await client.aclose()


async def _run_query(platform: FakePlatform, model=None, maximum_image_bytes: int = 2 * 1024 * 1024):
    client = _client(platform)
    runner = QueryRunner(client, worker_id=WORKER, model=model or _model(), dimension=DIMENSION, minimum_face_side=FLOOR,
                         maximum_image_bytes=maximum_image_bytes, completion_retry_seconds=0.0)
    try:
        return await runner.run_once()
    finally:
        runner.close()
        await client.aclose()


def _validator(name: str):
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft202012Validator(json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8")))


# --- analysis --------------------------------------------------------------------------------------------------


def test_completion_reports_observed_and_every_unknown_reason_in_lease_order() -> None:
    platform = FakePlatform()
    usable, too_small, nothing = _image(100, 140, 1), _image(60, 120, 2), _image(70, 120, 3)
    observed, observed_ids = platform.add_track([nothing, usable, too_small])
    small_only, small_ids = platform.add_track([too_small, nothing])
    none_found, _ = platform.add_track([nothing])
    empty, _ = platform.add_track([])
    unavailable, _ = platform.add_track([(422, "face_evidence_missing"), b"not an image"])

    outcome = asyncio.run(_run_analysis(platform))

    assert outcome is not None and outcome.status == "completed" and platform.failures == []
    body = json.loads(platform.completions[0])
    _validator("face-complete-v1").validate(body)
    assert body["provenance"] == PROVENANCE and body["workerId"] == WORKER and body["attemptCount"] == 1
    assert [track["trackId"] for track in body["tracks"]] == [observed, small_only, none_found, empty, unavailable]
    first = body["tracks"][0]
    assert first["outcome"] == "observed" and "reason" not in first
    # Crops in lease order: the usable face of the second crop, then the small face of the third.
    assert [(face["observationId"], face["usable"]) for face in first["faces"]] == [(observed_ids[1], True), (observed_ids[2], False)]
    assert first["faces"][0]["box"] == {"x": 30.0, "y": 10.0, "width": 40.0, "height": 48.0}
    vector = decode_vector(first["faces"][0]["embedding"], DIMENSION)
    assert abs(float(np.linalg.norm(vector)) - 1.0) < 1e-5
    assert "embedding" not in first["faces"][1]
    assert [(track["outcome"], track.get("reason")) for track in body["tracks"][1:]] == [
        ("unknown", "face_too_small"), ("unknown", "no_face_detected"), ("unknown", "no_evidence"),
        ("unknown", "evidence_unavailable")]
    assert [face["observationId"] for face in body["tracks"][1]["faces"]] == [small_ids[0]]
    assert body["tracks"][2]["faces"] == [] and body["tracks"][4]["faces"] == []


def test_faces_keep_score_order_and_the_per_crop_cap() -> None:
    platform = FakePlatform()
    platform.add_track([_image(101, 140, 4), _image(300, 300, 5)])
    asyncio.run(_run_analysis(platform))
    faces = json.loads(platform.completions[0])["tracks"][0]["faces"]
    assert [face["usable"] for face in faces[:2]] == [False, True] and faces[0]["score"] > faces[1]["score"]
    capped = faces[2:]
    assert len(capped) == 8 and [face["score"] for face in capped] == sorted((f["score"] for f in capped), reverse=True)
    assert capped[0]["score"] == pytest.approx(0.911)


def test_a_face_is_usable_exactly_at_the_floor() -> None:
    platform = FakePlatform()
    DETECTIONS[(90, 140)] = [_face(1, 1, FLOOR, FLOOR + 10, 0.95), _face(50, 1, FLOOR - 0.001, 50, 0.94)]
    try:
        platform.add_track([_image(90, 140, 6)])
        asyncio.run(_run_analysis(platform))
    finally:
        del DETECTIONS[(90, 140)]
    faces = json.loads(platform.completions[0])["tracks"][0]["faces"]
    assert [face["usable"] for face in faces] == [True, False]


def test_a_digest_mismatch_on_every_read_makes_the_crop_unavailable() -> None:
    platform = FakePlatform()
    track, ids = platform.add_track([_image(100, 140, 7)])
    platform.evidence[ids[0]] = bytes(reversed(platform.evidence[ids[0]]))
    asyncio.run(_run_analysis(platform))
    body = json.loads(platform.completions[0])
    assert body["tracks"] == [{"trackId": track, "outcome": "unknown", "reason": "evidence_unavailable", "faces": []}]


def test_persistent_evidence_transport_fails_the_attempt_as_retryable() -> None:
    platform = FakePlatform()
    platform.add_track([(503, "unavailable")])
    outcome = asyncio.run(_run_analysis(platform))
    assert outcome.status == "failed" and outcome.failure_code == "face_evidence_transport_failed"
    assert platform.completions == [] and [item["failureCode"] for item in platform.failures] == ["face_evidence_transport_failed"]


def test_an_ambiguous_completion_is_replayed_with_identical_bytes() -> None:
    platform = FakePlatform()
    platform.add_track([_image(100, 140, 8)])
    platform.complete_statuses = [503, 502, 200]
    outcome = asyncio.run(_run_analysis(platform))
    assert outcome.status == "completed" and len(platform.completions) == 3 and len(set(platform.completions)) == 1


def test_completion_refusals() -> None:
    platform = FakePlatform()
    platform.add_track([_image(100, 140, 9)])
    platform.complete_statuses = [(422, "face_completion_invalid")]
    assert asyncio.run(_run_analysis(platform)).failure_code == "face_output_invalid"
    for refusal in [(409, "face_identity_mismatch"), (413, "payload_too_large")]:
        platform = FakePlatform()
        platform.add_track([_image(100, 140, 9)])
        platform.complete_statuses = [refusal]
        outcome = asyncio.run(_run_analysis(platform))
        assert outcome.status == "abandoned" and platform.failures == []


def test_a_model_fault_fails_the_attempt_and_bad_output_is_not_retryable() -> None:
    class Broken(FixtureFaceModel):
        def embed(self, faces):
            raise RuntimeError("onnx exploded")

    class NaN(FixtureFaceModel):
        def embed(self, faces):
            return np.full((len(faces), self.dimension), np.nan, dtype=np.float32)

    for model, code in [(Broken(DIMENSION, _detections), "face_runtime_failed"), (NaN(DIMENSION, _detections), "face_output_invalid")]:
        platform = FakePlatform()
        platform.add_track([_image(100, 140, 10)])
        outcome = asyncio.run(_run_analysis(platform, model))
        assert outcome.failure_code == code and platform.completions == []


def test_a_lost_lease_is_never_answered_with_fail_or_complete() -> None:
    platform = FakePlatform()
    platform.heartbeat_status = 409

    class Slow(FixtureFaceModel):
        def detect(self, rgb):
            import time

            time.sleep(0.3)
            return super().detect(rgb)

    platform.add_track([_image(100, 140, 11), _image(100, 140, 12)])
    outcome = asyncio.run(_run_analysis(platform, Slow(DIMENSION, _detections)))
    assert outcome.status == "lease_lost" and platform.completions == [] and platform.failures == []


def test_the_capability_never_leaves_the_header() -> None:
    platform = FakePlatform()
    platform.add_track([_image(100, 140, 13)])
    asyncio.run(_run_analysis(platform))
    for request in platform.requests:
        assert platform.capability not in str(request.url)
        assert platform.capability.encode() not in request.content


# --- query images ----------------------------------------------------------------------------------------------


def test_a_query_image_completes_with_faces_and_thumbnails_for_usable_faces_only() -> None:
    platform = FakePlatform()
    query_id = platform.add_query(_image(101, 140, 20))
    outcome = asyncio.run(_run_query(platform))
    assert outcome.status == "completed" and platform.query_failures == []
    body = platform.query_completions[0]
    _validator("face-query-complete-v1").validate(body)
    assert body["queryId"] == query_id
    small, usable = body["faces"]
    assert not small["usable"] and "thumbnail" not in small and "embedding" not in small
    assert usable["usable"] and decode_vector(usable["embedding"], DIMENSION).shape == (DIMENSION,)
    with Image.open(io.BytesIO(base64.b64decode(usable["thumbnail"]))) as thumbnail:
        assert thumbnail.format == "JPEG" and thumbnail.size == (112, 112)


def test_an_image_without_faces_completes_with_an_empty_list() -> None:
    platform = FakePlatform()
    platform.add_query(_image(70, 120, 21, "PNG"), "image/png")
    asyncio.run(_run_query(platform))
    assert platform.query_completions[0]["faces"] == []


def test_query_images_the_role_cannot_use_fail_the_query_as_not_retryable() -> None:
    cases = [
        lambda p: p.add_query(_image(100, 140, 22, "PNG"), "image/jpeg"),                       # not its declared type
        lambda p: p.add_query(b"garbage bytes", "image/png"),                                   # not an image
        lambda p: p.add_query(_image(100, 140, 23), served=(422, "face_query_image_missing")),  # erased
        lambda p: p.add_query(_image(100, 140, 24), served=bytes(reversed(_image(100, 140, 24)))),  # wrong digest
    ]
    for setup in cases:
        platform = FakePlatform()
        setup(platform)
        outcome = asyncio.run(_run_query(platform))
        assert outcome.failure_code == "face_query_image_invalid" and platform.query_completions == []
        assert [failure["failureCode"] for failure in platform.query_failures] == ["face_query_image_invalid"]


def test_a_query_image_over_the_profile_bound_is_refused() -> None:
    platform = FakePlatform()
    image = _image(100, 140, 25)
    platform.add_query(image)
    outcome = asyncio.run(_run_query(platform, maximum_image_bytes=len(image) - 1))
    assert outcome.failure_code == "face_query_image_invalid"


def test_a_lost_query_lease_is_not_answered() -> None:
    platform = FakePlatform()
    platform.add_query(_image(100, 140, 26), served=(409, "face_lease_invalid"))
    outcome = asyncio.run(_run_query(platform))
    assert outcome.status == "lease_lost" and platform.query_failures == [] and platform.query_completions == []


# --- process -----------------------------------------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides) -> FaceWorkerSettings:
    values = dict(api_base_url=BASE, worker_id=WORKER, model_root=tmp_path, face_manifest_path=FIXTURE_MANIFEST,
                  face_pipeline_profile_path=FIXTURE_PROFILE)
    values.update(overrides)
    return FaceWorkerSettings(**values)


def test_production_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="face_role_development_only"):
        _settings(tmp_path, production_mode=True)


def test_an_unverifiable_pack_leaves_the_worker_unavailable_and_it_never_leases(tmp_path: Path) -> None:
    supervisor = FaceSupervisor(_settings(tmp_path))
    supervisor.start()
    assert supervisor.state is FaceRuntimeState.UNAVAILABLE
    assert supervisor.unavailable_reason.startswith("face_model_artifact_missing")

    leased = []

    def client_factory(**kwargs):
        leased.append(kwargs)
        raise AssertionError("an unavailable worker must not build a client")

    exit_code = asyncio.run(run_worker(_settings(tmp_path), client_factory=client_factory, max_iterations=1))
    assert exit_code == RUNTIME_UNAVAILABLE_EXIT and leased == []
