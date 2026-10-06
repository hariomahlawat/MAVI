"""Development producers (ADR-014 2026-10-06 note) added to the resolver and verify_repo overlays.

``add_development_producer`` turns an ``Overlay`` (resolver paths) or a
``RepositoryOverlay`` (the repository paths ``verify_repo`` reads) into one with
the A2 Development profile, a Development qualification record and a Development
replacement binding of ``vision``/``detector``, pinned by a producer registry to
the overlay's own release binding. Every identity is derived from bytes, as the
base overlays derive theirs; a test then breaks one relationship.

For the resolver ``Overlay`` (whose binding and profile live at fixed paths) the
overlay *becomes* the producer: its binding, record and profile are replaced, so
``overlay.resolve()`` resolves the Development producer exactly as the worker would.
"""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from tests.component_binding_v2_fixtures import REPOSITORY
from tests.resolver_overlay import Overlay, RepositoryOverlay, _dump, sha256_bytes

A2_PROFILE = REPOSITORY / "src/vision/config/pipelines/phase1-detection-tracking-a2-v1.json"
A2_PROFILE_RELATIVE = "src/vision/config/pipelines/phase1-detection-tracking-a2-v1.json"
REGISTRY_RELATIVE = "src/vision/config/development-producers-v1.json"
RELEASE_BINDING_RELATIVE = "src/vision/config/components/phase1-bindings-v2.json"


def make_producer(overlay: Overlay, *, binding_id: str, qualification_id: str, scale1280: bool) -> None:
    """Make a resolver ``Overlay`` resolve as one Development producer (A2 profile, own record)."""
    shutil.copyfile(A2_PROFILE, overlay.pipeline_path)
    if scale1280:
        directory = "rtmdet-m-coco-phase1-scale1280-v1"
        overlay.manifest["modelVersion"] = "1.0.0-dev.scale1280"
        for item in overlay.manifest["artifacts"]:
            item["relativePath"] = directory + "/" + item["relativePath"].split("/", 1)[1]
        # A distinct resolved config (the real one differs from the base only in the test scale).
        overlay.artifacts["resolved-config"] = b"model = dict(type='RTMDet')\nload_from = None\ntest_scale = 1280\n"
    overlay.record["qualificationId"] = qualification_id
    overlay.record["policies"]["pipelineProfileId"] = "phase1-detection-tracking-a2"
    overlay.record.pop("supersedes", None)
    overlay.binding["bindingId"] = binding_id
    for item in overlay.binding["capabilityBindings"]:
        if item["capabilityId"] == "detector":
            item["qualificationId"] = qualification_id
    overlay.write()


@dataclass
class DevelopmentRepository:
    """A ``RepositoryOverlay`` plus one declared Development producer."""

    overlay: RepositoryOverlay
    record: dict
    binding: dict
    registry: dict

    @property
    def root(self) -> Path:
        return self.overlay.root

    @property
    def profile_path(self) -> Path:
        return self.root / A2_PROFILE_RELATIVE

    @property
    def record_path(self) -> Path:
        return self.root / "models/qualifications/rtmdet-m-coco-phase1-a2-test-dev-v1.json"

    @property
    def binding_path(self) -> Path:
        return self.root / "src/vision/config/components/development-phase1-a2-test-v1.json"

    @property
    def registry_path(self) -> Path:
        return self.root / REGISTRY_RELATIVE

    @classmethod
    def create(cls, tmp_path: Path) -> "DevelopmentRepository":
        overlay = RepositoryOverlay.create(tmp_path)
        overlay.pipeline_path.parent.mkdir(parents=True, exist_ok=True)
        repository = cls(overlay=overlay, record={}, binding={}, registry={})
        shutil.copyfile(A2_PROFILE, repository.profile_path)
        record = copy.deepcopy(overlay.record)
        record["qualificationId"] = "rtmdet-m-coco-phase1-a2-test-dev-v1"
        record["policies"] = {
            "pipelineProfileId": "phase1-detection-tracking-a2",
            "pipelineProfileSha256": sha256_bytes(repository.profile_path.read_bytes()),
        }
        record.pop("supersedes", None)
        binding = copy.deepcopy(overlay.binding)
        binding["bindingId"] = "development-phase1-a2-test-v1"
        for item in binding["capabilityBindings"]:
            if item["capabilityId"] == "detector":
                item["qualificationId"] = record["qualificationId"]
        repository.record, repository.binding = record, binding
        repository.registry = {
            "schemaVersion": "mavi-vision-development-producers-v1",
            "releaseBinding": {"path": RELEASE_BINDING_RELATIVE, "sha256": ""},
            "producers": [
                {
                    "producerId": "a2-test",
                    "bindingPath": "src/vision/config/components/development-phase1-a2-test-v1.json",
                    "pipelineProfilePath": A2_PROFILE_RELATIVE,
                    "replaces": [{"roleId": "vision", "capabilityId": "detector"}],
                }
            ],
        }
        repository.write()
        return repository

    def write(self, *, pin: bool = True) -> None:
        """Write the Development files; ``pin`` re-pins the registry to the release binding bytes."""
        _dump(self.record_path, self.record)
        _dump(self.binding_path, self.binding)
        if pin:
            self.registry["releaseBinding"]["sha256"] = sha256_bytes(self.overlay.binding_path.read_bytes())
        _dump(self.registry_path, self.registry)

    def tracked(self) -> list[Path]:
        return self.overlay.tracked()


def write_json(path: Path, document: dict) -> None:
    """LF bytes on every platform (``Path.write_text`` would write CRLF on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))
