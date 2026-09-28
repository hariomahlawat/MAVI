"""The ``attributes`` role: composition, readiness, transport, aggregation and the attempt loop.

S2b plan §9–§14. The role composes through the same Component Binding v2 registry, resolver
and environment policy as the vision role; these tests hold it to that and to the transport
taxonomy (transport is never evidence), header-only capability and lease-loss containment.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from mavi_vision.attributes import contracts
from mavi_vision.attributes.client import (
    AttributeApiClient,
    AttributeApiError,
    AttributeLeaseLost,
    EvidenceTransportError,
    EvidenceUnavailable,
    LeasedAnalysis,
)
from mavi_vision.attributes.contracts import AttributeLease, CompleteResponse, FailResponse, HeartbeatResponse, UploadResponse
from mavi_vision.attributes.inference import CropDecodeError, FixtureAttributeInferencer, VerifiedCrop
from mavi_vision.attributes.main import COMPOSITION_REFUSED_EXIT, RUNTIME_UNAVAILABLE_EXIT, run_worker
from mavi_vision.attributes.pipeline import (
    AggregationPolicy,
    AttributeDefinition,
    MAXIMUM_PREDICTION_ARTIFACT_BYTES,
    load_attribute_pipeline,
    worst_case_prediction_artifact_bytes,
)
from mavi_vision.attributes.predictions import ObservationResult, aggregate_track, encode_predictions
from mavi_vision.attributes.runner import AttributeRunner
from mavi_vision.attributes.settings import AttributeWorkerSettings
from mavi_vision.attributes.supervisor import AttributeRuntimeState, AttributeSupervisor, attribute_composition
from mavi_vision.runtime.binding import load_component_binding
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.resolver import resolve_completion_contract
from tests.attribute_overlay import AttributeOverlay
from tests.resolver_overlay import DEPLOYMENT_PROFILES, _dump

CAPABILITY = "A" * 42 + "A"
FINGERPRINT = "f" * 64
JPEG = b"\xff\xd8\xff\xe0" + bytes(range(64)) + b"\xff\xd9"


@pytest.fixture
def overlay(tmp_path: Path) -> AttributeOverlay:
    return AttributeOverlay.create(tmp_path)


def _start(overlay: AttributeOverlay, **overrides) -> AttributeSupervisor:
    settings = overlay.settings(**overrides)
    supervisor = AttributeSupervisor(settings, attribute_composition(settings))
    supervisor.start()
    return supervisor


# --------------------------------------------------------------------------- composition


def test_the_attributes_role_resolves_through_the_shared_resolver(overlay: AttributeOverlay) -> None:
    supervisor = _start(overlay)
    assert supervisor.state is AttributeRuntimeState.READY
    runtime = supervisor.runtime
    pack = overlay.derived_model_pack_id()
    assert [(item.capability_id, item.model_pack_id) for item in runtime.identity.capabilities] == [
        ("person-attributes", pack),
        ("vehicle-attributes", pack),
    ]
    provenance = runtime.provenance
    assert provenance["provenanceContract"] == "visual-attribute-complete-v1"
    # An unpacked environment is never verified and names no Runtime Pack.
    assert provenance["runtimePackSource"] == "unpacked-environment" and provenance["runtimePackId"] is None
    assert {item["verificationStatus"] for item in provenance["capabilities"]} == {"unverified"}
    assert provenance["componentBindingSha256"] == load_component_binding(overlay.binding_path).component_binding_sha256


def test_production_refuses_the_fixture(overlay: AttributeOverlay) -> None:
    supervisor = _start(overlay, production_mode=True, deployment_profile="P3", device_policy="cpu",
                        deployment_profile_policy_path=DEPLOYMENT_PROFILES)
    assert supervisor.state is AttributeRuntimeState.UNAVAILABLE
    assert supervisor.unavailable_reason == "attribute_development_profile_forbidden"


def test_production_refuses_an_unverified_pack_even_under_a_production_profile(overlay: AttributeOverlay, tmp_path: Path) -> None:
    profile = overlay.pipeline_profile_path
    document = json.loads(profile.read_text(encoding="utf-8"))
    document["developmentOnly"] = False
    _dump(profile, document)
    overlay.write()
    supervisor = _start(overlay, production_mode=True, deployment_profile="P3", device_policy="cpu",
                        deployment_profile_policy_path=DEPLOYMENT_PROFILES)
    assert supervisor.state is AttributeRuntimeState.UNAVAILABLE
    assert supervisor.unavailable_reason == "unverified_release_forbidden"


def test_the_vision_worker_cannot_run_the_attributes_role(overlay: AttributeOverlay) -> None:
    binding = load_component_binding(overlay.binding_path)
    with pytest.raises(ReleaseMetadataError, match="^role_provenance_contract_mismatch$"):
        resolve_completion_contract(
            binding.role("attributes"), override=None, production_mode=False, emittable_versions=("3.0", "3.1", "3.2")
        )


@pytest.mark.parametrize(
    ("role_id", "capability_id", "code"),
    [
        ("vision", "person-attributes", "role_capabilities_contract_mismatch:person-attributes"),
        ("attributes", "detector", "role_capabilities_contract_mismatch:detector"),
    ],
)
def test_a_role_cannot_declare_a_capability_its_contract_does_not_serve(
    overlay: AttributeOverlay, role_id: str, capability_id: str, code: str
) -> None:
    # A capability is bound once: move its binding to the role under test.
    binding = overlay.vision.binding
    role = next(item for item in binding["roles"] if item["roleId"] == role_id)
    role["capabilityIds"] = sorted({*role["capabilityIds"], capability_id})
    source = next(item for item in binding["capabilityBindings"] if item["capabilityId"] == capability_id)
    previous = source["roleId"]
    source["roleId"] = role_id
    for other in binding["roles"]:
        if other["roleId"] == previous:
            other["capabilityIds"] = [item for item in other["capabilityIds"] if item != capability_id]
    binding["roles"] = [item for item in binding["roles"] if item["capabilityIds"]]
    overlay.write()
    if role_id == "vision":
        with pytest.raises(ReleaseMetadataError, match=f"^{code}$"):
            overlay.vision.resolve()
    else:
        supervisor = _start(overlay)
        assert supervisor.unavailable_reason == code


def test_an_attributes_role_naming_another_entry_point_never_starts(overlay: AttributeOverlay) -> None:
    role = next(item for item in overlay.vision.binding["roles"] if item["roleId"] == "attributes")
    role["entryPoint"] = "mavi_vision.worker.main"
    overlay.write()
    assert _start(overlay).unavailable_reason == "role_entry_point_unsupported:attributes"


def test_a_missing_model_pack_leaves_the_role_unavailable_and_it_never_leases(overlay: AttributeOverlay) -> None:
    overlay.manifest_path.unlink()
    created: list[object] = []

    def factory(**kwargs):
        created.append(kwargs)
        raise AssertionError("an UNAVAILABLE worker must not create a lease client")

    assert asyncio.run(run_worker(overlay.settings(), client_factory=factory)) == RUNTIME_UNAVAILABLE_EXIT
    assert created == []


def test_cuda_is_refused_rather_than_substituted(overlay: AttributeOverlay) -> None:
    assert _start(overlay, device_policy="cuda").unavailable_reason == "attribute_device_unsupported:cuda"


def test_a_binding_without_the_role_refuses_composition(overlay: AttributeOverlay) -> None:
    binding = overlay.vision.binding
    binding["roles"] = [item for item in binding["roles"] if item["roleId"] != "attributes"]
    binding["capabilityBindings"] = [item for item in binding["capabilityBindings"] if item["roleId"] != "attributes"]
    overlay.write()
    assert asyncio.run(run_worker(overlay.settings())) == COMPOSITION_REFUSED_EXIT


# --------------------------------------------------------------------------- settings


@pytest.mark.parametrize(("interval", "timeout", "valid"), [(29.0, 15.9, True), (30.0, 15.0, False)])
def test_the_heartbeat_margin_is_bounded_by_the_shortest_lease(interval: float, timeout: float, valid: bool) -> None:
    values = dict(api_base_url="http://h", worker_id="w-1", pipeline_profile_path=Path("p.json"),
                  heartbeat_interval_seconds=interval, request_timeout_seconds=timeout)
    if valid:
        AttributeWorkerSettings(**values)
    else:
        with pytest.raises(ValueError, match="attribute_heartbeat_margin_invalid"):
            AttributeWorkerSettings(**values)


# --------------------------------------------------------------------------- inference and aggregation

ATTRIBUTES = (
    AttributeDefinition("fixture-person-lower", "person-attributes", "person", ("dark", "light", "mid")),
    AttributeDefinition("fixture-person-upper", "person-attributes", "person", ("dark", "light", "mid")),
)
POLICY = AggregationPolicy("mean-score-argmax", "1.0.0", "a" * 64, "mean-score-argmax", 0.5)


def _track(count: int) -> contracts.LeaseTrack:
    return contracts.LeaseTrack.model_validate_json(json.dumps({
        "trackId": str(uuid4()), "objectClass": "person",
        "observations": [{"observationId": str(uuid4()), "role": "representative", "evidenceRank": index,
                          "sizeBytes": 10, "sha256": "b" * 64} for index in range(count)],
    }))


def test_the_fixture_inferencer_is_deterministic_and_decodes_structurally() -> None:
    inferencer = FixtureAttributeInferencer("seed")
    crop = VerifiedCrop("o", 0, hashlib.sha256(JPEG).hexdigest(), JPEG)
    first = inferencer.score(crop, ATTRIBUTES)
    assert first == FixtureAttributeInferencer("seed").score(crop, ATTRIBUTES)
    assert first != FixtureAttributeInferencer("other").score(crop, ATTRIBUTES)
    assert all(abs(sum(values.values()) - 1.0) < 1e-12 for values in first.values())
    with pytest.raises(CropDecodeError):
        inferencer.score(VerifiedCrop("o", 0, "c" * 64, b"GIF89a"), ATTRIBUTES)


def test_mean_score_argmax_observes_above_the_floor_and_is_unknown_below_it() -> None:
    track = _track(2)
    first, second = track.observations
    observations = (
        ObservationResult(first.observation_id, 0, scores={
            "fixture-person-lower": {"dark": 0.8, "light": 0.1, "mid": 0.1},
            "fixture-person-upper": {"dark": 0.4, "light": 0.3, "mid": 0.3}}),
        ObservationResult(second.observation_id, 1, scores={
            "fixture-person-lower": {"dark": 0.9, "light": 0.05, "mid": 0.05},
            "fixture-person-upper": {"dark": 0.3, "light": 0.4, "mid": 0.3}}),
    )
    result = aggregate_track(track, observations, ATTRIBUTES, POLICY)
    lower, upper = result.decisions
    assert (lower.outcome, lower.value, lower.supporting_observation_id) == ("observed", "dark", second.observation_id)
    assert lower.confidence == pytest.approx(0.85)
    # Mean 0.35 for dark and light: under the floor, and Unknown asserts nothing.
    assert (upper.outcome, upper.value, upper.confidence, upper.supporting_observation_id) == ("unknown", None, None, None)


def test_a_track_with_no_scored_crop_is_unavailable_with_its_most_severe_reason() -> None:
    track = _track(2)
    observations = (
        ObservationResult(track.observations[0].observation_id, 0, reason="evidence_decode_failed"),
        ObservationResult(track.observations[1].observation_id, 1, reason="evidence_integrity_failed"),
    )
    result = aggregate_track(track, observations, ATTRIBUTES, POLICY)
    assert (result.outcome, result.reason, result.decisions) == ("unavailable", "evidence_integrity_failed", ())
    empty = aggregate_track(_track(0), (), ATTRIBUTES, POLICY)
    assert (empty.outcome, empty.reason) == ("unavailable", "no_accepted_evidence")


def test_the_worst_case_bound_is_an_upper_bound_of_the_real_encoder() -> None:
    """The largest accepted schema's worst artefact, from the production encoder, fits its bound."""
    vectors = json.loads((Path(__file__).resolve().parents[3] / "contracts/test-vectors/visual-attribute-artifact-bound-v1.json").read_text())
    vector = next(item for item in vectors["vectors"] if item["name"] == "largest-accepted")
    attributes = tuple(AttributeDefinition(i["attributeType"], i["capabilityId"], i["objectClass"], tuple(i["values"])) for i in vector["attributes"])
    longest = max((value for attribute in attributes for value in attribute.values), key=len)
    worst_score = -2.2250738585072014e-308  # a 24-character shortest round-trip double
    lease = _lease(tracks=[
        {"trackId": str(uuid4()), "objectClass": "person",
         "observations": [{"observationId": str(uuid4()), "role": "late-diverse", "evidenceRank": rank,
                           "sizeBytes": 1, "sha256": "b" * 64} for rank in range(4)]}
        for _ in range(contracts.MAXIMUM_ANALYSIS_TRACKS)])
    tracks = []
    from mavi_vision.attributes.predictions import Decision, TrackResult
    for track in lease.tracks:
        observations = tuple(ObservationResult(item.observation_id, item.evidence_rank, scores={
            attribute.attribute_type: {value: worst_score for value in attribute.values} for attribute in attributes})
            for item in track.observations)
        decisions = tuple(Decision(attribute.attribute_type, "observed",
                                   max(attribute.values, key=len), 0.12345678901234568, track.observations[0].observation_id)
                          for attribute in attributes)
        tracks.append(TrackResult(track.track_id, "analysed", None, observations, decisions))
    encoded = encode_predictions(lease, tuple(tracks))
    assert len(encoded) <= worst_case_prediction_artifact_bytes(attributes) <= MAXIMUM_PREDICTION_ARTIFACT_BYTES
    assert longest.endswith("z")


