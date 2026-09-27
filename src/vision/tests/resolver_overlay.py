"""A self-consistent overlay of the committed v2 composition, for resolver tests.

The committed binding, runtime family profile, locks, pipeline profile, gate
sets and qualification record are copied into a temporary overlay root. The
Model Pack's artefacts are small synthetic bytes (the real checkpoint is not in
Git), so ``write()`` re-derives exactly what the real artefacts derive: the
manifest's digests, the ``modelPackId`` (plan P-3), the record's identity block
and the binding's pinned id. A test then breaks one thing, after or instead of
that derivation, and names the stable code the resolver must fail with.

Nothing here fabricates a Runtime Pack id: an installed pack manifest is built
from the binding's own pinned entry and the runtime profile's Python identity,
and the resolver re-derives the id from it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from mavi_vision.runtime.deployment_profiles import DeploymentProfile, select_profile
from mavi_vision.runtime.model_pack_identity import (
    ModelPackArtifactIdentity,
    ModelPackIdentityInputsV2,
    model_pack_id_v2,
)
from mavi_vision.runtime.resolver import (
    RoleComposition,
    RoleCompositionInputs,
    resolve_completion_contract,
)
from mavi_vision.runtime.binding import load_component_binding
from tests.component_binding_v2_fixtures import (
    LICENCE_BYTES,
    REPOSITORY,
    RUNTIME_DIR,
    V2_BINDING,
    V2_MANIFEST,
    V2_QUALIFICATION,
)

FAMILY = "mmdetection-phase1-v1"
GATE_SETS = REPOSITORY / "config/acceptance/capability-gate-sets-v1.json"
DEPLOYMENT_PROFILES = REPOSITORY / "config/acceptance/phase1-deployment-profiles-v1.json"
PIPELINE_PROFILE = REPOSITORY / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
EVIDENCE = {"kind": "workflow", "reference": "run-1", "sha256": "e" * 64}
EMITTABLE = ("3.0", "3.1", "3.2")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _dump(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Overlay:
    root: Path
    model_root: Path
    manifest: dict
    record: dict
    binding: dict
    runtime: dict
    artifacts: dict[str, bytes] = field(default_factory=dict)

    # ------------------------------------------------------------------ layout

    @classmethod
    def create(cls, tmp_path: Path) -> "Overlay":
        root = tmp_path / "overlay"
        runtime_dir = root / "src/vision/runtime" / FAMILY
        runtime_dir.mkdir(parents=True)
        for source in RUNTIME_DIR.iterdir():
            if source.suffix in {".lock", ".txt"}:
                shutil.copyfile(source, runtime_dir / source.name)
        (root / "config/acceptance").mkdir(parents=True)
        shutil.copyfile(GATE_SETS, root / "config/acceptance/capability-gate-sets-v1.json")
        shutil.copyfile(PIPELINE_PROFILE, root / "pipeline.json")
        overlay = cls(
            root=root,
            model_root=tmp_path / "model-store",
            manifest=_load(V2_MANIFEST),
            record=_load(V2_QUALIFICATION),
            binding=_load(V2_BINDING),
            runtime=_load(RUNTIME_DIR / "runtime.json"),
            artifacts={
                "checkpoint": b"synthetic rtmdet checkpoint\n",
                "licence-notice": LICENCE_BYTES,
                "resolved-config": b"model = dict(type='RTMDet')\nload_from = None\n",
            },
        )
        overlay.write()
        return overlay

    @property
    def runtime_path(self) -> Path:
        return self.root / "src/vision/runtime" / FAMILY / "runtime.json"

    @property
    def manifest_path(self) -> Path:
        return self.root / "models/manifests/rtmdet-m-coco-phase1-v2.json"

    @property
    def record_path(self) -> Path:
        return self.root / "models/qualifications/rtmdet-m-coco-phase1-v2.json"

    @property
    def binding_path(self) -> Path:
        return self.root / "binding.json"

    @property
    def pipeline_path(self) -> Path:
        return self.root / "pipeline.json"

    @property
    def pack_manifest_path(self) -> Path:
        return self.root / "runtime-pack" / "runtime-pack-manifest.json"

    # ------------------------------------------------------------------ derivation

    def derived_model_pack_id(self) -> str:
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

    def write(self, *, sync: bool = True) -> None:
        """Write every file; ``sync`` re-derives each identity from the bytes first."""
        _dump(self.runtime_path, self.runtime)
        for item in self.manifest["artifacts"]:
            data = self.artifacts.get(item["artifactRole"])
            if data is None:
                continue
            target = self.model_root / item["relativePath"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if sync:
                item["sha256"] = sha256_bytes(data)
        _dump(self.manifest_path, self.manifest)
        if sync:
            derived = self.derived_model_pack_id()
            self.record["modelPackId"] = derived
            self.record["modelManifestSha256"] = sha256_bytes(self.manifest_path.read_bytes())
            self.record["artifactSha256"] = {
                item["artifactRole"]: item["sha256"] for item in self.manifest["artifacts"]
            }
            self.record["runtimeProfileSha256"] = sha256_bytes(self.runtime_path.read_bytes())
            self.record["policies"]["pipelineProfileSha256"] = sha256_bytes(self.pipeline_path.read_bytes())
            for binding in self.binding["capabilityBindings"]:
                if binding["capabilityId"] == "detector":
                    binding["modelPackId"] = derived
        _dump(self.record_path, self.record)
        _dump(self.binding_path, self.binding)

    # ------------------------------------------------------------------ Runtime Pack

    def pack_manifest_for(self, variant: str) -> dict:
        """What an installed pack built from the tracked lock records (never an invented id)."""
        entry = self.binding["runtimePacks"][0]["variants"][variant]
        return {
            "schemaVersion": "mavi-vision-runtime-pack-v2",
            "runtimePackId": entry["runtimePackId"],
            "platformVariant": variant,
            "pythonVersion": self.runtime["platformVariants"][variant]["pythonIdentity"]["version"],
            "nativeAbi": entry["nativeAbi"],
            "thirdPartyLockSha256": entry["thirdPartyLockSha256"],
            "runtimeRequirementsSha256": entry["runtimeRequirementsSha256"],
        }

    def install_pack(self, variant: str, **changes: str) -> dict:
        document = self.pack_manifest_for(variant)
        document.update(changes)
        _dump(self.pack_manifest_path, document)
        return document

    # ------------------------------------------------------------------ qualification

    def pass_variant(self, variant: str) -> None:
        entry = self.record["variants"][variant]
        entry["gates"] = {gate: "passed" for gate in entry["gates"]}
        entry["status"] = "passed"
        self.record["evidence"][variant] = {gate: dict(EVIDENCE) for gate in entry["gates"]}

    def qualify_for_production(self, *, profile_id: str = "P3") -> tuple[DeploymentProfile, str]:
        """Every claim a Production start needs, made consistently (never committed)."""
        profile, policy_sha = select_profile(profile_id, DEPLOYMENT_PROFILES)
        variant = profile.runtime_variant
        self.pass_variant(variant)
        self.record["qualifiedProfiles"] = [profile_id]
        self.record["profileQualifications"] = {
            profile_id: {
                "deploymentProfilePolicySha256": policy_sha,
                "runtimeVariant": variant,
                "evidence": {gate: dict(EVIDENCE) for gate in self.record["variants"][variant]["gates"]},
            }
        }
        self.record["overallResult"] = "passed"
        self.manifest["verificationStatus"] = "verified"
        self.manifest["qualificationId"] = self.record["qualificationId"]
        self.manifest["licence"]["reviewStatus"] = "approved"
        self.write()
        self.install_pack(variant)
        return profile, policy_sha

    # ------------------------------------------------------------------ composition

    def composition(
        self,
        *,
        production_mode: bool = False,
        override: str | None = None,
        installed: bool = False,
    ) -> RoleComposition:
        binding = load_component_binding(self.binding_path)
        completion = resolve_completion_contract(
            binding.role("vision"),
            override=override,
            production_mode=production_mode,
            emittable_versions=EMITTABLE,
        )
        return RoleComposition(
            RoleCompositionInputs(
                component_binding_path=self.binding_path,
                role_id="vision",
                overlay_root=self.root,
                model_root=self.model_root,
                pipeline_profile_path=self.pipeline_path,
                runtime_pack_manifest_path=self.pack_manifest_path if installed else None,
                production_mode=production_mode,
            ),
            completion=completion,
            binding=binding,
        )

    def resolve(
        self,
        variant: str = "linux-x86_64-cpu",
        *,
        python_version: str | None = None,
        production_mode: bool = False,
        override: str | None = None,
        installed: bool = False,
        profile_requirement: DeploymentProfile | None = None,
        deployment_profile_policy_sha256: str | None = None,
    ):
        if python_version is None:
            identity = self.runtime["platformVariants"][variant].get("pythonIdentity") or {}
            python_version = identity.get("version", "3.12.14")
        return self.composition(
            production_mode=production_mode, override=override, installed=installed
        ).resolve(
            runtime_variant=variant,
            python_version=python_version,
            profile_requirement=profile_requirement,
            deployment_profile_policy_sha256=deployment_profile_policy_sha256,
        )

    def copy(self) -> dict:
        return copy.deepcopy({"manifest": self.manifest, "record": self.record, "binding": self.binding})
