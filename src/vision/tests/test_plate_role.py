"""The ``plates`` role: composition, readiness, transport and the attempt loop (Stage 4 PR-3).

The role composes through the same Component Binding v2 registry, resolver and environment policy as
every role; these tests hold it to that, to the identity vector, to the transport taxonomy (transport is
never evidence), to header-only capability, to lease-loss containment, and to the bounded profile
(output beyond a configured bound fails the attempt and is never truncated).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from mavi_vision.plates import contracts
from mavi_vision.plates.client import EvidenceTransportError, EvidenceUnavailable, LeasedAnalysis, PlateApiClient, PlateLeaseLost
from mavi_vision.plates.contracts import CompleteResponse, FailResponse, HeartbeatResponse, PlateLease, UploadResponse
from mavi_vision.plates.inference import PlateBox, Reading
from mavi_vision.plates.main import COMPOSITION_REFUSED_EXIT, RUNTIME_UNAVAILABLE_EXIT, run_worker
from mavi_vision.plates.profile import load_plate_pipeline, plate_identity
from mavi_vision.plates.runner import PlateRunner
from mavi_vision.plates.supervisor import PlateRuntimeState, PlateSupervisor, plate_composition
from mavi_vision.runtime.binding import load_component_binding
from mavi_vision.runtime.resolver import CONTRACT_CAPABILITIES, IMPLEMENTED_ROLE_ENTRY_POINTS, PLATE_PROVENANCE_CONTRACT
from tests.plate_overlay import PlateOverlay
from tests.resolver_overlay import DEPLOYMENT_PROFILES, _dump

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "A" * 43


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (240, 180), (90, 90, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = _jpeg()


@pytest.fixture
def overlay(tmp_path: Path) -> PlateOverlay:
    return PlateOverlay.create(tmp_path)


def _start(overlay: PlateOverlay, **overrides) -> PlateSupervisor:
    settings = overlay.settings(**overrides)
    supervisor = PlateSupervisor(settings, plate_composition(settings))
    supervisor.start()
    return supervisor


# --------------------------------------------------------------------------- composition


def test_the_plates_role_resolves_through_the_shared_resolver(overlay: PlateOverlay) -> None:
    supervisor = _start(overlay)
    assert supervisor.state is PlateRuntimeState.READY, supervisor.unavailable_reason
    runtime = supervisor.runtime
    pack = overlay.derived_model_pack_id()
    assert [(item.capability_id, item.model_pack_id) for item in runtime.identity.capabilities] == [("ocr", pack), ("plate-detector", pack)]
    provenance = runtime.provenance
    assert provenance["provenanceContract"] == "plate-complete-v1"
    assert provenance["roleId"] == "plates"
    assert provenance["runtimePackSource"] == "unpacked-environment" and provenance["runtimePackId"] is None
    assert {item["verificationStatus"] for item in provenance["capabilities"]} == {"unverified"}
    assert [item["qualificationId"] for item in provenance["capabilities"]] == ["ocr-fixture", "plate-detector-fixture"]
    assert provenance["componentBindingSha256"] == load_component_binding(overlay.binding_path).component_binding_sha256


def test_the_identity_is_the_cross_language_vector() -> None:
    vector = json.loads((ROOT / "contracts/test-vectors/plate-identity-v1.json").read_text(encoding="utf-8"))["vectors"][0]
    profile = load_plate_pipeline(ROOT / vector["pipelineProfile"])
    identity = plate_identity(profile, vector["capabilities"])
    assert identity.canonical == vector["canonicalIdentity"]
    assert identity.fingerprint == vector["fingerprint"]


def test_production_refuses_the_fixture(overlay: PlateOverlay) -> None:
    supervisor = _start(overlay, production_mode=True, deployment_profile="P3", device_policy="cpu",
                        deployment_profile_policy_path=DEPLOYMENT_PROFILES)
    assert supervisor.state is PlateRuntimeState.UNAVAILABLE
    assert supervisor.unavailable_reason == "plate_development_profile_forbidden"


def test_a_profile_outside_the_bounded_v1_profile_never_starts(overlay: PlateOverlay) -> None:
    directory = overlay.pipeline_profile_path.parent
    parameters = json.loads((directory / "fixture-parameters-v1.json").read_text(encoding="utf-8"))
    parameters["maxReadingsPerPlate"] = 4
    _dump(directory / "fixture-parameters-v1.json", parameters)
    profile = json.loads(overlay.pipeline_profile_path.read_text(encoding="utf-8"))
    profile["parameters"]["sha256"] = hashlib.sha256((directory / "fixture-parameters-v1.json").read_bytes()).hexdigest()
    _dump(overlay.pipeline_profile_path, profile)
    overlay.write()
    assert _start(overlay).unavailable_reason == "plate_parameters_invalid:worst_case_exceeds_cap"


def test_cuda_is_refused_rather_than_substituted(overlay: PlateOverlay) -> None:
    assert _start(overlay, device_policy="cuda").unavailable_reason == "plate_device_unsupported:cuda"


def test_a_plates_role_naming_another_entry_point_never_starts(overlay: PlateOverlay) -> None:
    role = next(item for item in overlay.vision.binding["roles"] if item["roleId"] == "plates")
    role["entryPoint"] = "mavi_vision.attributes.main"
    overlay.write()
    assert _start(overlay).unavailable_reason == "role_entry_point_unsupported:plates"


def test_a_missing_model_pack_leaves_the_role_unavailable_and_it_never_leases(overlay: PlateOverlay) -> None:
    overlay.manifest_path.unlink()

    def factory(**kwargs):
        raise AssertionError("an UNAVAILABLE worker must not create a lease client")

    assert asyncio.run(run_worker(overlay.settings(), client_factory=factory)) == RUNTIME_UNAVAILABLE_EXIT


def test_verify_only_reports_a_ready_runtime_without_ever_leasing(overlay: PlateOverlay) -> None:
    def factory(**kwargs):
        raise AssertionError("a verify-only run must not create a lease client")

    assert asyncio.run(run_worker(overlay.settings(verify_only=True), client_factory=factory)) == 0


def test_verify_only_still_refuses_an_unavailable_runtime(overlay: PlateOverlay) -> None:
    overlay.manifest_path.unlink()
    assert asyncio.run(run_worker(overlay.settings(verify_only=True))) == RUNTIME_UNAVAILABLE_EXIT


def test_a_binding_without_the_role_refuses_composition(overlay: PlateOverlay) -> None:
    binding = overlay.vision.binding
    binding["roles"] = [item for item in binding["roles"] if item["roleId"] != "plates"]
    binding["capabilityBindings"] = [item for item in binding["capabilityBindings"] if item["roleId"] != "plates"]
    overlay.write()
    assert asyncio.run(run_worker(overlay.settings())) == COMPOSITION_REFUSED_EXIT


def test_the_resolver_serves_exactly_the_plate_capabilities() -> None:
    assert CONTRACT_CAPABILITIES[PLATE_PROVENANCE_CONTRACT] == frozenset({"ocr", "plate-detector"})
    assert IMPLEMENTED_ROLE_ENTRY_POINTS["plates"] == "mavi_vision.plates.main"


# --------------------------------------------------------------------------- transport


def _lease_document(observations: int = 2, roles=("representative", "near-view", "early-diverse", "late-diverse"), expires_in: float = 120.0) -> dict:
    lease = json.loads((ROOT / "contracts/examples/plate-lease-v1.example.json").read_text(encoding="utf-8"))
    lease["leaseExpiresAtUtc"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    lease["tracks"] = [{
        "trackId": str(uuid4()), "objectClass": "vehicle",
        "observations": [{"observationId": str(uuid4()), "role": roles[rank], "evidenceRank": rank, "sizeBytes": len(JPEG),
                          "sha256": hashlib.sha256(JPEG).hexdigest()} for rank in range(observations)],
    }]
    return lease


def _lease(**kwargs) -> PlateLease:
    return PlateLease.model_validate_json(json.dumps(_lease_document(**kwargs)))


def _client(handler) -> PlateApiClient:
    lease = _lease()
    return PlateApiClient(api_base_url="http://platform", worker_id="plates-01", identity_fingerprint=lease.identity.fingerprint,
                          request_timeout_seconds=1.0, evidence_retry_backoff_seconds=0.0,
                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_the_capability_travels_only_in_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/lease"):
            return httpx.Response(200, json=_lease_document(), headers={contracts.CAPABILITY_HEADER: CAPABILITY})
        return httpx.Response(200, json={"schemaVersion": contracts.CONTROL_VERSION, "leaseExpiresAtUtc": "2099-01-01T00:00:00Z"})

    async def run():
        client = _client(handler)
        leased = await client.lease()
        await client.heartbeat(leased)
        return leased

    leased = asyncio.run(run())
    assert CAPABILITY not in repr(leased)
    assert seen[1].headers[contracts.CAPABILITY_HEADER] == CAPABILITY
    assert all(CAPABILITY.encode() not in request.content and CAPABILITY not in str(request.url) for request in seen)


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        ([httpx.Response(422, json={"code": "plate_evidence_missing"})], EvidenceUnavailable("evidence_missing")),
        ([httpx.Response(422, json={"code": "plate_evidence_integrity_failed"})], EvidenceUnavailable("evidence_integrity_failed")),
        ([httpx.Response(503, json={"code": "plate_evidence_unreadable"})] * 3, EvidenceTransportError),
        ([httpx.Response(200, content=b"x" * len(JPEG))] * 3, EvidenceUnavailable("evidence_integrity_failed")),
        ([httpx.Response(409, json={"code": "plate_lease_invalid"})], PlateLeaseLost),
    ],
)
def test_evidence_transport_is_never_evidence(responses, expected) -> None:
    queue = list(responses)
    leased = LeasedAnalysis(_lease(), CAPABILITY)
    client = _client(lambda request: queue.pop(0))
    observation = leased.lease.tracks[0].observations[0]
    if isinstance(expected, type):
        with pytest.raises(expected):
            asyncio.run(client.read_evidence(leased, observation))
    else:
        assert asyncio.run(client.read_evidence(leased, observation)) == expected


# --------------------------------------------------------------------------- the attempt loop


class FakeApi:
    def __init__(self, lease: PlateLease, *, evidence=None, heartbeat=None, complete=None) -> None:
        self.leased = LeasedAnalysis(lease, CAPABILITY)
        self.evidence = evidence or (lambda observation: JPEG)
        self.heartbeat_behaviour = heartbeat
        self.complete_behaviour = complete or []
        self.uploaded: bytes | None = None
        self.completions: list[bytes] = []
        self.failures: list[tuple[str, str | None]] = []
        self.reads: list[str] = []
        self.heartbeats = 0

    async def lease(self):
        return self.leased

    async def heartbeat(self, leased):
        self.heartbeats += 1
        if self.heartbeat_behaviour is not None:
            return await self.heartbeat_behaviour(self.heartbeats)
        return HeartbeatResponse.model_construct(schema_version=contracts.CONTROL_VERSION,
                                                 lease_expires_at_utc=datetime.now(timezone.utc) + timedelta(seconds=120))

    async def fail(self, leased, code, message):
        self.failures.append((code, message))
        return FailResponse.model_construct(schema_version=contracts.CONTROL_VERSION, outcome="failed")

    async def read_evidence(self, leased, observation):
        self.reads.append(observation.role)
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


class Detector:
    def __init__(self, boxes=None) -> None:
        self.boxes = boxes if boxes is not None else [PlateBox(40, 100, 60, 15, 0.9)]

    def detect(self, crop, verified):
        return list(self.boxes)


class Recogniser:
    def __init__(self, readings=None, delay: float = 0.0) -> None:
        self.readings = readings if readings is not None else [Reading("KA 01 AB 1234", 0.8)]
        self.delay = delay

    def read(self, region, verified, box):
        if self.delay:
            import time
            time.sleep(self.delay)
        return list(self.readings)


@pytest.fixture
def parameters():
    return load_plate_pipeline(ROOT / "tests/fixtures/plates/fixture-pipeline-v1.json").parameters


def _runner(api: FakeApi, parameters, *, detector=None, recogniser=None, heartbeat_interval: float = 60.0) -> PlateRunner:
    return PlateRunner(api, worker_id="plates-01", parameters=parameters, detector=detector or Detector(),
                       recogniser=recogniser or Recogniser(), provenance={"p": 1}, heartbeat_interval_seconds=heartbeat_interval,
                       request_timeout_seconds=1.0, completion_retry_seconds=0.0)


def test_an_attempt_uploads_then_completes_with_facts_equal_to_the_artefact(parameters) -> None:
    api = FakeApi(_lease())
    outcome = asyncio.run(_runner(api, parameters).run_once())
    assert outcome.status == "completed"
    artefact = json.loads(api.uploaded)
    body = json.loads(api.completions[0])
    assert body["payload"]["predictionArtifact"]["sha256"] == hashlib.sha256(api.uploaded).hexdigest()
    track = body["payload"]["tracks"][0]
    assert (track["outcome"], len(track["plateObservations"])) == ("analysed", 2)
    assert track["texts"][0]["supportCount"] == 2
    assert artefact["tracks"][0]["crops"][0]["detections"][0]["plate"]["readings"][0]["rawText"] == "KA 01 AB 1234"
    assert api.uploaded.endswith(b"\n") and CAPABILITY.encode() not in api.uploaded + api.completions[0]


def test_an_excluded_role_is_recorded_and_never_read(parameters) -> None:
    excluded = type(parameters)(**{**{name: getattr(parameters, name) for name in parameters.__slots__},
                                   "excluded_roles": frozenset({"representative"})})
    api = FakeApi(_lease())
    assert asyncio.run(_runner(api, excluded).run_once()).status == "completed"
    assert api.reads == ["near-view"]
    crops = json.loads(api.uploaded)["tracks"][0]["crops"]
    assert [crop["status"] for crop in crops] == ["excluded", "scored"]


def test_a_detector_beyond_its_configured_bound_fails_the_attempt_and_nothing_is_published(parameters) -> None:
    boxes = [PlateBox(10, 10, 20, 10, 0.9), PlateBox(40, 40, 20, 10, 0.8), PlateBox(70, 70, 20, 10, 0.7)]
    api = FakeApi(_lease())
    outcome = asyncio.run(_runner(api, parameters, detector=Detector(boxes)).run_once())
    assert (outcome.status, outcome.failure_code) == ("failed", "plate_output_invalid")
    assert contracts.FAILURE_CODE_RETRYABLE["plate_output_invalid"] is False
    assert api.uploaded is None and api.completions == []


def test_a_recogniser_beyond_its_configured_bound_fails_the_attempt(parameters) -> None:
    readings = [Reading(text, 0.9 - index / 10) for index, text in enumerate(["A", "B", "C", "D"])]
    api = FakeApi(_lease())
    outcome = asyncio.run(_runner(api, parameters, recogniser=Recogniser(readings)).run_once())
    assert outcome.failure_code == "plate_output_invalid"
    assert api.uploaded is None


def test_evidence_transport_fails_the_attempt_as_retryable_and_never_as_unavailable(parameters) -> None:
    api = FakeApi(_lease(), evidence=lambda observation: EvidenceTransportError("reset"))
    outcome = asyncio.run(_runner(api, parameters).run_once())
    assert (outcome.status, outcome.failure_code) == ("failed", "plate_evidence_transport_failed")
    assert contracts.FAILURE_CODE_RETRYABLE[api.failures[0][0]] is True
    assert api.uploaded is None


def test_authoritative_evidence_conditions_become_unavailable_tracks(parameters) -> None:
    api = FakeApi(_lease(), evidence=lambda observation: EvidenceUnavailable("evidence_missing"))
    assert asyncio.run(_runner(api, parameters).run_once()).status == "completed"
    track = json.loads(api.completions[0])["payload"]["tracks"][0]
    assert (track["outcome"], track["reason"], track["plateObservations"]) == ("unavailable", "evidence_missing", [])


def test_a_lost_lease_cancels_the_work_and_is_never_answered_with_fail(parameters) -> None:
    async def refuse(count):
        raise PlateLeaseLost("gone", status_code=409, code="plate_lease_invalid")

    api = FakeApi(_lease(observations=4, expires_in=0.3), heartbeat=refuse)
    outcome = asyncio.run(_runner(api, parameters, recogniser=Recogniser(delay=0.5), heartbeat_interval=0.05).run_once())
    assert outcome.status == "lease_lost"
    assert api.failures == [] and api.uploaded is None and api.completions == []


def test_an_ambiguous_completion_replays_the_identical_body(parameters) -> None:
    from mavi_vision.plates.client import PlateApiError

    api = FakeApi(_lease(), complete=[PlateApiError("timeout"), PlateApiError("503", status_code=503)])
    assert asyncio.run(_runner(api, parameters).run_once()).status == "completed"
    assert len(api.completions) == 3 and len(set(api.completions)) == 1


def test_a_contradicted_evidence_claim_fails_the_attempt_as_retryable(parameters) -> None:
    from mavi_vision.plates.client import PlateApiError

    refusal = PlateApiError("422", status_code=422, code=contracts.EVIDENCE_CLAIM_CONTRADICTED)
    api = FakeApi(_lease(), complete=[refusal])
    outcome = asyncio.run(_runner(api, parameters).run_once())
    assert (outcome.status, outcome.failure_code) == ("failed", "plate_evidence_claim_contradicted")
    assert contracts.FAILURE_CODE_RETRYABLE["plate_evidence_claim_contradicted"] is True
    assert len(api.completions) == 1


def test_a_platform_publication_refusal_is_not_blamed_on_the_worker_output(parameters) -> None:
    from mavi_vision.plates.client import PlateApiError

    refusal = PlateApiError("422", status_code=422, code=contracts.PERSISTENCE_REFUSED)
    api = FakeApi(_lease(), complete=[refusal])
    outcome = asyncio.run(_runner(api, parameters).run_once())
    assert (outcome.status, outcome.failure_code) == ("failed", "plate_publication_refused")
    assert contracts.FAILURE_CODE_RETRYABLE["plate_publication_refused"] is False
    assert len(api.completions) == 1


def test_contract_constants_match_the_platform() -> None:
    source = (ROOT / "src/platform/Mavi.Contracts/Worker/Plates/PlateContractRules.cs").read_text(encoding="utf-8")
    for constant, value in [
        ("SchemaVersion", contracts.CONTROL_VERSION),
        ("ProvenanceContract", contracts.PROVENANCE_CONTRACT),
        ("PredictionsSchemaVersion", contracts.PREDICTIONS_SCHEMA_VERSION),
        ("NormalisationSha256", contracts.NORMALISATION_SHA256),
        ("RoutePrefix", contracts.ROUTE_PREFIX),
    ]:
        assert f'{constant} = "{value}"' in source, constant
    for constant, value in [
        ("MaximumDetectionsPerCrop", contracts.MAXIMUM_DETECTIONS_PER_CROP),
        ("MaximumPlatesPerCrop", contracts.MAXIMUM_PLATES_PER_CROP),
        ("MaximumReadingsPerPlate", contracts.MAXIMUM_READINGS_PER_PLATE),
    ]:
        assert f"{constant} = {value};" in source, constant
    for code, retryable in contracts.FAILURE_CODE_RETRYABLE.items():
        assert f'["{code}"] = {"true" if retryable else "false"}' in source, code