# --------------------------------------------------------------------------- client transport


def _lease(tracks: list[dict] | None = None, *, expires_in: float = 120.0, worker: str = "attributes-01") -> AttributeLease:
    now = datetime.now(timezone.utc)
    return AttributeLease.model_validate_json(json.dumps(_lease_document(tracks, expires_in=expires_in, worker=worker, now=now)))


def _lease_document(tracks, *, expires_in=120.0, worker="attributes-01", now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    stamp = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"  # noqa: E731
    return {
        "schemaVersion": contracts.CONTROL_VERSION, "analysisId": str(uuid4()), "processingRunId": str(uuid4()),
        "workerId": worker, "attemptCount": 1,
        "leaseExpiresAtUtc": stamp(now + timedelta(seconds=expires_in)), "deadlineAtUtc": stamp(now + timedelta(hours=1)),
        "identity": {"fingerprint": FINGERPRINT, "attributeSchemaId": "s", "attributeSchemaVersion": "1.0.0",
                     "attributeSchemaSha256": "1" * 64, "pipelineId": "p", "pipelineVersion": "1.0.0",
                     "aggregationPolicyId": "a", "aggregationPolicyVersion": "1.0.0", "aggregationPolicySha256": "2" * 64,
                     "capabilities": [], "parametersSha256": "3" * 64},
        "tracks": tracks if tracks is not None else [],
    }


def _client(handler, **kwargs) -> AttributeApiClient:
    return AttributeApiClient(
        api_base_url="http://platform", worker_id="attributes-01", identity_fingerprint=FINGERPRINT,
        request_timeout_seconds=5, evidence_retry_backoff_seconds=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs)


def _observation(content: bytes = JPEG) -> contracts.LeaseObservation:
    return contracts.LeaseObservation.model_validate_json(json.dumps({
        "observationId": str(uuid4()), "role": "representative", "evidenceRank": 0,
        "sizeBytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}))


def test_the_capability_travels_only_in_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/lease"):
            return httpx.Response(200, headers={contracts.CAPABILITY_HEADER: CAPABILITY}, json=_lease_document([]))
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"schemaVersion": contracts.CONTROL_VERSION, "leaseExpiresAtUtc": "2030-01-01T00:00:00.000000Z"})
        return httpx.Response(200, content=JPEG)

    async def scenario() -> None:
        client = _client(handler)
        leased = await client.lease()
        assert leased is not None and leased.capability == CAPABILITY
        assert CAPABILITY not in repr(leased)
        await client.heartbeat(leased)
        await client.read_evidence(leased, _observation())

    asyncio.run(scenario())
    lease_request, *rest = seen
    assert contracts.CAPABILITY_HEADER not in lease_request.headers
    for request in rest:
        assert request.headers[contracts.CAPABILITY_HEADER] == CAPABILITY
        assert CAPABILITY not in str(request.url) and CAPABILITY.encode() not in request.content


def test_a_lease_response_over_its_bound_is_refused_unread() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={contracts.CAPABILITY_HEADER: CAPABILITY,
                                            "content-length": str(contracts.MAXIMUM_LEASE_RESPONSE_BYTES + 1)},
                              content=b" " * (contracts.MAXIMUM_LEASE_RESPONSE_BYTES + 1))

    with pytest.raises(AttributeApiError, match="exceeds its bound"):
        asyncio.run(_client(handler).lease())


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        ([httpx.Response(422, json={"code": "visual_attribute_evidence_missing"})], EvidenceUnavailable("evidence_missing")),
        ([httpx.Response(422, json={"code": "visual_attribute_evidence_integrity_failed"})], EvidenceUnavailable("evidence_integrity_failed")),
        ([httpx.Response(503, json={"code": "visual_attribute_evidence_unreadable"}), httpx.Response(200, content=JPEG)], JPEG),
        ([httpx.Response(200, content=JPEG[:-1])] * 3, EvidenceTransportError),
        ([httpx.Response(503)] * 3, EvidenceTransportError),
        ([httpx.Response(200, content=b"\x00" * len(JPEG))] * 3, EvidenceUnavailable("evidence_integrity_failed")),
        ([httpx.Response(200, content=b"\x00" * len(JPEG)), httpx.Response(200, content=JPEG)], JPEG),
        ([httpx.Response(409, json={"code": "visual_attribute_lease_invalid"})], AttributeLeaseLost),
    ],
    ids=["missing", "integrity", "transient-then-ok", "truncated", "unavailable-5xx", "persistent-digest", "one-bad-read", "lease-lost"],
)
def test_evidence_transport_is_never_evidence(responses, expected) -> None:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    client = _client(handler, evidence_read_attempts=3)
    leased = LeasedAnalysis(_lease(), CAPABILITY)
    if isinstance(expected, type):
        with pytest.raises(expected):
            asyncio.run(client.read_evidence(leased, _observation()))
    else:
        assert asyncio.run(client.read_evidence(leased, _observation())) == expected


