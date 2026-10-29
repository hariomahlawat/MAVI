"""Write the PoC S5 zero-shot attribute release documents (zero-shot, Development).

One declarative source for the attribute vocabulary, prompts and per-attribute abstention thresholds; every pin is
derived from bytes: the pipeline profile pins its schema, aggregation policy and parameters by SHA-256; the
parameters pin the SigLIP 2 Model Pack manifest by SHA-256; the binding names that manifest's derived
``modelPackId``. ``--check`` fails if any committed file differs from what this script would write.

    python tools/poc/attributes_zero_shot_profile.py [--check] [--thresholds thresholds.json]

``--thresholds`` takes ``{"<attributeType>": <threshold>}`` from the calibration note
(``docs/qualification/poc/s5-zero-shot-attributes.md``); without it the committed thresholds are kept.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src" / "vision"))

from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2  # noqa: E402

DIRECTORY = REPOSITORY / "src/vision/config/attributes"
MANIFEST = REPOSITORY / "models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json"
RECORD_ID = "attributes-siglip2-zero-shot-development"
LOGIT_SCALE = 112.66889953613281  # E:\MAVI-Controlled\PoC\S4\pack\build-record.json
MINIMUM_CROP_SIDE = 80  # ADR-021 §1

PERSON_COLOURS = ("black", "blue", "brown", "green", "grey", "orange", "pink", "purple", "red", "white", "yellow")
VEHICLE_COLOURS = ("beige", "black", "blue", "brown", "green", "grey", "orange", "red", "silver", "white", "yellow")

# attributeType -> (capabilityId, objectClass, kind, values, prompts)
ATTRIBUTES = {
    "person-carried-bag": (
        "person-attributes", "person", "presence", ("present",),
        {
            "present": ["a photo of a person carrying a bag", "a photo of a person wearing a backpack",
                        "a photo of a person carrying a handbag"],
            "absent": ["a photo of a person without a bag", "a photo of a person with empty hands"],
        },
    ),
    "person-headwear": (
        "person-attributes", "person", "presence", ("present",),
        {
            "present": ["a photo of a person wearing a hat", "a photo of a person wearing a cap",
                        "a photo of a person wearing a helmet"],
            "absent": ["a photo of a person with a bare head", "a photo of a person not wearing a hat"],
        },
    ),
    "person-lower-colour": (
        "person-attributes", "person", "categorical", PERSON_COLOURS,
        {c: [f"a photo of a person wearing {c} trousers", f"a photo of a person wearing {c} pants",
             f"a photo of a person wearing a {c} skirt"] for c in PERSON_COLOURS},
    ),
    "person-upper-colour": (
        "person-attributes", "person", "categorical", PERSON_COLOURS,
        {c: [f"a photo of a person wearing a {c} top", f"a photo of a person wearing a {c} shirt",
             f"a photo of a person wearing a {c} jacket"] for c in PERSON_COLOURS},
    ),
    "vehicle-colour": (
        "vehicle-attributes", "vehicle", "categorical", VEHICLE_COLOURS,
        {c: [f"a photo of a {c} car", f"a photo of a {c} vehicle", f"a photo of a {c} truck"] for c in VEHICLE_COLOURS},
    ),
}


def text(document: object) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def documents(thresholds: dict[str, float]) -> dict[str, bytes]:
    manifest_bytes = MANIFEST.read_bytes()
    manifest = load_model_manifest_v2(MANIFEST)
    schema = text({
        "schemaVersion": "mavi-visual-attribute-schema-v1",
        "attributeSchemaId": "poc-zero-shot-attributes",
        "attributeSchemaVersion": "1.0.0",
        "attributes": [
            {"attributeType": name, "capabilityId": capability, "objectClass": object_class, "values": list(values)}
            for name, (capability, object_class, _, values, _) in sorted(ATTRIBUTES.items())
        ],
    })
    aggregation = text({
        "schemaVersion": "mavi-visual-attribute-aggregation-v1",
        "aggregationPolicyId": "mean-score-argmax",
        "aggregationPolicyVersion": "1.0.0",
        "method": "mean-score-argmax",
        "minimumConfidence": 0.5,
    })
    parameters = text({
        "schemaVersion": "mavi-visual-attribute-parameters-v1",
        "parameters": {
            "inferencer": "siglip2-zero-shot-v1",
            "disclosure": "zero-shot, uncalibrated, Development",
            "modelManifest": {"file": MANIFEST.name, "sha256": sha256(manifest_bytes)},
            "logitScale": LOGIT_SCALE,
            "minimumCropSide": MINIMUM_CROP_SIDE,
            "attributes": {
                name: {"kind": kind, "threshold": thresholds[name], "prompts": prompts}
                for name, (_, _, kind, _, prompts) in sorted(ATTRIBUTES.items())
            },
        },
    })
    names = {
        "schema": "attribute-schema-poc-zero-shot-v1.json",
        "aggregation": "aggregation-mean-score-argmax-v1.json",
        "parameters": "parameters-siglip2-zero-shot-v1.json",
    }
    pipeline = text({
        "schemaVersion": "mavi-visual-attribute-pipeline-v1",
        "pipelineId": "attributes-siglip2-zero-shot",
        "pipelineVersion": "1.0.0",
        "developmentOnly": True,
        "attributeSchema": {"file": names["schema"], "sha256": sha256(schema)},
        "aggregationPolicy": {"file": names["aggregation"], "sha256": sha256(aggregation)},
        "parameters": {"file": names["parameters"], "sha256": sha256(parameters)},
    })
    record = text({
        "schemaVersion": "mavi-poc-development-record-v1",
        "recordId": RECORD_ID,
        "status": "development-unqualified",
        "statement": "Zero-shot, Development. SigLIP 2 zero-shot attribute scores with per-attribute abstention; "
                     "not a qualified or learned attribute Model Pack (Stage-2 S2c), closes no Stage-2 F/G row, "
                     "not Production-qualified.",
        "calibration": "docs/qualification/poc/s5-zero-shot-attributes.md",
    })
    binding = text({
        "schemaVersion": "mavi-vision-component-binding-v2",
        "bindingId": "poc-attributes-siglip2-zero-shot-v1",
        "runtimePacks": [],
        "roles": [{
            "roleId": "attributes",
            "runtimePackFamilyId": "embeddings-onnx-v1",
            "capabilityIds": ["person-attributes", "vehicle-attributes"],
            "entryPoint": "mavi_vision.attributes.main",
            "readinessContract": "worker-health-v2",
            "provenanceContract": "visual-attribute-complete-v1",
        }],
        "capabilityBindings": [
            {"capabilityId": capability, "roleId": "attributes", "modelPackId": manifest.model_pack_id,
             "qualificationId": RECORD_ID, "enabled": True}
            for capability in ("person-attributes", "vehicle-attributes")
        ],
    })
    return {
        names["schema"]: schema,
        names["aggregation"]: aggregation,
        names["parameters"]: parameters,
        "development-attributes-siglip2-zero-shot-v1.json": pipeline,
        f"{RECORD_ID}.json": record,
        "development-attributes-siglip2-binding-v1.json": binding,
    }


def committed_thresholds() -> dict[str, float]:
    path = DIRECTORY / "parameters-siglip2-zero-shot-v1.json"
    if not path.is_file():
        return {name: 0.5 for name in ATTRIBUTES}
    attributes = json.loads(path.read_text(encoding="utf-8"))["parameters"]["attributes"]
    return {name: float(attributes[name]["threshold"]) for name in ATTRIBUTES}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--thresholds", type=Path)
    args = parser.parse_args()
    thresholds = committed_thresholds()
    if args.thresholds is not None:
        update = json.loads(args.thresholds.read_text(encoding="utf-8"))
        if set(update) != set(ATTRIBUTES) or not all(0.0 < float(value) < 1.0 for value in update.values()):
            raise SystemExit("thresholds must name every attribute type with a value in (0, 1)")
        thresholds = {name: float(value) for name, value in update.items()}
    stale = []
    for name, payload in documents(thresholds).items():
        path = DIRECTORY / name
        if args.check:
            if not path.is_file() or path.read_bytes() != payload:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    if stale:
        print("stale zero-shot attribute documents: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
