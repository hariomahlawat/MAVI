"""The plate pipeline profile and the analysis identity it defines (ADR-013 implementation amendment
2026-10-13, item 11).

The profile ``mavi-plate-pipeline-v1`` is release text beside the Component Binding. It names the frozen
normalisation by id and SHA-256 and pins, by SHA-256 of the exact file bytes, the summary policy and the
identity-bearing parameters. The platform's ``PlateReleaseParser`` reads the same files and derives the
same identity with the same canonical encoding; ``contracts/test-vectors/plate-identity-v1.json`` holds
both to it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from mavi_vision.plates.contracts import (
    CAPABILITIES,
    IDENTITY_SCHEMA_VERSION,
    NORMALISATION_ID,
    NORMALISATION_SHA256,
    PREDICTIONS_SCHEMA_VERSION,
)
from mavi_vision.plates.parameters import ParametersInvalid, PlateParameters, load_parameters
from mavi_vision.plates.pipeline import SUMMARY_POLICY_METHOD
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.schema_common import read_release_json_v2

PIPELINE_SCHEMA = "mavi-plate-pipeline-v1"
SUMMARY_POLICY_SCHEMA = "mavi-plate-summary-policy-v1"
MAXIMUM_TOKEN_LENGTH = 64

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.json$")
_MODEL_PACK_ID_RE = re.compile(r"^mavi-model-v2-[0-9a-f]{64}$")


def _fail(code: str) -> ReleaseMetadataError:
    return ReleaseMetadataError(code)


def _token(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) > MAXIMUM_TOKEN_LENGTH or _TOKEN_RE.fullmatch(value) is None:
        raise _fail(code)
    return value


def _version(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) > MAXIMUM_TOKEN_LENGTH or _VERSION_RE.fullmatch(value) is None:
        raise _fail(code)
    return value


def _exact_keys(document: object, keys: set[str], code: str) -> None:
    if not isinstance(document, dict) or set(document) != keys:
        raise _fail(code)


@dataclass(frozen=True, slots=True)
class SummaryPolicy:
    policy_id: str
    version: str
    sha256: str
    method: str


@dataclass(frozen=True, slots=True)
class PlatePipelineProfile:
    path: Path
    sha256: str
    pipeline_id: str
    pipeline_version: str
    development_only: bool
    summary_policy: SummaryPolicy
    parameters: PlateParameters
    parameters_sha256: str


@dataclass(frozen=True, slots=True)
class PlateCapabilityIdentity:
    capability_id: str
    model_pack_id: str


@dataclass(frozen=True, slots=True)
class PlateIdentity:
    fingerprint: str
    canonical: str
    pipeline_id: str
    pipeline_version: str
    summary_policy: SummaryPolicy
    capabilities: tuple[PlateCapabilityIdentity, ...]
    parameters_sha256: str


def _pinned_sibling(profile_path: Path, reference: object, code: str) -> tuple[dict, bytes, str]:
    _exact_keys(reference, {"file", "sha256"}, code)
    assert isinstance(reference, dict)
    name, sha256 = reference["file"], reference["sha256"]
    if not isinstance(name, str) or _FILE_NAME_RE.fullmatch(name) is None or ".." in name:
        raise _fail(code)
    if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
        raise _fail(code)
    document, payload = read_release_json_v2(profile_path.parent / name, code=code)
    if hashlib.sha256(payload).hexdigest() != sha256:
        raise _fail(f"{code}:sha256_mismatch")
    return document, payload, sha256


def load_plate_pipeline(path: Path) -> PlatePipelineProfile:
    """Load and pin the profile and its two sibling documents, or fail closed."""
    code = "plate_pipeline_invalid"
    document, payload = read_release_json_v2(path, code=code)
    _exact_keys(
        document,
        {"schemaVersion", "pipelineId", "pipelineVersion", "developmentOnly", "predictionsSchemaVersion", "normalisation",
         "summaryPolicy", "parameters"},
        code,
    )
    if document["schemaVersion"] != PIPELINE_SCHEMA:
        raise _fail(code)
    if not isinstance(document["developmentOnly"], bool):
        raise _fail(f"{code}:developmentOnly")
    if document["predictionsSchemaVersion"] != PREDICTIONS_SCHEMA_VERSION:
        raise _fail(f"{code}:predictionsSchemaVersion")
    if document["normalisation"] != {"id": NORMALISATION_ID, "sha256": NORMALISATION_SHA256}:
        raise _fail(f"{code}:normalisation")

    summary_document, _, summary_sha256 = _pinned_sibling(path, document["summaryPolicy"], "plate_summary_policy_invalid")
    summary_code = "plate_summary_policy_invalid"
    _exact_keys(summary_document, {"schemaVersion", "summaryPolicyId", "summaryPolicyVersion", "method"}, summary_code)
    if summary_document["schemaVersion"] != SUMMARY_POLICY_SCHEMA or summary_document["method"] != SUMMARY_POLICY_METHOD:
        raise _fail(summary_code)
    summary = SummaryPolicy(
        policy_id=_token(summary_document["summaryPolicyId"], f"{summary_code}:summaryPolicyId"),
        version=_version(summary_document["summaryPolicyVersion"], f"{summary_code}:summaryPolicyVersion"),
        sha256=summary_sha256,
        method=SUMMARY_POLICY_METHOD,
    )

    _, parameter_payload, parameters_sha256 = _pinned_sibling(path, document["parameters"], "plate_parameters_invalid")
    try:
        parameters = load_parameters(parameter_payload)
    except ParametersInvalid as exc:
        raise _fail(str(exc)) from exc

    return PlatePipelineProfile(
        path=path,
        sha256=hashlib.sha256(payload).hexdigest(),
        pipeline_id=_token(document["pipelineId"], f"{code}:pipelineId"),
        pipeline_version=_version(document["pipelineVersion"], f"{code}:pipelineVersion"),
        development_only=document["developmentOnly"],
        summary_policy=summary,
        parameters=parameters,
        parameters_sha256=parameters_sha256,
    )


def canonical_identity_bytes(profile: PlatePipelineProfile, capabilities: tuple[PlateCapabilityIdentity, ...]) -> bytes:
    """Sorted keys, compact separators, ASCII-only, one trailing LF (``mavi-plate-identity-v1``)."""
    payload = {
        "capabilities": [{"capabilityId": item.capability_id, "modelPackId": item.model_pack_id} for item in capabilities],
        "normalisation": {"id": NORMALISATION_ID, "sha256": NORMALISATION_SHA256},
        "parametersSha256": profile.parameters_sha256,
        "pipeline": {"id": profile.pipeline_id, "version": profile.pipeline_version},
        "predictionsSchemaVersion": PREDICTIONS_SCHEMA_VERSION,
        "schemaVersion": IDENTITY_SCHEMA_VERSION,
        "summaryPolicy": {
            "id": profile.summary_policy.policy_id,
            "sha256": profile.summary_policy.sha256,
            "version": profile.summary_policy.version,
        },
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def plate_identity(profile: PlatePipelineProfile, capabilities: Mapping[str, str]) -> PlateIdentity:
    """The identity of the enabled ``ocr`` and ``plate-detector`` bindings under this profile."""
    if set(capabilities) != set(CAPABILITIES):
        raise _fail("plate_capabilities_incomplete")
    ordered: list[PlateCapabilityIdentity] = []
    for capability_id in CAPABILITIES:
        model_pack_id = capabilities[capability_id]
        if _MODEL_PACK_ID_RE.fullmatch(model_pack_id) is None:
            raise _fail("plate_model_pack_id_invalid")
        ordered.append(PlateCapabilityIdentity(capability_id, model_pack_id))
    items = tuple(ordered)
    canonical = canonical_identity_bytes(profile, items)
    return PlateIdentity(
        fingerprint=hashlib.sha256(canonical).hexdigest(),
        canonical=canonical.decode("ascii"),
        pipeline_id=profile.pipeline_id,
        pipeline_version=profile.pipeline_version,
        summary_policy=profile.summary_policy,
        capabilities=items,
        parameters_sha256=profile.parameters_sha256,
    )


__all__ = [
    "PIPELINE_SCHEMA",
    "PlateCapabilityIdentity",
    "PlateIdentity",
    "PlatePipelineProfile",
    "SummaryPolicy",
    "canonical_identity_bytes",
    "load_plate_pipeline",
    "plate_identity",
]