def test_a_failure_message_never_carries_the_capability() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"schemaVersion": contracts.CONTROL_VERSION, "outcome": "requeued"})

    asyncio.run(_client(handler).fail(LeasedAnalysis(_lease(), CAPABILITY), "visual_attribute_inference_failed", f"x {CAPABILITY}"))
    assert CAPABILITY not in bodies[0]["failureMessage"]


# --------------------------------------------------------------------------- the attempt loop


class FakeApi:
    def __init__(self, lease: AttributeLease, *, evidence=None, heartbeat=None, complete=None) -> None:
        self.leased = LeasedAnalysis(lease, CAPABILITY)
        self.evidence = evidence or (lambda observation: JPEG)
        self.heartbeat_behaviour = heartbeat
        self.complete_behaviour = complete or []
        self.calls: list[str] = []
        self.uploaded: bytes | None = None
        self.completions: list[bytes] = []
        self.failures: list[tuple[str, str | None]] = []
        self.heartbeats = 0

    async def lease(self):
        self.calls.append("lease")
        return self.leased

    async def heartbeat(self, leased):
        self.heartbeats += 1
        if self.heartbeat_behaviour is not None:
            return await self.heartbeat_behaviour(self.heartbeats)
        return HeartbeatResponse.model_construct(schema_version=contracts.CONTROL_VERSION,
                                                 lease_expires_at_utc=datetime.now(timezone.utc) + timedelta(seconds=120))

    async def fail(self, leased, code, message):
        self.failures.append((code, message))
        return FailResponse.model_construct(schema_version=contracts.CONTROL_VERSION, outcome="requeued")

    async def read_evidence(self, leased, observation):
        result = self.evidence(observation)
        if isinstance(result, Exception):
            raise result
        return result

    async def upload(self, leased, content):
        self.uploaded = content
        return UploadResponse.model_construct(schema_version=contracts.CONTROL_VERSION, status="stored", size_bytes=len(content),
                              sha256=hashlib.sha256(content).hexdigest())

    async def complete(self, leased, body):
        self.completions.append(body)
        if self.complete_behaviour:
            behaviour = self.complete_behaviour.pop(0)
            if isinstance(behaviour, Exception):
                raise behaviour
        return CompleteResponse.model_construct(schema_version=contracts.CONTROL_VERSION, analysis_id=leased.lease.analysis_id,
                                processing_run_id=leased.lease.processing_run_id, status="completed",
                                completed_at_utc=datetime.now(timezone.utc), tracks_analysed=1, tracks_unavailable=0)


