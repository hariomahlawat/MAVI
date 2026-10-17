"""The committed Issue #225 Development pilot release: plates-onnx-v1, the two unverified Model Packs, the plates role
binding and the Development-only plate profile.

Always run: Production refuses the profile; Development refuses missing or altered model bytes; the runtime graph and
statuses fail closed; the running environment is compared with the family; the registry declares the role binding.
Run where the local packs and runtime are present (``MAVI_PLATES_PILOT_MODEL_ROOT`` names a model root staged by
``tools/vision/plates_pilot_packs.py`` and the interpreter is the ``plates-onnx-v1`` environment): the real models
compose READY and execute through the real ``PlateRunner`` on a synthetic crop. Elsewhere that test is skipped with
the reason; it never passes vacuously.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from mavi_vision.plates.contracts import PlateLease
from mavi_vision.plates.runner import PlateRunner
from mavi_vision.plates.settings import PlateWorkerSettings
from mavi_vision.plates.supervisor import PlateRuntimeState, PlateSupervisor, check_development_environment, plate_composition
from mavi_vision.runtime.development_binding import (
    DEVELOPMENT_PRODUCERS_PATH,
    check_role_binding,
    load_development_producers,
    parse_development_producers,
)
from mavi_vision.runtime.binding import load_component_binding
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.runtime_profile_v2 import load_runtime_profile_v2, parse_runtime_profile_v2
from tests.component_binding_v2_fixtures import REPOSITORY

BINDING = REPOSITORY / "src/vision/config/components/development-plates-onnx-pilot-v1.json"
PROFILE = REPOSITORY / "src/vision/config/plates/development-plates-onnx-pilot-v1.json"
RUNTIME = REPOSITORY / "src/vision/runtime/plates-onnx-v1/runtime.json"
IDENTITY = "c86c930b038d4f933f66ec2ed2f0c886f2df18dc932f79ec2f703c5f882f066e"
MODEL_ROOT = os.environ.get("MAVI_PLATES_PILOT_MODEL_ROOT")


def _settings(model_root: Path, **overrides) -> PlateWorkerSettings:
    values = {"api_base_url": "http://127.0.0.1:5000", "worker_id": "plates-pilot-01", "component_binding_path": BINDING,
              "overlay_root": REPOSITORY, "model_root": model_root, "pipeline_profile_path": PROFILE,
              "deployment_profile_policy_path": REPOSITORY / "config/acceptance/phase1-deployment-profiles-v1.json"}
    values.update(overrides)
    return PlateWorkerSettings(**values)


def _start(settings: PlateWorkerSettings) -> PlateSupervisor:
    supervisor = PlateSupervisor(settings, plate_composition(settings))
    supervisor.start()
    return supervisor


# --------------------------------------------------------------------------- refusals (always)


def test_production_refuses_the_pilot_profile_before_any_model_is_read(tmp_path: Path) -> None:
    supervisor = _start(_settings(tmp_path, production_mode=True, deployment_profile="P1"))
    assert supervisor.state is PlateRuntimeState.UNAVAILABLE
    assert supervisor.unavailable_reason == "plate_development_profile_forbidden"


def test_development_refuses_absent_model_bytes(tmp_path: Path) -> None:
    supervisor = _start(_settings(tmp_path))
    assert supervisor.state is PlateRuntimeState.UNAVAILABLE
    assert supervisor.unavailable_reason.startswith("model_artifact_missing:")


def test_development_refuses_altered_model_bytes(tmp_path: Path) -> None:
    for manifest_name in ("plates-pd5-ppocrv5-mobile-det-dev-v1.json", "plates-oc1-fast-plate-ocr-cct-s-v2-dev-v1.json"):
        manifest = json.loads((REPOSITORY / "models/manifests" / manifest_name).read_text(encoding="utf-8"))
        for artifact in manifest["artifacts"]:
            target = tmp_path / artifact["relativePath"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"not the pinned bytes\n")
    supervisor = _start(_settings(tmp_path))
    assert supervisor.unavailable_reason.startswith("model_artifact_hash_mismatch:")


def test_the_family_is_development_only_and_a_qualified_status_is_refused() -> None:
    profile = load_runtime_profile_v2(RUNTIME)
    assert profile.graph.development_only and profile.qualification_status == "partial"
    raw = json.loads(RUNTIME.read_text(encoding="utf-8"))
    for mutate, code in [
        (lambda d: d["platformVariants"]["windows-x86_64-cpu"].update(status="qualified-hosted-cpu"),
         "runtime_platform_evidence_required"),
        (lambda d: d["releaseLocks"]["windows-x86_64-cpu"].update(status="qualified-offline-lock"),
         "runtime_development_graph_qualified_status_forbidden"),
        (lambda d: d.pop("runtimeGraph"), "runtime"),
        (lambda d: d.update(runtimeGraph="mmdetection-v1"), "runtime_graph_unknown"),
        (lambda d: d["semanticGraph"].update(torch="2.6.0"), "runtime"),
    ]:
        document = copy.deepcopy(raw)
        mutate(document)
        with pytest.raises(ReleaseMetadataError) as error:
            parse_runtime_profile_v2(document)
        assert error.value.code.startswith(code), (code, error.value.code)


def test_the_vision_family_can_never_take_a_development_status() -> None:
    raw = json.loads((REPOSITORY / "src/vision/runtime/mmdetection-phase1-v1/runtime.json").read_text(encoding="utf-8"))
    raw["platformVariants"]["windows-x86_64-cpu"] = {"status": "development-cpu",
                                                      "pythonIdentity": raw["platformVariants"]["windows-x86_64-cpu"]["pythonIdentity"]}
    raw["releaseLocks"]["windows-x86_64-cpu"]["status"] = "development-offline-lock"
    with pytest.raises(ReleaseMetadataError) as error:
        parse_runtime_profile_v2(raw)
    assert error.value.code == "runtime_development_status_requires_development_graph"


def test_the_running_environment_must_be_the_family_environment() -> None:
    from types import SimpleNamespace

    from mavi_vision.runtime.qualification import runtime_platform_variant_identities

    profile = load_runtime_profile_v2(RUNTIME)
    family = SimpleNamespace(runtime_profile=profile, runtime_platform_variants=runtime_platform_variant_identities(profile))
    selection = SimpleNamespace(resolved_role=SimpleNamespace(family=family, runtime_variant="windows-x86_64-cpu"))
    graph = profile.semantic_graph.model_dump(by_alias=True)
    installed = {"onnxruntime": graph["onnxruntime"], "numpy": graph["numpy"], "opencv-python-headless": graph["opencvPythonHeadless"],
                 "pillow": graph["pillow"], "scipy": graph["scipy"], "pyyaml": graph["pyyaml"]}
    check_development_environment(selection, python_version="3.12.10", installed=installed)
    with pytest.raises(ValueError, match="plate_runtime_python_mismatch"):
        check_development_environment(selection, python_version="3.13.14", installed=installed)
    with pytest.raises(ValueError, match="plate_runtime_environment_mismatch:onnxruntime"):
        check_development_environment(selection, python_version="3.12.10", installed={**installed, "onnxruntime": "1.30.0"})
    with pytest.raises(ValueError, match="plate_runtime_environment_mismatch:pyyaml"):
        check_development_environment(selection, python_version="3.12.10",
                                      installed={k: v for k, v in installed.items() if k != "pyyaml"})


def test_the_registry_declares_the_plates_role_binding_and_it_adds_only_its_role() -> None:
    producers = load_development_producers(REPOSITORY / DEVELOPMENT_PRODUCERS_PATH)
    (role_binding,) = producers.role_bindings
    assert role_binding.role_ids == frozenset({"plates"})
    release = load_component_binding(REPOSITORY / producers.release_binding_path)
    candidate = load_component_binding(REPOSITORY / role_binding.binding_path)
    check_role_binding(release=release, candidate=candidate, role_ids=role_binding.role_ids)
    with pytest.raises(ReleaseMetadataError, match="development_binding_id_invalid"):
        check_role_binding(release=release, candidate=release, role_ids=frozenset({"vision"}))
    raw = json.loads((REPOSITORY / DEVELOPMENT_PRODUCERS_PATH).read_text(encoding="utf-8"))
    raw["developmentRoleBindings"][0]["roleIds"] = ["vision"]
    with pytest.raises(ReleaseMetadataError, match="development_role_binding_role_unauthorised:vision"):
        parse_development_producers(raw)


# --------------------------------------------------------------------------- the real models (local packs only)


def _real_runtime_reason() -> str | None:
    if not MODEL_ROOT:
        return "MAVI_PLATES_PILOT_MODEL_ROOT is not set (the pilot packs are staged outside Git)"
    for module in ("onnxruntime", "cv2", "yaml"):
        try:
            __import__(module)
        except ImportError:
            return f"the plates-onnx-v1 runtime is absent ({module} not importable)"
    return None


def _plate_crop() -> bytes:
    image = Image.new("RGB", (480, 320), (70, 80, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((140, 200, 340, 250), fill=(245, 245, 245), outline=(0, 0, 0), width=2)
    try:
        font = ImageFont.load_default(size=36)
    except TypeError:  # pragma: no cover - Pillow without FreeType sizes
        font = ImageFont.load_default()
    draw.text((152, 205), "ABC1234", fill=(10, 10, 10), font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


@pytest.mark.skipif(_real_runtime_reason() is not None, reason=str(_real_runtime_reason()))
def test_the_real_models_compose_ready_and_run_through_the_real_runner() -> None:
    from tests.test_plate_role import FakeApi, _lease_document

    supervisor = _start(_settings(Path(MODEL_ROOT)))
    assert supervisor.state is PlateRuntimeState.READY, supervisor.unavailable_reason
    runtime = supervisor.runtime
    assert runtime.identity.fingerprint == IDENTITY
    assert {item["verificationStatus"] for item in runtime.provenance["capabilities"]} == {"unverified"}
    assert (runtime.provenance["runtimePackFamilyId"], runtime.provenance["actualDevice"]) == ("plates-onnx-v1", "cpu")

    crop = _plate_crop()
    document = _lease_document(observations=1)
    document["identity"]["fingerprint"] = runtime.identity.fingerprint
    observation = document["tracks"][0]["observations"][0]
    observation.update(sizeBytes=len(crop), sha256=hashlib.sha256(crop).hexdigest())
    api = FakeApi(PlateLease.model_validate_json(json.dumps(document)), evidence=lambda item: crop)
    runner = PlateRunner(api, worker_id="plates-pilot-01", parameters=runtime.profile.parameters, detector=runtime.detector,
                         recogniser=runtime.recogniser, provenance=runtime.provenance, heartbeat_interval_seconds=60.0,
                         request_timeout_seconds=1.0, completion_retry_seconds=0.0)
    try:
        outcome = asyncio.run(runner.run_once())
    finally:
        runner.close()
    assert outcome.status == "completed", outcome
    artefact = json.loads(api.uploaded)
    crop_record = artefact["tracks"][0]["crops"][0]
    assert crop_record["status"] == "scored"
    assert crop_record["detections"], "the real detector proposed no region on a crop with large printed text"
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((REPOSITORY / "contracts/schemas/plate-predictions-v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(artefact, schema)
