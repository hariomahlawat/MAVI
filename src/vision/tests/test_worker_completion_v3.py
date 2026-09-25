"""W family: the worker client's completion 3.0 wire and capability probe.

The worker is the only producer of completion 3.0; these tests pin it to the
checked-in golden example and JSON Schema so the Python and .NET boundaries
cannot drift, and prove that a rejection is never answered with a 2.0 body.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import jsonschema
import pytest
from pydantic import ValidationError

from mavi_vision.common.analytical import (
    ArtifactDescriptor,
    EvidenceAccounting,
    NormalizedBoundingBox,
    ObjectClass,
    ObservationDescriptor,
    ProcessedTrack,
    RoleAccounting,
    VisionProcessingResult,
)
from mavi_vision.common.control_plane import VisionJobCompleteV3, VisionJobLease
from mavi_vision.common.settings import WorkerSettings
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole, role_cap_bytes
from mavi_vision.runtime.provenance import (
    PlatformIdentity,
    RuntimeProvenance,
    TrackerParameters,
)
from mavi_vision.worker.client import (
    CompletionPayloadInvalid,
    PlatformContractUnsupported,
    WorkerApiClient,
    WorkerApiError,
)


ROOT = Path(__file__).resolve().parents[3]
# Since S1.4 F2 the worker emits completion 3.1: the 3.0 body under the
# asynchronous exchange version (the 3.1 example and schema are the 3.0 ones
# with only the version changed, which tools/verify_repo.py enforces).
GOLDEN = ROOT / "contracts/examples/vision-job-complete-v3.1.example.json"
SCHEMA = ROOT / "contracts/schemas/vision-job-complete-v3.1.schema.json"
LEASE_EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"
# The platform's completion body cap is 48 MiB; plan §7 keeps the worst-shape
# 3.x body under 40 MiB so the envelope has headroom.
WORST_SHAPE_BODY_BUDGET = 40 * 1024 * 1024


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _settings(tmp_path: Path, worker_id: str = "gpu-sdd-01") -> WorkerSettings:
    return WorkerSettings(
        api_base_url="https://mavi-api.local",
        worker_id=worker_id,
        media_root=tmp_path,
    )


def _lease_for(golden: dict) -> VisionJobLease:
    payload = json.loads(LEASE_EXAMPLE.read_text(encoding="utf-8"))
    payload["jobId"] = golden["jobId"]
    payload["workerId"] = golden["workerId"]
    payload["leaseToken"] = golden["leaseToken"]
    payload["attemptCount"] = golden["attemptCount"]
    return VisionJobLease.model_validate_json(json.dumps(payload))


def _provenance_from(wire: dict) -> RuntimeProvenance:
    platform = wire["platform"]
    tracker = wire["trackerParameters"]
    assert wire["gpu"] is None
    return RuntimeProvenance(
        model_id=wire["modelId"],
        model_version=wire["modelVersion"],
        model_manifest_sha256=wire["modelManifestSha256"],
        checkpoint_sha256=wire["checkpointSha256"],
        resolved_config_sha256=wire["resolvedConfigSha256"],
        pipeline_profile_id=wire["pipelineProfileId"],
        pipeline_profile_version=wire["pipelineProfileVersion"],
        pipeline_profile_sha256=wire["pipelineProfileSha256"],
        qualification_id=wire["qualificationId"],
        qualification_sha256=wire["qualificationSha256"],
        verification_status=wire["verificationStatus"],
        runtime_profile_id=wire["runtimeProfileId"],
        runtime_profile_sha256=wire["runtimeProfileSha256"],
        runtime_variant=wire["runtimeVariant"],
        platform_lock_sha256=wire["platformLockSha256"],
        detector_backend=wire["detectorBackend"],
        dependency_versions=dict(wire["dependencyVersions"]),
        ffmpeg_version=wire["ffmpegVersion"],
        platform=PlatformIdentity(
            system=platform["system"],
            release=platform["release"],
            version=platform["version"],
            machine=platform["machine"],
            processor=platform["processor"],
            python_version=platform["pythonVersion"],
            python_implementation=platform["pythonImplementation"],
            python_build=tuple(platform["pythonBuild"]),
            python_compiler=platform["pythonCompiler"],
        ),
        configured_device_policy=wire["configuredDevicePolicy"],
        configured_device_index=wire["configuredDeviceIndex"],
        device_resolution_reason=wire["deviceResolutionReason"],
        actual_device=wire["actualDevice"],
        gpu=None,
        mavi_build=wire["maviBuild"],
        mavi_commit=wire["maviCommit"],
        frame_policy=wire["framePolicy"],
        tracker_parameters=TrackerParameters(
            reference_frame_rate=tracker["referenceFrameRate"],
            track_activation_threshold=tracker["trackActivationThreshold"],
            high_confidence_threshold=tracker["highConfidenceThreshold"],
            minimum_iou_threshold=tracker["minimumIouThreshold"],
            minimum_consecutive_frames=tracker["minimumConsecutiveFrames"],
            lost_track_buffer_seconds=tracker["lostTrackBufferSeconds"],
        ),
    )


def _micro(score: float) -> int:
    micro = round(score * 1_000_000)
    assert micro / 1_000_000 == score
    return micro


def _artifact(wire: dict) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        storage_key=wire["storageKey"],
        media_type=wire["mediaType"],
        size_bytes=wire["sizeBytes"],
        sha256=wire["sha256"],
    )


def _track_from(wire: dict) -> ProcessedTrack:
    return ProcessedTrack(
        track_id=wire["trackId"],
        object_class=ObjectClass(wire["objectClass"]),
        start_offset_ms=wire["startOffsetMs"],
        end_offset_ms=wire["endOffsetMs"],
        detection_count=wire["detectionCount"],
        mean_confidence=wire["meanConfidence"],
        max_confidence=wire["maxConfidence"],
        observations=tuple(
            ObservationDescriptor(
                role=EvidenceRole(item["role"]),
                rank=item["rank"],
                offset_ms=item["offsetMs"],
                source_frame_number=item["sourceFrameNumber"],
                confidence=item["confidence"],
                bounding_box=NormalizedBoundingBox(**item["boundingBox"]),
                quality_micro=_micro(item["qualityScore"]),
                selection_micro=_micro(item["selectionScore"]),
                crop=_artifact(item["crop"]),
            )
            for item in wire["observations"]
        ),
        trajectory_artifact=_artifact(wire["trajectoryArtifact"]),
    )


def _accounting_from(wire: dict) -> EvidenceAccounting:
    return EvidenceAccounting.of(
        {
            role: RoleAccounting(
                candidates=wire[role.value]["candidates"],
                admitted=wire[role.value]["admitted"],
                omitted=wire[role.value]["omitted"],
                candidate_bytes=wire[role.value]["candidateBytes"],
                admitted_bytes=wire[role.value]["admittedBytes"],
            )
            for role in ROLE_ORDER
        }
    )


def _response_for(body: dict, version: str = "3.1", state: str = "finalizing") -> httpx.Response:
    """A completion acknowledgement: the 3.1 hand-off by default, or a
    synchronous-style (2.0/3.0) echo for the version-skew tests."""
    if version != "3.1":
        return httpx.Response(
            200,
            json={
                "schemaVersion": version,
                "jobId": body["jobId"],
                "processingRunId": "018fa7b6-2b31-7f42-9f33-9fd9f6fdd762",
                "tracksAccepted": len(body["tracks"]),
                "completedAtUtc": "2026-09-24T00:00:00Z",
            },
        )
    payload = {
        "schemaVersion": "3.1",
        "jobId": body["jobId"],
        "processingRunId": "018fa7b6-2b31-7f42-9f33-9fd9f6fdd762",
        "state": state,
        "acceptedAtUtc": "2026-09-24T00:00:00Z",
        "tracksSubmitted": len(body["tracks"]),
    }
    if state == "completed":
        payload["completedAtUtc"] = "2026-09-24T00:01:30Z"
    return httpx.Response(200, json=payload)


def _run(tmp_path: Path, handler, action, *, worker_id: str = "gpu-sdd-01"):
    async def invoke():
        client = WorkerApiClient(
            _settings(tmp_path, worker_id), httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        try:
            return await action(client)
        finally:
            await client.aclose()

    return asyncio.run(invoke())


def _complete_golden(tmp_path: Path, handler):
    golden = _golden()
    result = VisionProcessingResult(
        job_id=_lease_for(golden).job_id,
        frames_processed=golden["framesProcessed"],
        tracks=tuple(_track_from(track) for track in golden["tracks"]),
        evidence_accounting=_accounting_from(golden["evidenceAccounting"]),
    )
    return _run(
        tmp_path,
        handler,
        lambda client: client.complete(
            _lease_for(golden),
            result,
            golden["processingDurationMs"],
            _provenance_from(golden["provenance"]),
        ),
        worker_id=golden["workerId"],
    )


# Capability probe -------------------------------------------------------------


def _capabilities(payload: object, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/vision/contract"
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    return handler


def test_capability_probe_accepts_a_platform_listing_completion_3_1(tmp_path: Path) -> None:
    capabilities = _run(
        tmp_path,
        _capabilities(
            {"schemaVersion": "2.0", "completionSchemaVersions": ["2.0", "3.1"], "future": 1}
        ),
        lambda client: client.get_contract_capabilities(),
    )
    assert capabilities.completion_schema_versions == ("2.0", "3.1")


def test_a_platform_listing_only_completion_3_0_is_unsupported(tmp_path: Path) -> None:
    """Version skew, new worker against a pre-F2 platform: the worker never
    submits 3.0, so a platform that lists 3.0 but not 3.1 keeps it not-ready."""
    with pytest.raises(PlatformContractUnsupported):
        _run(
            tmp_path,
            _capabilities({"schemaVersion": "2.0", "completionSchemaVersions": ["2.0", "3.0"]}),
            lambda client: client.get_contract_capabilities(),
        )


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"schemaVersion": "2.0", "completionSchemaVersions": ["2.0"]}, 200),
        ({"schemaVersion": "2.0", "completionSchemaVersions": []}, 200),
        ({"schemaVersion": "2.0", "completionSchemaVersions": "3.0"}, 200),
        ({"schemaVersion": "2.0", "completionSchemaVersions": [3.0]}, 200),
        ({"schemaVersion": "3.0", "completionSchemaVersions": ["3.0"]}, 200),
        ({"completionSchemaVersions": ["3.0"]}, 200),
        (b"not json", 200),
        ({"code": "not_found"}, 404),
        ({"code": "method_not_allowed"}, 405),
    ],
    ids=[
        "no-3.0",
        "empty",
        "not-an-array",
        "non-string",
        "control-plane-not-2.0",
        "missing-control-plane-version",
        "malformed",
        "predates-probe-404",
        "predates-probe-405",
    ],
)
def test_incompatible_or_malformed_capabilities_are_unsupported(
    tmp_path: Path, payload: object, status: int
) -> None:
    with pytest.raises(PlatformContractUnsupported):
        _run(tmp_path, _capabilities(payload, status), lambda client: client.get_contract_capabilities())


def test_capability_probe_server_error_is_an_ordinary_api_error(tmp_path: Path) -> None:
    with pytest.raises(WorkerApiError) as raised:
        _run(tmp_path, _capabilities({"code": "x"}, 503), lambda client: client.get_contract_capabilities())
    assert not isinstance(raised.value, PlatformContractUnsupported)
    assert raised.value.status_code == 503


def test_capability_probe_transport_error_is_an_ordinary_api_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(WorkerApiError) as raised:
        _run(tmp_path, handler, lambda client: client.get_contract_capabilities())
    assert not isinstance(raised.value, PlatformContractUnsupported)


# Completion 3.0 ---------------------------------------------------------------


def test_worker_body_is_byte_equivalent_to_the_golden_example(tmp_path: Path) -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return _response_for(body)

    _complete_golden(tmp_path, handler)

    assert captured == [_golden()]
    body = captured[0]
    assert body["schemaVersion"] == "3.1"
    assert all("representative" not in track for track in body["tracks"])
    # The golden's accounting is the worker's exact input, so it must survive
    # untouched, including omitted candidates that have no observation.
    assert body["evidenceAccounting"]["near-view"]["omitted"] == 1


def test_worker_body_validates_against_the_v3_json_schema(tmp_path: Path) -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return _response_for(body)

    _complete_golden(tmp_path, handler)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        captured[0]
    )
    VisionJobCompleteV3.model_validate_json(json.dumps(captured[0]))


def test_contract_rejection_raises_unsupported_and_sends_nothing_else(tmp_path: Path) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            400,
            json={"code": "worker_contract_version_unsupported", "title": "unsupported"},
        )

    with pytest.raises(PlatformContractUnsupported) as raised:
        _complete_golden(tmp_path, handler)

    assert raised.value.status_code == 400
    assert raised.value.code == "worker_contract_version_unsupported"
    # Exactly one request, and it was 3.1: no retry and no 3.0 or 2.0 fallback.
    assert [body["schemaVersion"] for body in requests] == ["3.1"]


def test_an_invalid_local_body_is_refused_before_anything_is_sent(tmp_path: Path, monkeypatch) -> None:
    requests: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.content)
        return _response_for(json.loads(request.content))

    # A crop key that is not this attempt's: the platform would refuse it.
    import mavi_vision.worker.client as client_module

    real = client_module.WorkerApiClient._map_observation

    def wrong_key(observation):
        mapped = real(observation)
        return mapped.model_copy(
            update={"crop": mapped.crop.model_copy(update={"storage_key": "staging/other/attempt-0001/evidence/x.jpg"})}
        )

    monkeypatch.setattr(client_module.WorkerApiClient, "_map_observation", staticmethod(wrong_key))
    with pytest.raises(CompletionPayloadInvalid):
        _complete_golden(tmp_path, handler)
    assert requests == []


def test_other_bad_requests_are_not_contract_rejections(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "completion_invalid"})

    with pytest.raises(WorkerApiError) as raised:
        _complete_golden(tmp_path, handler)
    assert not isinstance(raised.value, PlatformContractUnsupported)
    assert raised.value.code == "completion_invalid"


@pytest.mark.parametrize("version", ["2.0", "3.0"])
def test_a_synchronous_completion_echo_is_rejected(tmp_path: Path, version: str) -> None:
    """A 2.0/3.0-style completion response is not a hand-off acknowledgement."""
    def handler(request: httpx.Request) -> httpx.Response:
        return _response_for(json.loads(request.content), version=version)

    with pytest.raises(WorkerApiError, match="unexpected version"):
        _complete_golden(tmp_path, handler)


def test_a_finalizing_acknowledgement_is_the_hand_off(tmp_path: Path) -> None:
    acknowledged = _complete_golden(tmp_path, lambda request: _response_for(json.loads(request.content)))

    assert acknowledged.state == "finalizing"
    assert acknowledged.tracks_submitted == len(_golden()["tracks"])
    assert acknowledged.completed_at_utc is None
    assert str(acknowledged.job_id) == _golden()["jobId"]


def test_a_completed_acknowledgement_is_an_idempotent_replay(tmp_path: Path) -> None:
    acknowledged = _complete_golden(
        tmp_path, lambda request: _response_for(json.loads(request.content), state="completed")
    )

    assert acknowledged.state == "completed"
    assert acknowledged.completed_at_utc is not None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(completedAtUtc="2026-09-24T00:01:30Z"),  # finalizing with a completion time
        lambda payload: payload.update(state="completed"),  # completed without one
        lambda payload: payload.update(tracksAccepted=payload.pop("tracksSubmitted")),  # the retired name
        lambda payload: payload.update(state="published"),
        lambda payload: payload.update(jobId="018fa7b6-2b31-7f42-9f33-9fd9f6fdd7ff"),  # another job
    ],
)
def test_a_malformed_or_foreign_acknowledgement_is_refused(tmp_path: Path, mutate) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _response_for(json.loads(request.content)).json()
        mutate(payload)
        return httpx.Response(200, json=payload)

    with pytest.raises(WorkerApiError):
        _complete_golden(tmp_path, handler)


def test_worst_shape_body_stays_within_the_budget(tmp_path: Path) -> None:
    """10 000 Tracks (the contract maximum), each with all four roles at their
    byte caps and 17-significant-digit floats: the largest body the worker can
    emit. It must stay under the budget, and the platform model must accept it."""
    golden = _golden()
    job = golden["jobId"]
    prefix = f"staging/{job}/attempt-0001"
    confidence = 0.12345678901234567
    box = NormalizedBoundingBox(0.12345678901234567, 0.12345678901234567, 0.12345678901234567, 0.12345678901234567)
    tracks = []
    for index in range(1, 10_001):
        track_id = f"vehicle-{index:06d}"
        tracks.append(
            ProcessedTrack(
                track_id=track_id,
                object_class=ObjectClass.VEHICLE,
                start_offset_ms=0,
                end_offset_ms=86_400_000,
                detection_count=2_147_483_647,
                mean_confidence=confidence,
                max_confidence=confidence,
                observations=tuple(
                    ObservationDescriptor(
                        role=role,
                        rank=rank,
                        offset_ms=86_399_999 - rank,
                        source_frame_number=2_147_483_000 + rank,
                        confidence=confidence,
                        bounding_box=box,
                        quality_micro=123_457,
                        selection_micro=123_457,
                        crop=ArtifactDescriptor(
                            storage_key=f"{prefix}/evidence/{track_id}-{role.value}.jpg",
                            media_type="image/jpeg",
                            # Five-digit sizes: the Representative at its cap, and
                            # supplementals as large as the 1 GiB quota allows.
                            size_bytes=(
                                role_cap_bytes(role)
                                if role is EvidenceRole.REPRESENTATIVE
                                else 12_000
                            ),
                            sha256="f" * 64,
                        ),
                    )
                    for rank, role in enumerate(ROLE_ORDER)
                ),
                trajectory_artifact=ArtifactDescriptor(
                    storage_key=f"{prefix}/trajectories/{track_id}.msgpack",
                    media_type="application/msgpack",
                    size_bytes=50_000,
                    sha256="f" * 64,
                ),
            )
        )
    by_role = {}
    for role in ROLE_ORDER:
        sizes = [o.crop.size_bytes for t in tracks for o in t.observations if o.role is role]
        by_role[role] = RoleAccounting(len(sizes), len(sizes), 0, sum(sizes), sum(sizes))
    result = VisionProcessingResult(
        job_id=_lease_for(golden).job_id,
        frames_processed=2_147_483_647,
        tracks=tuple(tracks),
        evidence_accounting=EvidenceAccounting.of(by_role),
    )
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(request.content))
        VisionJobCompleteV3.model_validate_json(request.content)
        return _response_for(json.loads(request.content))

    _run(
        tmp_path,
        handler,
        lambda client: client.complete(
            _lease_for(golden), result, 2_147_483_647, _provenance_from(golden["provenance"])
        ),
        worker_id=golden["workerId"],
    )
    assert len(sizes) == 1
    assert sizes[0] <= WORST_SHAPE_BODY_BUDGET, sizes[0]


@pytest.mark.parametrize("tight", [False, True], ids=["all-admitted", "supplementals-omitted"])
def test_pipeline_generated_body_validates_against_schema_and_model(tmp_path: Path, tight: bool) -> None:
    """End to end on the worker side: a real VideoProcessor result (real JPEG
    crops, real admission) becomes a body the v3 schema and model accept."""
    from test_evidence_pipeline import JOB_ID, Walker, _run as run_pipeline

    walkers = {"person-a": range(0, 120), "person-b": range(10, 90)}
    options = {}
    if tight:
        full = run_pipeline(tmp_path / "probe", Walker(walkers, grow=0.01, grow_after=40), 120)
        options["evidence_quota_bytes"] = sum(t.observations[0].crop.size_bytes for t in full.tracks)
    result = run_pipeline(tmp_path / "run", Walker(walkers, grow=0.01, grow_after=40), 120, **options)

    golden = _golden()
    golden["jobId"] = str(JOB_ID)
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return _response_for(body)

    _run(
        tmp_path,
        handler,
        lambda client: client.complete(
            _lease_for(golden), result, 1, _provenance_from(golden["provenance"])
        ),
        worker_id=golden["workerId"],
    )

    (body,) = captured
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(body)
    VisionJobCompleteV3.model_validate_json(json.dumps(body))
    assert [track["trackId"] for track in body["tracks"]] == sorted(t["trackId"] for t in body["tracks"])
    for track in body["tracks"]:
        roles = [o["role"] for o in track["observations"]]
        assert roles[0] == "representative"
        assert [o["rank"] for o in track["observations"]] == list(range(len(roles)))
    accounting = body["evidenceAccounting"]
    for role in ROLE_ORDER:
        present = [o for t in body["tracks"] for o in t["observations"] if o["role"] == role.value]
        assert accounting[role.value]["admitted"] == len(present)
        assert accounting[role.value]["admittedBytes"] == sum(o["crop"]["sizeBytes"] for o in present)
        assert accounting[role.value]["omitted"] == (
            accounting[role.value]["candidates"] - accounting[role.value]["admitted"]
        )
    omitted = sum(accounting[role.value]["omitted"] for role in ROLE_ORDER)
    assert (omitted > 0) is tight
    assert accounting["representative"]["omitted"] == 0


# Cross-language alignment (W1) ------------------------------------------------

VECTORS = ROOT / "contracts/test-vectors"


@pytest.mark.parametrize(
    "vector",
    json.loads((VECTORS / "control-plane-v3-invalid.json").read_text(encoding="utf-8")),
    ids=lambda vector: vector["name"],
)
def test_python_v3_model_rejects_every_shared_invalid_vector(vector: dict) -> None:
    """The .NET schema and validator reject each of these; so must the worker's
    own model, including the cross-field rules the JSON Schema cannot express,
    so the worker can never build a body the platform refuses."""
    with pytest.raises(ValueError):
        VisionJobCompleteV3.model_validate_json(json.dumps(vector["payload"]))


def test_python_v3_model_follows_the_shared_integer_conformance_corpus() -> None:
    placeholder = "__MAVI_V3_NUMBER__"
    for vector in json.loads((VECTORS / "vision-job-complete-v3-conformance.json").read_text(encoding="utf-8"))[
        "integerCases"
    ]:
        payload = _golden()
        parent: object = payload
        parts = vector["path"].strip("/").split("/")
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        if isinstance(parent, list):
            parent[int(parts[-1])] = placeholder
        else:
            parent[parts[-1]] = placeholder
        raw = json.dumps(payload).replace(f'"{placeholder}"', vector["token"])
        # The corpus pins *binding* (type and range of the one number). The model
        # also runs the cross-field rules in the same step, so an accepted token
        # may still break one of those (e.g. candidates no longer equal admitted
        # + omitted). Binding is judged by errors located at the vector's path.
        try:
            VisionJobCompleteV3.model_validate_json(raw)
            located: list[dict] = []
        except ValidationError as exc:
            # A non-integral integer token is refused before field binding by the
            # model's integer wire-tree check, which reports at the root; only
            # one number differs from the golden example, so it is this one.
            located = [
                e
                for e in exc.errors()
                if tuple(str(part) for part in e["loc"]) == tuple(parts)
                or (e["loc"] == () and "completion integer" in e["msg"])
            ]
        assert (not located) is vector["accepted"], (vector["name"], located)
