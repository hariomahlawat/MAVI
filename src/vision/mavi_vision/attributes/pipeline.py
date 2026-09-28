"""The attribute pipeline profile and the analysis identity it defines (ADR-013 §11, §16).

The profile is release text beside the Component Binding. It pins, by SHA-256 of the exact
file bytes, the attribute schema, the aggregation policy and the parameters an analysis
runs with. The platform reads the same files (ADR-013 implementation amendment 2026-09-28),
so both sides derive the identity from the same bytes with the one canonical encoding below;
``contracts/test-vectors/visual-attribute-identity-v1.json`` holds them to it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.schema_common import read_release_json_v2

PIPELINE_SCHEMA = "mavi-visual-attribute-pipeline-v1"
ATTRIBUTE_SCHEMA_SCHEMA = "mavi-visual-attribute-schema-v1"
AGGREGATION_SCHEMA = "mavi-visual-attribute-aggregation-v1"
PARAMETERS_SCHEMA = "mavi-visual-attribute-parameters-v1"
IDENTITY_SCHEMA = "mavi-visual-attribute-identity-v1"

ATTRIBUTE_CAPABILITIES = MappingProxyType(
    {"person-attributes": "person", "vehicle-attributes": "vehicle"}
)
MAXIMUM_SCHEMA_ATTRIBUTE_TYPES = 16
MAXIMUM_ATTRIBUTE_TYPES_PER_OBJECT_CLASS = 8
MAXIMUM_ATTRIBUTE_VALUES = 32
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


def _exact_keys(document: Mapping[str, object], keys: set[str], code: str) -> None:
    if set(document) != keys:
        raise _fail(code)


@dataclass(frozen=True, slots=True)
class AttributeDefinition:
    attribute_type: str
    capability_id: str
    object_class: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AttributeSchema:
    schema_id: str
    version: str
    sha256: str
    attributes: tuple[AttributeDefinition, ...]

    def for_object_class(self, object_class: str) -> tuple[AttributeDefinition, ...]:
        return tuple(item for item in self.attributes if item.object_class == object_class)

    @property
    def capability_ids(self) -> frozenset[str]:
        return frozenset(item.capability_id for item in self.attributes)


@dataclass(frozen=True, slots=True)
class AggregationPolicy:
    policy_id: str
    version: str
    sha256: str
    method: str
    minimum_confidence: float


@dataclass(frozen=True, slots=True)
class AttributePipelineProfile:
    path: Path
    sha256: str
    pipeline_id: str
    pipeline_version: str
    development_only: bool
    schema: AttributeSchema
    aggregation: AggregationPolicy
    parameters_sha256: str
    parameters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CapabilityIdentity:
    capability_id: str
    model_pack_id: str


@dataclass(frozen=True, slots=True)
class AttributeIdentity:
    """The ADR-013 §11 identity without the run; ``fingerprint`` is its §16 SHA-256."""

    fingerprint: str
    attribute_schema_id: str
    attribute_schema_version: str
    attribute_schema_sha256: str
    pipeline_id: str
    pipeline_version: str
    aggregation_policy_id: str
    aggregation_policy_version: str
    aggregation_policy_sha256: str
    capabilities: tuple[CapabilityIdentity, ...]
    parameters_sha256: str


# --------------------------------------------------------------------------- loading


def _pinned_sibling(profile_path: Path, reference: object, code: str) -> tuple[dict, str]:
    if not isinstance(reference, dict):
        raise _fail(code)
    _exact_keys(reference, {"file", "sha256"}, code)
    name, sha256 = reference["file"], reference["sha256"]
    if not isinstance(name, str) or _FILE_NAME_RE.fullmatch(name) is None or ".." in name:
        raise _fail(code)
    if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
        raise _fail(code)
    document, payload = read_release_json_v2(profile_path.parent / name, code=code)
    if hashlib.sha256(payload).hexdigest() != sha256:
        raise _fail(f"{code}:sha256_mismatch")
    return document, sha256


def _parse_schema(document: dict, sha256: str) -> AttributeSchema:
    code = "attribute_schema_invalid"
    _exact_keys(document, {"schemaVersion", "attributeSchemaId", "attributeSchemaVersion", "attributes"}, code)
    if document["schemaVersion"] != ATTRIBUTE_SCHEMA_SCHEMA:
        raise _fail(code)
    attributes = document["attributes"]
    if not isinstance(attributes, list) or not 1 <= len(attributes) <= MAXIMUM_SCHEMA_ATTRIBUTE_TYPES:
        raise _fail(f"{code}:attributes")
    parsed: list[AttributeDefinition] = []
    for item in attributes:
        if not isinstance(item, dict):
            raise _fail(f"{code}:attributes")
        _exact_keys(item, {"attributeType", "capabilityId", "objectClass", "values"}, f"{code}:attributes")
        attribute_type = _token(item["attributeType"], f"{code}:attributeType")
        capability_id = item["capabilityId"]
        if capability_id not in ATTRIBUTE_CAPABILITIES:
            raise _fail(f"{code}:capabilityId")
        object_class = item["objectClass"]
        if ATTRIBUTE_CAPABILITIES[capability_id] != object_class:
            raise _fail(f"{code}:objectClass")
        values = item["values"]
        if not isinstance(values, list) or not 1 <= len(values) <= MAXIMUM_ATTRIBUTE_VALUES:
            raise _fail(f"{code}:values")
        tokens = tuple(_token(value, f"{code}:values") for value in values)
        if list(tokens) != sorted(set(tokens)):
            raise _fail(f"{code}:values_order")
        parsed.append(AttributeDefinition(attribute_type, capability_id, object_class, tokens))
    names = [item.attribute_type for item in parsed]
    if names != sorted(set(names)):
        raise _fail(f"{code}:attributes_order")
    for object_class in set(ATTRIBUTE_CAPABILITIES.values()):
        if sum(1 for item in parsed if item.object_class == object_class) > MAXIMUM_ATTRIBUTE_TYPES_PER_OBJECT_CLASS:
            raise _fail(f"{code}:object_class_limit")
    return AttributeSchema(
        schema_id=_token(document["attributeSchemaId"], f"{code}:attributeSchemaId"),
        version=_version(document["attributeSchemaVersion"], f"{code}:attributeSchemaVersion"),
        sha256=sha256,
        attributes=tuple(parsed),
    )


def _parse_aggregation(document: dict, sha256: str) -> AggregationPolicy:
    code = "aggregation_policy_invalid"
    _exact_keys(
        document,
        {"schemaVersion", "aggregationPolicyId", "aggregationPolicyVersion", "method", "minimumConfidence"},
        code,
    )
    if document["schemaVersion"] != AGGREGATION_SCHEMA or document["method"] != "mean-score-argmax":
        raise _fail(code)
    minimum = document["minimumConfidence"]
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not 0.0 <= float(minimum) <= 1.0:
        raise _fail(f"{code}:minimumConfidence")
    return AggregationPolicy(
        policy_id=_token(document["aggregationPolicyId"], f"{code}:aggregationPolicyId"),
        version=_version(document["aggregationPolicyVersion"], f"{code}:aggregationPolicyVersion"),
        sha256=sha256,
        method=document["method"],
        minimum_confidence=float(minimum),
    )


def load_attribute_pipeline(path: Path) -> AttributePipelineProfile:
    """Load and pin the profile and its three sibling documents, or fail closed."""
    code = "attribute_pipeline_invalid"
    document, payload = read_release_json_v2(path, code=code)
    _exact_keys(
        document,
        {
            "schemaVersion",
            "pipelineId",
            "pipelineVersion",
            "developmentOnly",
            "attributeSchema",
            "aggregationPolicy",
            "parameters",
        },
        code,
    )
    if document["schemaVersion"] != PIPELINE_SCHEMA:
        raise _fail(code)
    if not isinstance(document["developmentOnly"], bool):
        raise _fail(f"{code}:developmentOnly")
    schema_document, schema_sha256 = _pinned_sibling(path, document["attributeSchema"], "attribute_schema_invalid")
    aggregation_document, aggregation_sha256 = _pinned_sibling(
        path, document["aggregationPolicy"], "aggregation_policy_invalid"
    )
    parameters_document, parameters_sha256 = _pinned_sibling(path, document["parameters"], "attribute_parameters_invalid")
    _exact_keys(parameters_document, {"schemaVersion", "parameters"}, "attribute_parameters_invalid")
    if parameters_document["schemaVersion"] != PARAMETERS_SCHEMA or not isinstance(
        parameters_document["parameters"], dict
    ):
        raise _fail("attribute_parameters_invalid")
    return AttributePipelineProfile(
        path=path,
        sha256=hashlib.sha256(payload).hexdigest(),
        pipeline_id=_token(document["pipelineId"], f"{code}:pipelineId"),
        pipeline_version=_version(document["pipelineVersion"], f"{code}:pipelineVersion"),
        development_only=document["developmentOnly"],
        schema=_parse_schema(schema_document, schema_sha256),
        aggregation=_parse_aggregation(aggregation_document, aggregation_sha256),
        parameters_sha256=parameters_sha256,
        parameters=MappingProxyType(dict(parameters_document["parameters"])),
    )


# --------------------------------------------------------------------------- identity


def canonical_identity_bytes(
    profile: AttributePipelineProfile, capabilities: tuple[CapabilityIdentity, ...]
) -> bytes:
    """Sorted keys, compact separators, ASCII-only, one trailing LF (the pack-identity encoding)."""
    payload = {
        "aggregationPolicy": {
            "id": profile.aggregation.policy_id,
            "sha256": profile.aggregation.sha256,
            "version": profile.aggregation.version,
        },
        "attributeSchema": {
            "id": profile.schema.schema_id,
            "sha256": profile.schema.sha256,
            "version": profile.schema.version,
        },
        "capabilities": [
            {"capabilityId": item.capability_id, "modelPackId": item.model_pack_id} for item in capabilities
        ],
        "parametersSha256": profile.parameters_sha256,
        "pipeline": {"id": profile.pipeline_id, "version": profile.pipeline_version},
        "schemaVersion": IDENTITY_SCHEMA,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def attribute_identity(
    profile: AttributePipelineProfile, capabilities: Mapping[str, str]
) -> AttributeIdentity:
    """The identity of the enabled attribute bindings under this profile.

    ``capabilities`` maps each bound capability id to its Model Pack id. The bound set must be
    exactly the set the schema's attributes are served by, so neither side can bind a
    capability the schema does not use or leave one of its attributes unserved.
    """
    if set(capabilities) != set(profile.schema.capability_ids):
        raise _fail("attribute_capabilities_schema_mismatch")
    ordered: list[CapabilityIdentity] = []
    for capability_id in sorted(capabilities):
        model_pack_id = capabilities[capability_id]
        if _MODEL_PACK_ID_RE.fullmatch(model_pack_id) is None:
            raise _fail("attribute_model_pack_id_invalid")
        ordered.append(CapabilityIdentity(capability_id, model_pack_id))
    items = tuple(ordered)
    return AttributeIdentity(
        fingerprint=hashlib.sha256(canonical_identity_bytes(profile, items)).hexdigest(),
        attribute_schema_id=profile.schema.schema_id,
        attribute_schema_version=profile.schema.version,
        attribute_schema_sha256=profile.schema.sha256,
        pipeline_id=profile.pipeline_id,
        pipeline_version=profile.pipeline_version,
        aggregation_policy_id=profile.aggregation.policy_id,
        aggregation_policy_version=profile.aggregation.version,
        aggregation_policy_sha256=profile.aggregation.sha256,
        capabilities=items,
        parameters_sha256=profile.parameters_sha256,
    )


__all__ = [
    "ATTRIBUTE_CAPABILITIES",
    "AggregationPolicy",
    "AttributeDefinition",
    "AttributeIdentity",
    "AttributePipelineProfile",
    "AttributeSchema",
    "CapabilityIdentity",
    "IDENTITY_SCHEMA",
    "attribute_identity",
    "canonical_identity_bytes",
    "load_attribute_pipeline",
]
