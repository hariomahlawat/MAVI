"""Composition of the zero-shot ``attributes`` role (PoC S5; ADR-021 amendment 2026-10-29).

Like the ``embeddings`` role (ADR-021 §3), the zero-shot role is Development-only and composed from explicit,
SHA-pinned inputs instead of the Component Binding resolver: it runs from the ``embeddings-onnx-v1`` runtime (a
locked virtual environment, not a Runtime Pack) over the S4 SigLIP 2 Model Pack, so the resolver's Runtime Pack,
qualification-record and gate-set path has nothing true to resolve. What it does check, fail-closed:

* production mode is refused;
* the pipeline profile is ``developmentOnly`` and names ``siglip2-zero-shot-v1``;
* the model manifest is the file, with the SHA-256, that the parameters (an identity input) name;
* the binding's ``attributes`` role is the one the platform reads (``VisualAttributeReleaseParser``): it runs from
  ``embeddings-onnx-v1``, and every attribute capability binding is enabled and names this manifest's derived
  ``modelPackId`` and the Development record beside the profile;
* every Model Pack artefact is hash-verified before ONNX Runtime sees a byte.

The provenance is truthful: an ``unpacked-environment`` runtime, ``unverified`` capabilities and the Development
record (``status: development-unqualified``) in place of a qualification record.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from mavi_vision.attributes.inference import AttributeInferencer
from mavi_vision.attributes.pipeline import AttributeIdentity, AttributePipelineProfile, attribute_identity, load_attribute_pipeline
from mavi_vision.attributes.settings import AttributeWorkerSettings
from mavi_vision.attributes.zero_shot import SiglipZeroShotInferencer, is_zero_shot, parse_zero_shot_parameters
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.model_manifest_v2 import ModelManifestV2, parse_model_manifest_v2

_LOGGER = logging.getLogger(__name__)

ROLE_ID = "attributes"
ENTRY_POINT = "mavi_vision.attributes.main"
PROVENANCE_CONTRACT = "visual-attribute-complete-v1"
RUNTIME_FAMILY_ID = "embeddings-onnx-v1"
BINDING_SCHEMA = "mavi-vision-component-binding-v2"
RECORD_SCHEMA = "mavi-poc-development-record-v1"
ATTRIBUTE_CAPABILITY_IDS = frozenset({"person-attributes", "vehicle-attributes"})
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class ZeroShotRuntime:
    """What ``main.run_worker`` needs: the same members as ``AttributeRuntime``."""

    identity: AttributeIdentity
    profile: AttributePipelineProfile
    inferencer: AttributeInferencer
    provenance: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ZeroShotBinding:
    sha256: str
    model_pack_ids: Mapping[str, str]
    qualification_id: str


def _read(path: Path, code: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(code) from exc


def _json(payload: bytes, code: str) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(code) from exc


def read_zero_shot_binding(path: Path) -> ZeroShotBinding:
    """The attribute role and its capability bindings, read as the platform reads them, plus the runtime family."""
    code = "attribute_zero_shot_binding_invalid"
    payload = _read(path, code)
    document = _json(payload, code)
    if not isinstance(document, dict) or document.get("schemaVersion") != BINDING_SCHEMA:
        raise ValueError(code)
    roles = [item for item in document.get("roles", []) if isinstance(item, dict)
             and any(cap in ATTRIBUTE_CAPABILITY_IDS for cap in item.get("capabilityIds", []))]
    if len(roles) != 1:
        raise ValueError(f"{code}:role")
    role = roles[0]
    if (role.get("roleId") != ROLE_ID or role.get("entryPoint") != ENTRY_POINT
            or role.get("provenanceContract") != PROVENANCE_CONTRACT
            or role.get("runtimePackFamilyId") != RUNTIME_FAMILY_ID
            or sorted(role.get("capabilityIds", [])) != sorted(ATTRIBUTE_CAPABILITY_IDS)):
        raise ValueError(f"{code}:role")
    packs: dict[str, str] = {}
    qualification_ids: set[str] = set()
    for item in document.get("capabilityBindings", []):
        if not isinstance(item, dict) or item.get("roleId") != ROLE_ID:
            continue
        capability_id = item.get("capabilityId")
        if capability_id not in ATTRIBUTE_CAPABILITY_IDS or capability_id in packs or item.get("enabled") is not True:
            raise ValueError(f"{code}:capabilityBindings")
        qualification_id = item.get("qualificationId")
        if not isinstance(qualification_id, str) or _TOKEN_RE.fullmatch(qualification_id) is None:
            raise ValueError(f"{code}:qualificationId")
        packs[capability_id] = str(item.get("modelPackId"))
        qualification_ids.add(qualification_id)
    if set(packs) != ATTRIBUTE_CAPABILITY_IDS or len(qualification_ids) != 1:
        raise ValueError(f"{code}:capabilityBindings")
    return ZeroShotBinding(hashlib.sha256(payload).hexdigest(), packs, qualification_ids.pop())


def read_development_record(directory: Path, record_id: str) -> str:
    """The Development record beside the profile, ``<recordId>.json``; returns its SHA-256."""
    code = "attribute_zero_shot_record_invalid"
    payload = _read(directory / f"{record_id}.json", code)
    document = _json(payload, code)
    if (not isinstance(document, dict) or document.get("schemaVersion") != RECORD_SCHEMA
            or document.get("recordId") != record_id or document.get("status") != "development-unqualified"):
        raise ValueError(code)
    return hashlib.sha256(payload).hexdigest()


def load_manifest(path: Path, expected_name: str, expected_sha256: str) -> tuple[ModelManifestV2, str]:
    if path.name != expected_name:
        raise ValueError("attribute_zero_shot_manifest_mismatch")
    payload = _read(path, "attribute_zero_shot_manifest_unreadable")
    sha256 = hashlib.sha256(payload).hexdigest()
    if sha256 != expected_sha256:
        raise ValueError("attribute_zero_shot_manifest_sha256_mismatch")
    try:
        manifest = parse_model_manifest_v2(_json(payload, "attribute_zero_shot_manifest_invalid"))
    except ReleaseMetadataError as exc:
        raise ValueError(f"attribute_zero_shot_manifest_invalid:{exc.code}") from exc
    if RUNTIME_FAMILY_ID not in manifest.runtime_pack_family_ids:
        raise ValueError("attribute_zero_shot_manifest_runtime_incompatible")
    return manifest, sha256


ModelLoader = Callable[[ModelManifestV2, AttributeWorkerSettings], tuple[object, str, str]]


def onnx_model_loader(manifest: ModelManifestV2, settings: AttributeWorkerSettings) -> tuple[object, str, str]:
    """Verify every artefact, then open the two ONNX towers; returns (model, runtime variant, actual device)."""
    # Imported here: onnxruntime and sentencepiece exist only in the embeddings-onnx-v1 environment.
    from mavi_vision.embeddings.identity import verify_model_pack
    from mavi_vision.embeddings.onnx_model import load_onnx_model, runtime_variant

    dimension = manifest.capability_specific.get("embedding", {}).get("dimension")
    if not isinstance(dimension, int):
        raise ValueError("attribute_zero_shot_manifest_dimension_invalid")
    artifacts = verify_model_pack(manifest, settings.model_root)
    model = load_onnx_model(artifacts, dimension=dimension, device_policy=settings.device_policy,
                            device_index=settings.device_index, cuda_dll_directory=settings.cuda_dll_directory)
    return model, runtime_variant(model.resolution), model.resolution.actual_device


def compose_zero_shot(settings: AttributeWorkerSettings, *, model_loader: ModelLoader = onnx_model_loader) -> ZeroShotRuntime:
    if settings.production_mode:
        raise ValueError("attribute_zero_shot_development_only")
    if settings.attribute_model_manifest_path is None:
        raise ValueError("attribute_zero_shot_manifest_required")
    profile = load_attribute_pipeline(settings.pipeline_profile_path)
    if not profile.development_only or not is_zero_shot(profile.parameters):
        raise ValueError("attribute_zero_shot_profile_invalid")
    parameters = parse_zero_shot_parameters(profile.parameters, profile.schema)
    manifest, manifest_sha256 = load_manifest(
        settings.attribute_model_manifest_path, parameters.model_manifest_file, parameters.model_manifest_sha256)
    binding = read_zero_shot_binding(settings.component_binding_path)
    if any(pack != manifest.model_pack_id for pack in binding.model_pack_ids.values()):
        raise ValueError("attribute_zero_shot_model_pack_mismatch")
    record_sha256 = read_development_record(profile.path.parent, binding.qualification_id)
    runtime_profile_sha256 = hashlib.sha256(_read(settings.attribute_runtime_profile_path, "attribute_runtime_profile_unreadable")).hexdigest()
    identity = attribute_identity(profile, dict(binding.model_pack_ids))
    model, variant, device = model_loader(manifest, settings)
    inferencer = SiglipZeroShotInferencer(model, parameters)  # type: ignore[arg-type]
    provenance = {
        "provenanceContract": PROVENANCE_CONTRACT,
        "roleId": ROLE_ID,
        "capabilities": [
            {
                "capabilityId": item.capability_id,
                "modelPackId": item.model_pack_id,
                "modelManifestSha256": manifest_sha256,
                "qualificationId": binding.qualification_id,
                "qualificationSha256": record_sha256,
                "verificationStatus": "unverified",
            }
            for item in identity.capabilities
        ],
        "runtimePackFamilyId": RUNTIME_FAMILY_ID,
        "runtimeProfileSha256": runtime_profile_sha256,
        "runtimeVariant": variant,
        "runtimePackId": None,
        "runtimePackSource": "unpacked-environment",
        "componentBindingSha256": binding.sha256,
        "pipelineProfileSha256": profile.sha256,
        "configuredDevicePolicy": settings.device_policy,
        "actualDevice": device,
        "maviBuild": settings.build_id,
        "maviCommit": settings.commit_sha,
    }
    _LOGGER.info("MAVI attributes runtime READY (zero-shot, Development): identity %s on %s", identity.fingerprint, device)
    return ZeroShotRuntime(identity, profile, inferencer, provenance)


__all__ = [
    "ZeroShotBinding",
    "ZeroShotRuntime",
    "compose_zero_shot",
    "load_manifest",
    "onnx_model_loader",
    "read_development_record",
    "read_zero_shot_binding",
]