def _runner(api: FakeApi, overlay_profile, *, inferencer=None, heartbeat_interval=60.0) -> AttributeRunner:
    return AttributeRunner(api, worker_id="attributes-01", profile=overlay_profile,
                           inferencer=inferencer or FixtureAttributeInferencer("seed"), provenance={"p": 1},
                           heartbeat_interval_seconds=heartbeat_interval, request_timeout_seconds=1.0,
                           completion_retry_seconds=0.0)


@pytest.fixture
def profile():
    return load_attribute_pipeline(Path(__file__).resolve().parents[3] / "tests/fixtures/visual-attributes/fixture-pipeline-v1.json")


def _person_lease(count: int = 2, **kwargs) -> AttributeLease:
    return _lease(tracks=[{"trackId": str(uuid4()), "objectClass": "person",
                           "observations": [{"observationId": str(uuid4()), "role": "representative", "evidenceRank": rank,
                                             "sizeBytes": len(JPEG), "sha256": hashlib.sha256(JPEG).hexdigest()}
                                            for rank in range(count)]}], **kwargs)


def test_an_attempt_uploads_then_completes_with_rows_equal_to_the_artefact(profile) -> None:
    api = FakeApi(_person_lease())
    outcome = asyncio.run(_runner(api, profile).run_once())
    assert outcome.status == "completed"
    artefact = json.loads(api.uploaded)
    body = json.loads(api.completions[0])
    assert body["payload"]["predictionArtifact"]["sha256"] == hashlib.sha256(api.uploaded).hexdigest()
    assert body["payload"]["tracks"][0]["attributes"] == artefact["tracks"][0]["decisions"]
    assert api.uploaded.endswith(b"\n") and CAPABILITY.encode() not in api.uploaded + api.completions[0]


