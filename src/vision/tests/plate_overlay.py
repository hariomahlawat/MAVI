"""A Development overlay with the Stage-4 ``plates`` role bound to a fixture Model Pack.

Built on the vision ``Overlay`` exactly as the attribute overlay is: the committed binding, runtime
family, locks and gate sets are copied, then the ``plates`` role, one fixture Model Pack serving both
plate capabilities, one qualification record per capability and a capability gate set are added. Every
identity is derived from bytes; nothing is written to the repository. The fixture pack is ``unverified``
and its pipeline profile ``developmentOnly``, so the overlay can never start in Production.

Run as ``python -m tests.plate_overlay <directory>`` it writes the overlay and prints the paths a host
needs (for the .NET end-to-end test), as JSON.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from mavi_vision.plates.settings import PlateWorkerSettings
from tests.component_binding_v2_fixtures import LICENCE_BYTES, REPOSITORY
from tests.resolver_overlay import Overlay, _dump, sha256_bytes

FIXTURE_PROFILE_DIRECTORY = REPOSITORY / "tests/fixtures/plates"
FIXTURE_PROFILE_FILES = ("fixture-pipeline-v1.json", "fixture-summary-policy-v1.json", "fixture-parameters-v1.json")
PLATE_CAPABILITIES = ("ocr", "plate-detector")
GATE_SET_ID = "plates-fixture-v1"
FIXTURE_GATES = ("plate-fixture-lifecycle",)

FIXTURE_MANIFEST = {
    "schemaVersion": "2.0",
    "modelId": "plates-fixture",
    "modelVersion": "1.0.0",
    "capabilityIds": list(PLATE_CAPABILITIES),
    "artifacts": [
        {"artifactRole": "fixture-definition", "relativePath": "plates-fixture-v1/fixture.txt", "sha256": "0" * 64},
        {"artifactRole": "licence-notice", "relativePath": "plates-fixture-v1/LICENSE", "sha256": "0" * 64},
    ],
    "inputContract": {"kind": "evidence-crop-jpeg", "colourSpace": "RGB"},
    "outputContract": {"schemaId": "plate-readings-v1"},
    "runtimeCompatibility": {"runtimePackFamilyIds": ["mmdetection-phase1-v1"]},
    "licence": {"spdxId": "Apache-2.0", "noticeArtifactRole": "licence-notice", "reviewStatus": "pending-review"},
    "provenance": {"publisher": "MAVI", "sourceRepository": "mavi/tests/fixtures", "sourceRevision": "stage4-pr3-fixture-v1"},
    "verificationStatus": "unverified",
    "qualificationId": None,
    "capabilitySpecific": {},
}
FIXTURE_ARTIFACTS = {
    "fixture-definition": b"MAVI Stage 4 plate fixture: deterministic, model-free, Development only.\n",
    "licence-notice": LICENCE_BYTES,
}


@dataclass
class PlateOverlay:
    vision: Overlay
    manifest: dict
    records: dict[str, dict]
    gate_sets: dict

    @classmethod
    def create(cls, tmp_path: Path) -> "PlateOverlay":
        vision = Overlay.create(tmp_path)
        profile_directory = vision.root / "plates-profile"
        profile_directory.mkdir(parents=True, exist_ok=True)
        for name in FIXTURE_PROFILE_FILES:
            shutil.copyfile(FIXTURE_PROFILE_DIRECTORY / name, profile_directory / name)
        gate_sets = json.loads((vision.root / "config/acceptance/capability-gate-sets-v1.json").read_text(encoding="utf-8"))
        gate_sets["gateSets"][GATE_SET_ID] = {"scope": "capability", "capabilityIds": list(PLATE_CAPABILITIES), "gates": list(FIXTURE_GATES)}
        overlay = cls(vision=vision, manifest=copy.deepcopy(FIXTURE_MANIFEST), records={}, gate_sets=gate_sets)
        overlay._add_role()
        overlay.write()
        return overlay

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
        return self.root / "plates-profile" / "fixture-pipeline-v1.json"

    @property
    def manifest_path(self) -> Path:
        return self.root / "models/manifests/plates-fixture-v1.json"

    def record_path(self, capability_id: str) -> Path:
        return self.root / f"models/qualifications/{capability_id}-fixture.json"

    def _add_role(self) -> None:
        binding = self.vision.binding
        binding["roles"].append(
            {
                "roleId": "plates",
                "runtimePackFamilyId": "mmdetection-phase1-v1",
                "capabilityIds": list(PLATE_CAPABILITIES),
                "entryPoint": "mavi_vision.plates.main",
                "readinessContract": "worker-health-v2",
                "provenanceContract": "plate-complete-v1",
            }
        )
        for capability_id in PLATE_CAPABILITIES:
            binding["capabilityBindings"].append(
                {
                    "capabilityId": capability_id,
                    "roleId": "plates",
                    "modelPackId": "mavi-model-v2-" + "0" * 64,
                    "qualificationId": f"{capability_id}-fixture",
                    "enabled": True,
                }
            )
        template = self.vision.record
        for capability_id in PLATE_CAPABILITIES:
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
        from mavi_vision.runtime.model_pack_identity import ModelPackArtifactIdentity, ModelPackIdentityInputsV2, model_pack_id_v2

        return model_pack_id_v2(
            ModelPackIdentityInputsV2(
                model_id=self.manifest["modelId"],
                model_version=self.manifest["modelVersion"],
                capability_ids=tuple(self.manifest["capabilityIds"]),
                artifacts=tuple(
                    ModelPackArtifactIdentity(artifact_role=item["artifactRole"], sha256=item["sha256"]) for item in self.manifest["artifacts"]
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
        for record in self.records.values():
            record["modelPackId"] = derived
            record["modelManifestSha256"] = sha256_bytes(self.manifest_path.read_bytes())
            record["artifactSha256"] = {item["artifactRole"]: item["sha256"] for item in self.manifest["artifacts"]}
            record["runtimeProfileSha256"] = runtime_sha
            record["policies"] = {"pipelineProfileId": "plates-fixture", "pipelineProfileSha256": profile_sha}
        for capability_id, record in self.records.items():
            _dump(self.record_path(capability_id), record)
        for binding in self.vision.binding["capabilityBindings"]:
            if binding["roleId"] == "plates":
                binding["modelPackId"] = derived
        self.vision.write()

    def settings(self, **overrides) -> PlateWorkerSettings:
        values = {
            "api_base_url": "http://127.0.0.1:5000",
            "worker_id": "plates-01",
            "component_binding_path": self.binding_path,
            "overlay_root": self.root,
            "model_root": self.model_root,
            "pipeline_profile_path": self.pipeline_profile_path,
        }
        values.update(overrides)
        return PlateWorkerSettings(**values)

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
        print("usage: python -m tests.plate_overlay <directory>", file=sys.stderr)
        return 2
    overlay = PlateOverlay.create(Path(argv[0]))
    print(json.dumps(overlay.describe()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
