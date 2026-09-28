"""A Development overlay with the S2b ``attributes`` role bound to a fixture Model Pack.

Built on the vision ``Overlay``: the committed binding, runtime family, locks and gate sets are
copied, then the ``attributes`` role, one fixture Model Pack serving both attribute
capabilities, one qualification record per capability and a capability gate set are added.
Every identity is derived from bytes exactly as for the detector pack (manifest digests,
``modelPackId``, record identity blocks, binding pins); nothing is written to the repository.
The fixture pack is ``unverified`` and its pipeline profile ``developmentOnly``, so the overlay
can never start in Production.

Run as ``python -m tests.attribute_overlay <directory>`` it writes the overlay and prints the
paths a host needs (for the .NET end-to-end test), as JSON.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from mavi_vision.attributes.settings import AttributeWorkerSettings
from tests.resolver_overlay import Overlay, _dump, sha256_bytes
from tests.component_binding_v2_fixtures import LICENCE_BYTES, REPOSITORY

FIXTURE_PROFILE_DIRECTORY = REPOSITORY / "tests/fixtures/visual-attributes"
FIXTURE_PROFILE_FILES = (
    "fixture-pipeline-v1.json",
    "fixture-attribute-schema-v1.json",
    "fixture-aggregation-policy-v1.json",
    "fixture-parameters-v1.json",
)
ATTRIBUTE_CAPABILITIES = ("person-attributes", "vehicle-attributes")
GATE_SET_ID = "visual-attributes-fixture-v1"
FIXTURE_GATES = ("attribute-fixture-lifecycle",)

FIXTURE_MANIFEST = {
    "schemaVersion": "2.0",
    "modelId": "visual-attributes-fixture",
    "modelVersion": "1.0.0",
    "capabilityIds": list(ATTRIBUTE_CAPABILITIES),
    "artifacts": [
        {"artifactRole": "fixture-definition", "relativePath": "visual-attributes-fixture-v1/fixture.txt", "sha256": "0" * 64},
        {"artifactRole": "licence-notice", "relativePath": "visual-attributes-fixture-v1/LICENSE", "sha256": "0" * 64},
    ],
    "inputContract": {"kind": "evidence-crop-jpeg", "colourSpace": "RGB"},
    "outputContract": {"schemaId": "attribute-scores-v1"},
    "runtimeCompatibility": {"runtimePackFamilyIds": ["mmdetection-phase1-v1"]},
    "licence": {"spdxId": "Apache-2.0", "noticeArtifactRole": "licence-notice", "reviewStatus": "pending-review"},
    "provenance": {"publisher": "MAVI", "sourceRepository": "mavi/tests/fixtures", "sourceRevision": "s2b-fixture-v1"},
    "verificationStatus": "unverified",
    "qualificationId": None,
    "capabilitySpecific": {},
}
FIXTURE_ARTIFACTS = {
    "fixture-definition": b"MAVI S2b visual attribute fixture: deterministic, model-free, Development only.\n",
    "licence-notice": LICENCE_BYTES,
}


@dataclass
class AttributeOverlay:
    vision: Overlay
    manifest: dict
    records: dict[str, dict]
    gate_sets: dict

    @classmethod
    def create(cls, tmp_path: Path) -> "AttributeOverlay":
        vision = Overlay.create(tmp_path)
        profile_directory = vision.root / "attributes-profile"
        profile_directory.mkdir(parents=True, exist_ok=True)
        for name in FIXTURE_PROFILE_FILES:
            shutil.copyfile(FIXTURE_PROFILE_DIRECTORY / name, profile_directory / name)
        gate_sets = json.loads((vision.root / "config/acceptance/capability-gate-sets-v1.json").read_text(encoding="utf-8"))
        gate_sets["gateSets"][GATE_SET_ID] = {
            "scope": "capability",
            "capabilityIds": list(ATTRIBUTE_CAPABILITIES),
            "gates": list(FIXTURE_GATES),
        }
        overlay = cls(vision=vision, manifest=copy.deepcopy(FIXTURE_MANIFEST), records={}, gate_sets=gate_sets)
        overlay._add_role()
        overlay.write()
        return overlay

    # ------------------------------------------------------------------ paths

    @property
    def root(self) -> Path:
        return self.vision.root

    @property
    def model_root(self) -> Path:
        return self.vision.model_root

    @property
    def binding_path(self) -> Path:
        return self.vision.binding_path

    @property
    def pipeline_profile_path(self) -> Path:
        return self.root / "attributes-profile" / "fixture-pipeline-v1.json"

    @property
    def manifest_path(self) -> Path:
        return self.root / "models/manifests/visual-attributes-fixture-v1.json"

    def record_path(self, capability_id: str) -> Path:
        return self.root / f"models/qualifications/{capability_id}-fixture.json"

    # ------------------------------------------------------------------ derivation

    def _add_role(self) -> None:
        binding = self.vision.binding
        binding["roles"].append(
            {
                "roleId": "attributes",
                "runtimePackFamilyId": "mmdetection-phase1-v1",
                "capabilityIds": list(ATTRIBUTE_CAPABILITIES),
                "entryPoint": "mavi_vision.attributes.main",
                "readinessContract": "worker-health-v2",
                "provenanceContract": "visual-attribute-complete-v1",
            }
        )
        for capability_id in ATTRIBUTE_CAPABILITIES:
            binding["capabilityBindings"].append(
                {
                    "capabilityId": capability_id,
                    "roleId": "attributes",
                    "modelPackId": "mavi-model-v2-" + "0" * 64,
                    "qualificationId": f"{capability_id}-fixture",
                    "enabled": True,
                }
            )
        template = self.vision.record
        for capability_id in ATTRIBUTE_CAPABILITIES:
            record = copy.deepcopy(template)
            record["qualificationId"] = f"{capability_id}-fixture"
            record["capabilityId"] = capability_id
            record["modelId"] = self.manifest["modelId"]
            record["outputContract"] = {"schemaId": self.manifest["outputContract"]["schemaId"]}
            record["gateSetIds"] = ["common-v1", GATE_SET_ID]
            common = self.gate_sets["gateSets"]["common-v1"]["gates"]
            for variant in record["variants"].values():
                variant["status"] = "pending"
                variant["gates"] = {gate: "pending" for gate in [*common, *FIXTURE_GATES]}
            record["qualifiedProfiles"] = []
            record["profileQualifications"] = {}
            record["evidence"] = {}
            record["overallResult"] = "pending"
            record.pop("supersedes", None)
            self.records[capability_id] = record

    def derived_model_pack_id(self) -> str:
        from mavi_vision.runtime.model_pack_identity import (
            ModelPackArtifactIdentity,
            ModelPackIdentityInputsV2,
            model_pack_id_v2,
        )

        return model_pack_id_v2(
            ModelPackIdentityInputsV2(
                model_id=self.manifest["modelId"],
                model_version=self.manifest["modelVersion"],
                capability_ids=tuple(self.manifest["capabilityIds"]),
                artifacts=tuple(
                    ModelPackArtifactIdentity(artifact_role=item["artifactRole"], sha256=item["sha256"])
                    for item in self.manifest["artifacts"]
                ),
            )
        )

    def write(self) -> None:
        _dump(self.root / "config/acceptance/capability-gate-sets-v1.json", self.gate_sets)
        for item in self.manifest["artifacts"]:
            data = FIXTURE_ARTIFACTS[item["artifactRole"]]
            target = self.model_root / item["relativePath"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            item["sha256"] = sha256_bytes(data)
        _dump(self.manifest_path, self.manifest)
        derived = self.derived_model_pack_id()
        runtime_sha = sha256_bytes(self.vision.runtime_path.read_bytes())
        profile_sha = sha256_bytes(self.pipeline_profile_path.read_bytes())
        for capability_id, record in self.records.items():
            record["modelPackId"] = derived
            record["modelManifestSha256"] = sha256_bytes(self.manifest_path.read_bytes())
            record["artifactSha256"] = {item["artifactRole"]: item["sha256"] for item in self.manifest["artifacts"]}
            record["runtimeProfileSha256"] = runtime_sha
            record["policies"] = {"pipelineProfileId": "visual-attributes-fixture", "pipelineProfileSha256": profile_sha}
            _dump(self.record_path(capability_id), record)
        for binding in self.vision.binding["capabilityBindings"]:
            if binding["roleId"] == "attributes":
                binding["modelPackId"] = derived
        # Keeps the detector pack's own derivation (and the vision role resolvable).
        self.vision.write()

    # ------------------------------------------------------------------ settings

    def settings(self, **overrides) -> AttributeWorkerSettings:
        values = {
            "api_base_url": "http://127.0.0.1:5000",
            "worker_id": "attributes-01",
            "component_binding_path": self.binding_path,
            "overlay_root": self.root,
            "model_root": self.model_root,
            "pipeline_profile_path": self.pipeline_profile_path,
        }
        values.update(overrides)
        return AttributeWorkerSettings(**values)

    def describe(self) -> dict[str, str]:
        return {
            "componentBindingPath": str(self.binding_path),
            "pipelineProfilePath": str(self.pipeline_profile_path),
            "overlayRoot": str(self.root),
            "modelRoot": str(self.model_root),
            "modelPackId": self.derived_model_pack_id(),
        }


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m tests.attribute_overlay <directory>", file=sys.stderr)
        return 2
    overlay = AttributeOverlay.create(Path(argv[0]))
    print(json.dumps(overlay.describe()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