def test_evidence_transport_fails_the_attempt_as_retryable_and_never_as_unavailable(profile) -> None:
    api = FakeApi(_person_lease(), evidence=lambda observation: EvidenceTransportError("reset"))
    outcome = asyncio.run(_runner(api, profile).run_once())
    assert (outcome.status, outcome.failure_code) == ("failed", "visual_attribute_evidence_transport_failed")
    assert api.uploaded is None and api.completions == []
    assert contracts.FAILURE_CODE_RETRYABLE[api.failures[0][0]] is True


def test_authoritative_evidence_conditions_become_unavailable_tracks(profile) -> None:
    api = FakeApi(_person_lease(), evidence=lambda observation: EvidenceUnavailable("evidence_missing"))
    assert asyncio.run(_runner(api, profile).run_once()).status == "completed"
    track = json.loads(api.completions[0])["payload"]["tracks"][0]
    assert (track["outcome"], track["reason"], track["attributes"]) == ("unavailable", "evidence_missing", [])


def test_a_lost_lease_cancels_the_work_and_is_never_answered_with_fail(profile) -> None:
    class SlowInferencer(FixtureAttributeInferencer):
        def score(self, crop, attributes):
            import time
            time.sleep(0.5)
            return super().score(crop, attributes)

    async def refuse(count):
        raise AttributeLeaseLost("gone", status_code=409, code="visual_attribute_lease_invalid")

    api = FakeApi(_person_lease(count=4, expires_in=0.3), heartbeat=refuse)
    outcome = asyncio.run(_runner(api, profile, inferencer=SlowInferencer("seed"), heartbeat_interval=0.05).run_once())
    assert outcome.status == "lease_lost"
    assert api.failures == [] and api.uploaded is None and api.completions == []


