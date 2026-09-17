#!/usr/bin/env python3
"""Verify strict ownership boundaries in the offline Vision component store."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

INVENTORY_SCHEMA = "mavi-offline-vision-component-inventory-v1"
RUNTIME_SCHEMA = "mavi-vision-runtime-pack-v2"
MODEL_SCHEMA = "mavi-vision-model-pack-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class ComponentOwnershipError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComponentOwnershipError(f"json_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise ComponentOwnershipError(f"json_object_required:{path}")
    return value


def _safe_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or value != value.strip() or "\\" in value or "\x00" in value:
        raise ComponentOwnershipError("component_path_invalid")
    path = PurePosixPath(value)
    parts = value.split("/")
    if path.is_absolute() or any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
        raise ComponentOwnershipError("component_path_invalid")
    return path


def _artifact_hashes(manifest: dict[str, object], *, kind: str) -> dict[str, str]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ComponentOwnershipError(f"{kind}_artifacts_missing")
    result: dict[str, str] = {}
    for item in artifacts:
        if not isinstance(item, dict):
            raise ComponentOwnershipError(f"{kind}_artifact_invalid")
        relative = _safe_relative(item.get("relativePath")).as_posix()
        sha = item.get("sha256")
        if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
            raise ComponentOwnershipError(f"{kind}_artifact_invalid")
        if relative in result:
            raise ComponentOwnershipError(f"{kind}_artifact_duplicate_path")
        result[relative] = sha
    return result


def verify_component_ownership(kit_root: Path) -> dict[str, object]:
    if not kit_root.is_dir() or kit_root.is_symlink():
        raise ComponentOwnershipError("kit_root_invalid")
    inventory = _load_json(kit_root / "vision" / "component-inventory.json")
    if inventory.get("schemaVersion") != INVENTORY_SCHEMA:
        raise ComponentOwnershipError("component_inventory_schema_invalid")
    runtime = inventory.get("runtimePack")
    model = inventory.get("modelPack")
    overlay = inventory.get("applicationOverlay")
    if not isinstance(runtime, dict) or not isinstance(model, dict) or not isinstance(overlay, dict):
        raise ComponentOwnershipError("component_inventory_incomplete")

    runtime_id = runtime.get("runtimePackId")
    model_id = model.get("modelPackId")
    runtime_relative = _safe_relative(runtime.get("relativePath"))
    model_relative = _safe_relative(model.get("relativePath"))
    if runtime_relative.parts != ("vision", "runtime", str(runtime_id)):
        raise ComponentOwnershipError("runtime_component_location_invalid")
    if model_relative.parts != ("vision", "models", str(model_id)):
        raise ComponentOwnershipError("model_component_location_invalid")

    runtime_manifest = _load_json(kit_root.joinpath(*runtime_relative.parts) / "runtime-pack-manifest.json")
    model_manifest = _load_json(kit_root.joinpath(*model_relative.parts) / "model-pack-manifest.json")
    if runtime_manifest.get("schemaVersion") != RUNTIME_SCHEMA or runtime_manifest.get("runtimePackId") != runtime_id:
        raise ComponentOwnershipError("runtime_component_identity_invalid")
    if model_manifest.get("schemaVersion") != MODEL_SCHEMA or model_manifest.get("modelPackId") != model_id:
        raise ComponentOwnershipError("model_component_identity_invalid")

    runtime_hashes = _artifact_hashes(runtime_manifest, kind="runtime")
    model_hashes = _artifact_hashes(model_manifest, kind="model")
    runtime_by_hash = {sha: path for path, sha in runtime_hashes.items()}
    for model_path, sha in model_hashes.items():
        runtime_path = runtime_by_hash.get(sha)
        if runtime_path is not None:
            raise ComponentOwnershipError(
                f"cross_component_artifact_duplicate:{sha}:runtime={runtime_path}:model={model_path}"
            )

    expected_overlay_keys = {"revision", "componentRequirements", "componentRequirementsSha256"}
    if set(overlay) != expected_overlay_keys:
        raise ComponentOwnershipError("application_overlay_inventory_boundary_invalid")
    revision = overlay.get("revision")
    requirements_name = overlay.get("componentRequirements")
    requirements_sha = overlay.get("componentRequirementsSha256")
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise ComponentOwnershipError("application_overlay_revision_invalid")
    if (
        not isinstance(requirements_name, str)
        or not requirements_name
        or PurePosixPath(requirements_name).name != requirements_name
        or "\\" in requirements_name
    ):
        raise ComponentOwnershipError("application_overlay_requirements_name_invalid")
    if not isinstance(requirements_sha, str) or not SHA256_RE.fullmatch(requirements_sha):
        raise ComponentOwnershipError("application_overlay_requirements_sha_invalid")

    return {
        "schemaVersion": "mavi-offline-vision-component-ownership-v1",
        "runtimePackId": runtime_id,
        "modelPackId": model_id,
        "runtimeArtifactCount": len(runtime_hashes),
        "modelArtifactCount": len(model_hashes),
        "crossComponentDuplicates": 0,
        "applicationRevision": revision,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_component_ownership(args.kit_root)
    except ComponentOwnershipError as exc:
        print(str(exc))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
