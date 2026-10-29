"""The ``embeddings`` role end to end against a fake platform (PoC S4; ADR-021 §3–§4).

The real :class:`EmbeddingApiClient` talks to an in-process fake of the ``mavi-embedding-control-v1`` routes through
``httpx.MockTransport``; the model is the deterministic fixture. Covered: the completion body against its JSON Schema,
the crop floor and the three unavailable reasons, mean-L2 aggregation, identical-byte replay, lease loss (no ``/fail``
and no ``/complete``), the capability confined to headers, and the concurrent text-query loop.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from mavi_vision.embeddings.client import EmbeddingApiClient, EmbeddingApiError
from mavi_vision.embeddings.identity import resolve_embedding_pack
from mavi_vision.embeddings.main import RUNTIME_UNAVAILABLE_EXIT, run_worker
from mavi_vision.embeddings.model import FixtureEmbeddingModel, decode_vector, l2_normalise_rows
from mavi_vision.embeddings.runner import EmbeddingRunner, TextQueryRunner
from mavi_vision.embeddings.settings import EmbeddingWorkerSettings
from mavi_vision.embeddings.supervisor import EmbeddingRuntime, EmbeddingRuntimeState

VISION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = VISION_ROOT.parents[1]
SCHEMAS = REPOSITORY_ROOT / "contracts" / "schemas"
FIXTURE_MANIFEST = VISION_ROOT / "tests" / "fixtures" / "model-manifests" / "embedding-fixture-v2.json"
FIXTURE_PROFILE = VISION_ROOT / "tests" / "fixtures" / "embeddings" / "fixture-pipeline-v1.json"
RESOLVED = resolve_embedding_pack(FIXTURE_MANIFEST, FIXTURE_PROFILE)
IDENTITY = RESOLVED.identity
DIMENSION = IDENTITY.dimension
FLOOR = RESOLVED.profile.minimum_crop_side
WORKER = "mavi-embeddings-1"
BASE = "http://platform.test"
PROVENANCE = {
    "roleId": "embeddings",
    "identityFingerprint": IDENTITY.fingerprint,
    "runtimeProfileId": "embeddings-onnx-v1",
    "runtimeVariant": "windows-x86_64-cpu",
    "executionProvider": "CPUExecutionProvider",
    "actualDevice": "cpu",
    "deviceResolutionReason": "explicit_cpu",
    "onnxRuntimeVersion": "1.31.0",
    "workerVersion": "1.0.0",
}


def _utc(delta_seconds: float = 60.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jpeg(width: int, height: int, seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    image = Image.fromarray(rng.integers(0, 255, (height, width, 3), dtype=np.uint8))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def _id() -> str:
    return str(uuid.uuid4())


def _identity_document() -> dict:
    return {"fingerprint": IDENTITY.fingerprint, **IDENTITY.document()}


class FakePlatform:
    """The embedding control plane as a ``httpx.MockTransport`` handler; records every request."""

    def __init__(self) -> None:
        self.capability = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
        self.text_capability = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
        self.analysis_id = _id()
        self.tracks: list[dict] = []
        self.evidence: dict[str, bytes | tuple[int, str]] = {}
        self.leases_left = 1
        self.lease_override: dict | None = None
        self.complete_statuses: list[int] = [200]
        self.heartbeat_status = 200
        self.requests: list[httpx.Request] = []
        self.completions: list[bytes] = []
        self.failures: list[dict] = []
        self.text_queries: list[dict] = []
        self.text_completions: list[dict] = []
        self.text_failures: list[dict] = []
        self.on_text_complete: list = []

    # --- lease setup ---
    def add_track(self, crops: list[bytes | tuple[int, str]], object_class: str = "Vehicle") -> tuple[str, list[str]]:
        track_id, observations = _id(), []
        for rank, crop in enumerate(crops):
            observation_id = _id()
            data = crop if isinstance(crop, bytes) else b"\xff\xd8placeholder"
            observations.append({"observationId": observation_id, "role": "representative" if rank == 0 else "near-view",
                                 "evidenceRank": rank, "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            self.evidence[observation_id] = crop
        self.tracks.append({"trackId": track_id, "objectClass": object_class, "observations": observations})
        return track_id, [item["observationId"] for item in observations]

    def lease_body(self) -> dict:
        body = {
            "schemaVersion": "mavi-embedding-control-v1", "analysisId": self.analysis_id, "processingRunId": _id(),
            "workerId": WORKER, "attemptCount": 1, "leaseExpiresAtUtc": _utc(), "deadlineAtUtc": _utc(3600),
            "identity": _identity_document(), "tracks": self.tracks,
        }
        return body if self.lease_override is None else {**body, **self.lease_override}

    # --- handler ---
    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/embeddings/analyses/lease":
            if self.leases_left <= 0:
                return httpx.Response(204)
            self.leases_left -= 1
            return httpx.Response(200, json=self.lease_body(), headers={"X-Mavi-Lease-Capability": self.capability})
        if path == "/api/embeddings/text-queries/lease":
            if not self.text_queries:
                return httpx.Response(204)
            return httpx.Response(200, json=self.text_queries.pop(0), headers={"X-Mavi-Lease-Capability": self.text_capability})
        if path.startswith("/api/embeddings/text-queries/"):
            assert request.headers["X-Mavi-Lease-Capability"] == self.text_capability
            body = json.loads(request.content)
            if path.endswith("/complete"):
                self.text_completions.append(body)
                for callback in self.on_text_complete:
                    callback()
                return httpx.Response(200, json={"schemaVersion": "mavi-embedding-control-v1", "status": "completed"})
            self.text_failures.append(body)
            return httpx.Response(200, json={"schemaVersion": "mavi-embedding-control-v1", "outcome": "failed"})
        assert request.headers["X-Mavi-Lease-Capability"] == self.capability
        prefix = f"/api/embeddings/analyses/{self.analysis_id}/"
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
                return httpx.Response(self.heartbeat_status, json={"code": "embedding_lease_invalid"})
            return httpx.Response(200, json={"schemaVersion": "mavi-embedding-control-v1", "leaseExpiresAtUtc": _utc()})
        if operation == "fail":
            self.failures.append(json.loads(request.content))
            return httpx.Response(200, json={"schemaVersion": "mavi-embedding-control-v1", "outcome": "requeued"})
        if operation == "complete":
            self.completions.append(request.content)
            status = self.complete_statuses.pop(0) if self.complete_statuses else 200
            if status != 200:
                return httpx.Response(status, json={"code": "transient"})
            body = json.loads(request.content)
            embedded = sum(1 for track in body["tracks"] if track["outcome"] == "embedded")
            return httpx.Response(200, json={
                "schemaVersion": "mavi-embedding-control-v1", "analysisId": self.analysis_id, "processingRunId": _id(),
                "status": "completed", "completedAtUtc": _utc(0), "tracksEmbedded": embedded,
                "tracksUnavailable": len(body["tracks"]) - embedded})
        raise AssertionError(f"unexpected route {path}")


def _client(platform: FakePlatform) -> EmbeddingApiClient:
    return EmbeddingApiClient(api_base_url=BASE, worker_id=WORKER, identity=IDENTITY, request_timeout_seconds=5.0,
                              evidence_read_attempts=2, evidence_retry_backoff_seconds=0.0,
                              http_client=httpx.AsyncClient(transport=httpx.MockTransport(platform)))


def _runner(client: EmbeddingApiClient, model=None, **overrides) -> EmbeddingRunner:
    options = dict(worker_id=WORKER, model=model or FixtureEmbeddingModel(DIMENSION), dimension=DIMENSION,
                   minimum_crop_side=FLOOR, provenance=PROVENANCE, heartbeat_interval_seconds=0.05,
                   request_timeout_seconds=1.0, completion_retry_seconds=0.0)
    options.update(overrides)
    return EmbeddingRunner(client, **options)


async def _run_analysis(platform: FakePlatform, model=None):
    client = _client(platform)
    runner = _runner(client, model)
    try:
        return await runner.run_once()
    finally:
        runner.close()
        await client.aclose()


def _schema_validator(name: str):
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft202012Validator(json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8")))


# --- analysis ------------------------------------------------------------------------------------------------


def test_completion_covers_every_track_in_lease_order_and_validates_against_the_schema() -> None:
    platform = FakePlatform()
    big_a, big_b, small = _jpeg(120, 96, 1), _jpeg(200, 81, 2), _jpeg(60, 140, 3)
    embedded, embedded_ids = platform.add_track([big_a, small, big_b])
    too_small, _ = platform.add_track([small, _jpeg(79, 300, 4)], "Person")
    empty, _ = platform.add_track([], "Person")
    missing, _ = platform.add_track([(422, "embedding_evidence_missing"), (422, "embedding_evidence_integrity_failed")])
    mixed, _ = platform.add_track([(422, "embedding_evidence_missing"), small])
    undecodable, _ = platform.add_track([b"not a jpeg at all"])

    outcome = asyncio.run(_run_analysis(platform))

    assert outcome is not None and outcome.status == "completed"
    assert len(platform.completions) == 1 and platform.failures == []
    body = json.loads(platform.completions[0])
    _schema_validator("embedding-complete-v1").validate(body)
    assert body["provenance"] == PROVENANCE
    assert body["analysisId"] == platform.analysis_id and body["workerId"] == WORKER and body["attemptCount"] == 1
    assert [track["trackId"] for track in body["tracks"]] == [embedded, too_small, empty, missing, mixed, undecodable]
    first = body["tracks"][0]
    assert first["outcome"] == "embedded"
    assert first["sourceObservationIds"] == [embedded_ids[0], embedded_ids[2]]  # lease order, the small crop dropped
    vector = decode_vector(first["embedding"], DIMENSION)
    expected = l2_normalise_rows(FixtureEmbeddingModel(DIMENSION).embed_images([big_a, big_b]), DIMENSION).mean(axis=0)
    expected /= np.linalg.norm(expected)
    assert np.allclose(vector, expected, atol=1e-6)
    assert [track.get("reason") for track in body["tracks"][1:]] == [
        "evidence_too_small", "no_evidence", "evidence_unavailable", "evidence_too_small", "evidence_unavailable"]


def test_a_digest_mismatch_on_every_read_makes_the_crop_unavailable() -> None:
    platform = FakePlatform()
    track, ids = platform.add_track([_jpeg(100, 100, 5)])
    platform.evidence[ids[0]] = bytes(reversed(platform.evidence[ids[0]]))  # the recorded size, another digest
    asyncio.run(_run_analysis(platform))
    body = json.loads(platform.completions[0])
    assert body["tracks"] == [{"trackId": track, "outcome": "unavailable", "reason": "evidence_unavailable"}]


def test_persistent_evidence_transport_fails_the_attempt_as_retryable() -> None:
    platform = FakePlatform()
    platform.add_track([(503, "unavailable")])
    outcome = asyncio.run(_run_analysis(platform))
    assert outcome.status == "failed" and outcome.failure_code == "embedding_evidence_transport_failed"
    assert platform.completions == [] and [item["failureCode"] for item in platform.failures] == ["embedding_evidence_transport_failed"]
    assert platform.failures[0]["analysisId"] == platform.analysis_id and platform.failures[0]["attemptCount"] == 1


def test_an_ambiguous_completion_is_replayed_with_identical_bytes() -> None:
    platform = FakePlatform()
    platform.add_track([_jpeg(100, 100, 7)])
    platform.complete_statuses = [503, 502, 200]
    outcome = asyncio.run(_run_analysis(platform))
    assert outcome.status == "completed"
    assert len(platform.completions) == 3 and len(set(platform.completions)) == 1


def test_a_refused_completion_fails_the_attempt_as_output_invalid() -> None:
    platform = FakePlatform()
    platform.add_track([_jpeg(100, 100, 8)])
    platform.complete_statuses = [422]
    outcome = asyncio.run(_run_analysis(platform))
    assert outcome.failure_code == "embedding_output_invalid" and len(platform.completions) == 1


def test_a_model_fault_fails_the_attempt_as_runtime_failed() -> None:
    class Broken(FixtureEmbeddingModel):
        def embed_images(self, crops):
            raise RuntimeError("onnx exploded")

    platform = FakePlatform()
    platform.add_track([_jpeg(100, 100, 9)])
    outcome = asyncio.run(_run_analysis(platform, Broken(DIMENSION)))
    assert outcome.failure_code == "embedding_runtime_failed" and platform.completions == []


def test_a_non_finite_model_output_fails_the_attempt_as_output_invalid() -> None:
    class NaN(FixtureEmbeddingModel):
        def embed_images(self, crops):
            return np.full((len(crops), self.dimension), np.nan, dtype=np.float32)

    platform = FakePlatform()
    platform.add_track([_jpeg(100, 100, 10)])
    outcome = asyncio.run(_run_analysis(platform, NaN(DIMENSION)))
    assert outcome.failure_code == "embedding_output_invalid" and platform.completions == []


def test_a_lease_lost_on_evidence_neither_fails_nor_completes() -> None:
    platform = FakePlatform()
    platform.add_track([(409, "embedding_attempt_stale")])
    outcome = asyncio.run(_run_analysis(platform))
    assert outcome.status == "lease_lost"
    assert platform.failures == [] and platform.completions == []


def test_a_lease_lost_on_heartbeat_cancels_the_work_and_neither_fails_nor_completes() -> None:
    class Slow(FixtureEmbeddingModel):
        def embed_images(self, crops):
            time.sleep(0.6)
            return super().embed_images(crops)

    platform = FakePlatform()
    platform.add_track([_jpeg(100, 100, 11)])
    platform.add_track([_jpeg(100, 100, 12)])
    platform.heartbeat_status = 409
    outcome = asyncio.run(_run_analysis(platform, Slow(DIMENSION)))
    assert outcome.status == "lease_lost"
    assert platform.failures == [] and platform.completions == []


def test_a_lease_for_another_identity_is_refused() -> None:
    platform = FakePlatform()
    platform.lease_override = {"identity": {**_identity_document(), "fingerprint": "0" * 64}}
    with pytest.raises(EmbeddingApiError, match="another worker or identity"):
        asyncio.run(_run_analysis(platform))
    assert platform.completions == [] and platform.failures == []


def test_the_capability_travels_only_in_headers_never_in_urls_bodies_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    platform = FakePlatform()
    platform.add_track([_jpeg(100, 100, 13)])
    platform.add_track([(503, "unavailable")])  # forces a /fail, whose message is also checked
    platform.text_queries.append({"schemaVersion": "mavi-embedding-control-v1", "queryId": _id(), "workerId": WORKER,
                                  "attemptCount": 1, "leaseExpiresAtUtc": _utc(30), "identityFingerprint": IDENTITY.fingerprint,
                                  "text": "white van"})

    async def scenario() -> None:
        client = _client(platform)
        runner, text = _runner(client), TextQueryRunner(client, worker_id=WORKER, model=FixtureEmbeddingModel(DIMENSION),
                                                         dimension=DIMENSION, maximum_characters=200)
        try:
            await runner.run_once()
            await text.run_once()
        finally:
            runner.close()
            text.close()
            await client.aclose()

    asyncio.run(scenario())
    assert platform.failures and platform.text_completions
    for capability in (platform.capability, platform.text_capability):
        leased_requests = [request for request in platform.requests if not request.url.path.endswith("/lease")]
        assert any(request.headers.get("X-Mavi-Lease-Capability") == capability for request in leased_requests)
        for request in platform.requests:
            assert capability not in str(request.url)
            assert capability.encode() not in request.content
        assert capability not in caplog.text
    for request in platform.requests:
        if request.url.path.endswith("/lease"):
            assert "X-Mavi-Lease-Capability" not in request.headers


# --- text queries ---------------------------------------------------------------------------------------------------


def _text_lease(text: str = "white van", **overrides) -> dict:
    return {"schemaVersion": "mavi-embedding-control-v1", "queryId": _id(), "workerId": WORKER, "attemptCount": 1,
            "leaseExpiresAtUtc": _utc(30), "identityFingerprint": IDENTITY.fingerprint, "text": text, **overrides}


async def _run_text(platform: FakePlatform, model=None):
    client = _client(platform)
    runner = TextQueryRunner(client, worker_id=WORKER, model=model or FixtureEmbeddingModel(DIMENSION), dimension=DIMENSION,
                             maximum_characters=200, completion_retry_seconds=0.0)
    try:
        return await runner.run_once()
    finally:
        runner.close()
        await client.aclose()


def test_text_query_is_embedded_and_completed_against_its_schema() -> None:
    platform = FakePlatform()
    lease = _text_lease()
    platform.text_queries.append(lease)
    outcome = asyncio.run(_run_text(platform))
    assert outcome.status == "completed" and platform.text_failures == []
    body = platform.text_completions[0]
    _schema_validator("embedding-text-query-complete-v1").validate(body)
    assert body["queryId"] == lease["queryId"] and body["attemptCount"] == 1
    expected = l2_normalise_rows(FixtureEmbeddingModel(DIMENSION).embed_texts(["white van"]), DIMENSION)[0]
    assert np.allclose(decode_vector(body["embedding"], DIMENSION), expected, atol=1e-6)


def test_nothing_to_lease_is_idle() -> None:
    assert asyncio.run(_run_text(FakePlatform())) is None


def test_text_runtime_fault_fails_retryable_and_bad_text_fails_for_good() -> None:
    class Broken(FixtureEmbeddingModel):
        def embed_texts(self, texts):
            raise RuntimeError("text tower failed")

    platform = FakePlatform()
    platform.text_queries.append(_text_lease())
    assert asyncio.run(_run_text(platform, Broken(DIMENSION))).failure_code == "embedding_text_runtime_failed"
    platform.text_queries.append(_text_lease(" padded "))
    assert asyncio.run(_run_text(platform)).failure_code == "embedding_text_invalid"
    assert [item["failureCode"] for item in platform.text_failures] == ["embedding_text_runtime_failed", "embedding_text_invalid"]
    assert platform.text_completions == []


def test_text_queries_are_served_while_a_long_analysis_runs() -> None:
    text_done = threading.Event()
    seen: dict[str, bool] = {}

    class Blocking(FixtureEmbeddingModel):
        def embed_images(self, crops):
            # The analysis holds its inference thread until the text query has completed on its own thread.
            seen["text_completed_during_analysis"] = text_done.wait(timeout=10)
            return super().embed_images(crops)

    platform = FakePlatform()
    platform.add_track([_jpeg(100, 100, 14)])
    platform.text_queries.append(_text_lease())
    platform.on_text_complete.append(text_done.set)
    settings = EmbeddingWorkerSettings(api_base_url=BASE, worker_id=WORKER, model_root=".", embedding_manifest_path=str(FIXTURE_MANIFEST),
                                       pipeline_profile_path=str(FIXTURE_PROFILE), heartbeat_interval_seconds=1.0)
    model = Blocking(DIMENSION)

    class ReadySupervisor:
        def __init__(self, _settings) -> None:
            self.state = EmbeddingRuntimeState.READY
            self.runtime = EmbeddingRuntime(IDENTITY, RESOLVED.profile, model, PROVENANCE)

        def start(self) -> None:
            pass

    def client_factory(**kwargs):
        kwargs.pop("verify")
        return EmbeddingApiClient(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(platform)))

    async def fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0.01)

    exit_code = asyncio.run(run_worker(settings, supervisor_factory=ReadySupervisor, client_factory=client_factory,
                                       sleep=fast_sleep, max_iterations=3))
    assert exit_code == 0
    assert seen == {"text_completed_during_analysis": True}
    assert len(platform.text_completions) == 1 and len(platform.completions) == 1


def test_an_unavailable_runtime_never_leases() -> None:
    platform = FakePlatform()

    class Unavailable:
        def __init__(self, _settings) -> None:
            self.state = EmbeddingRuntimeState.UNAVAILABLE

        def start(self) -> None:
            pass

    settings = EmbeddingWorkerSettings(api_base_url=BASE, worker_id=WORKER, model_root=".", embedding_manifest_path=str(FIXTURE_MANIFEST),
                                       pipeline_profile_path=str(FIXTURE_PROFILE))
    assert asyncio.run(run_worker(settings, supervisor_factory=Unavailable, max_iterations=1)) == RUNTIME_UNAVAILABLE_EXIT
    assert platform.requests == []