def test_the_heartbeat_runs_concurrently_with_slow_inference(profile) -> None:
    class SlowInferencer(FixtureAttributeInferencer):
        def score(self, crop, attributes):
            import time
            time.sleep(0.4)
            return super().score(crop, attributes)

    api = FakeApi(_person_lease(count=3, expires_in=2.5))
    runner = AttributeRunner(api, worker_id="attributes-01", profile=profile, inferencer=SlowInferencer("seed"),
                             provenance={}, heartbeat_interval_seconds=0.1, request_timeout_seconds=0.05)
    assert asyncio.run(runner.run_once()).status == "completed"
    assert api.heartbeats >= 5


def test_an_ambiguous_completion_replays_the_identical_body(profile) -> None:
    api = FakeApi(_person_lease(), complete=[AttributeApiError("reset"), AttributeApiError("503", status_code=503)])
    assert asyncio.run(_runner(api, profile).run_once()).status == "completed"
    assert len(api.completions) == 3 and len(set(api.completions)) == 1


def test_a_refused_completion_is_a_terminal_output_failure(profile) -> None:
    api = FakeApi(_person_lease(), complete=[AttributeApiError("bad", status_code=400, code="visual_attribute_row_invalid")])
    outcome = asyncio.run(_runner(api, profile).run_once())
    assert (outcome.status, outcome.failure_code) == ("failed", "visual_attribute_output_invalid")
    assert contracts.FAILURE_CODE_RETRYABLE["visual_attribute_output_invalid"] is False


def test_nothing_leasable_is_none(profile) -> None:
    class Empty(FakeApi):
        async def lease(self):
            return None

    assert asyncio.run(_runner(Empty(_person_lease()), profile).run_once()) is None


def test_contract_constants_match_the_platform() -> None:
    """The worker's copies of the platform's bounds and vocabularies (VisualAttributeContractRules)."""
    source = (Path(__file__).resolve().parents[3] / "src/platform/Mavi.Contracts/Worker/Attributes/VisualAttributeContractRules.cs").read_text()
    for value in (contracts.CONTROL_VERSION, contracts.PROVENANCE_CONTRACT, contracts.PREDICTIONS_SCHEMA_VERSION,
                  contracts.CAPABILITY_HEADER, contracts.ATTEMPT_HEADER, contracts.WORKER_HEADER,
                  contracts.CONTENT_SHA256_HEADER, contracts.ROUTE_PREFIX, *contracts.UNAVAILABLE_REASONS,
                  *contracts.FAILURE_CODE_RETRYABLE):
        assert f'"{value}"' in source, value
    for code, retryable in contracts.FAILURE_CODE_RETRYABLE.items():
        assert f'["{code}"] = {"true" if retryable else "false"}' in source
    assert "MaximumLeaseResponseBytes = 16L * 1024 * 1024" in source
    assert UUID(int=0)


def test_the_resolver_serves_exactly_the_attribute_capabilities() -> None:
    from mavi_vision.attributes.pipeline import ATTRIBUTE_CAPABILITIES
    from mavi_vision.runtime.resolver import ATTRIBUTE_PROVENANCE_CONTRACT, CONTRACT_CAPABILITIES

    assert CONTRACT_CAPABILITIES[ATTRIBUTE_PROVENANCE_CONTRACT] == frozenset(ATTRIBUTE_CAPABILITIES)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (AttributeApiError("reset"), "visual_attribute_upload_transport_failed"),
        (AttributeApiError("changed", status_code=422, code="vision_result_artifact_integrity_failed"), "visual_attribute_upload_transport_failed"),
        (AttributeApiError("too large", status_code=413), "visual_attribute_contract_violation"),
    ],
    ids=["transport", "digest-in-transit", "refused"],
)
def test_upload_failures_are_classified(profile, error, code) -> None:
    class Refusing(FakeApi):
        async def upload(self, leased, content):
            raise error

    api = Refusing(_person_lease())
    outcome = asyncio.run(_runner(api, profile).run_once())
    assert (outcome.status, outcome.failure_code) == ("failed", code)
    assert api.completions == []
