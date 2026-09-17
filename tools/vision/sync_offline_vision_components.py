#!/usr/bin/env python3
"""Synchronize reusable Vision Runtime/Model packs into an offline component store.

The component store lives inside (or beside) MAVI-Offline-Binary-Kit and is
content-addressed by stable Runtime Pack / Model Pack IDs. Re-running the
synchronizer with a pack assembled from another application commit reuses the
existing heavy bytes when the material component identity is unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

RUNTIME_SCHEMA = "mavi-vision-runtime-pack-v2"
MODEL_SCHEMA = "mavi-vision-model-pack-v1"
REQUIREMENTS_SCHEMA = "mavi-vision-component-requirements-v1"
INVENTORY_SCHEMA = "mavi-offline-vision-component-inventory-v1"
RUNTIME_ID_RE = re.compile(r"^mavi-runtime-v2-[0-9a-f]{64}$")
MODEL_ID_RE = re.compile(r"^mavi-model-v1-[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VisionComponentStoreError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisionComponentStoreError(f"json_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise VisionComponentStoreError(f"json_object_required:{path}")
    return value


def _safe_relative(value: object) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\\" in value
        or "\x00" in value
    ):
        raise VisionComponentStoreError("component_artifact_path_invalid")
    logical = PurePosixPath(value)
    parts = value.split("/")
    if (
        logical.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or ":" in parts[0]
    ):
        raise VisionComponentStoreError("component_artifact_path_invalid")
    return logical


def _material_fingerprint(
    manifest: dict[str, object], *, kind: str
) -> dict[str, object]:
    if kind == "runtime":
        keys = (
            "runtimePackId",
            "platformVariant",
            "pythonVersion",
            "nativeAbi",
            "thirdPartyLockSha256",
            "runtimeRequirementsSha256",
        )
    elif kind == "model":
        keys = ("modelPackId", "modelId", "checkpointSha256", "resolvedConfigSha256")
    else:
        raise AssertionError(kind)
    result = {key: manifest.get(key) for key in keys}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise VisionComponentStoreError("component_artifacts_missing")
    normalized = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise VisionComponentStoreError("component_artifact_invalid")
        normalized.append(
            {
                "relativePath": item.get("relativePath"),
                "sizeBytes": item.get("sizeBytes"),
                "sha256": item.get("sha256"),
            }
        )
    result["artifacts"] = sorted(
        normalized, key=lambda item: str(item["relativePath"])
    )
    return result


def _validate_component(
    root: Path, manifest_name: str, *, kind: str
) -> dict[str, object]:
    if not root.is_dir() or root.is_symlink():
        raise VisionComponentStoreError("component_root_invalid")
    for entry in root.rglob("*"):
        if entry.is_symlink():
            raise VisionComponentStoreError("component_symlink_forbidden")

    manifest_path = root / manifest_name
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise VisionComponentStoreError("component_manifest_missing")
    manifest = _load_json(manifest_path)
    schema = manifest.get("schemaVersion")
    if kind == "runtime":
        if schema != RUNTIME_SCHEMA or not RUNTIME_ID_RE.fullmatch(
            str(manifest.get("runtimePackId", ""))
        ):
            raise VisionComponentStoreError("runtime_manifest_invalid")
    else:
        if schema != MODEL_SCHEMA or not MODEL_ID_RE.fullmatch(
            str(manifest.get("modelPackId", ""))
        ):
            raise VisionComponentStoreError("model_manifest_invalid")

    declared: set[str] = set()
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise VisionComponentStoreError("component_artifacts_missing")
    for item in artifacts:
        if not isinstance(item, dict):
            raise VisionComponentStoreError("component_artifact_invalid")
        logical = _safe_relative(item.get("relativePath"))
        relative = logical.as_posix()
        if relative in declared:
            raise VisionComponentStoreError("component_artifact_duplicate")
        declared.add(relative)
        sha = item.get("sha256")
        size = item.get("sizeBytes")
        if (
            not isinstance(sha, str)
            or not SHA256_RE.fullmatch(sha)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise VisionComponentStoreError("component_artifact_invalid")
        path = root.joinpath(*logical.parts)
        if not path.is_file() or path.is_symlink():
            raise VisionComponentStoreError("component_artifact_missing")
        if path.stat().st_size != size or _sha256(path) != sha:
            raise VisionComponentStoreError("component_artifact_mismatch")

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != manifest_name
    }
    if actual != declared:
        raise VisionComponentStoreError("component_artifact_set_mismatch")
    return manifest


def _sync_component(
    source: Path, target: Path, manifest_name: str, *, kind: str
) -> tuple[dict[str, object], bool]:
    source_manifest = _validate_component(source, manifest_name, kind=kind)
    if target.exists():
        target_manifest = _validate_component(target, manifest_name, kind=kind)
        if _material_fingerprint(target_manifest, kind=kind) != _material_fingerprint(
            source_manifest, kind=kind
        ):
            raise VisionComponentStoreError("component_id_collision")
        return target_manifest, True

    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    published = False
    try:
        for child in source.iterdir():
            destination = stage / child.name
            if child.is_symlink():
                raise VisionComponentStoreError("component_symlink_forbidden")
            if child.is_dir():
                shutil.copytree(child, destination, symlinks=False)
            elif child.is_file():
                shutil.copy2(child, destination)
            else:
                raise VisionComponentStoreError("component_entry_invalid")
        copied_manifest = _validate_component(stage, manifest_name, kind=kind)
        if _material_fingerprint(copied_manifest, kind=kind) != _material_fingerprint(
            source_manifest, kind=kind
        ):
            raise VisionComponentStoreError("component_copy_mismatch")
        os.replace(stage, target)
        published = True
        return copied_manifest, False
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def sync_vision_components(
    *,
    kit_root: Path,
    runtime_pack_root: Path,
    model_pack_root: Path,
    component_requirements_path: Path,
    application_revision: str,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", application_revision):
        raise VisionComponentStoreError("application_revision_invalid")
    if kit_root.exists() and (not kit_root.is_dir() or kit_root.is_symlink()):
        raise VisionComponentStoreError("kit_root_invalid")
    kit_root.mkdir(parents=True, exist_ok=True)

    requirements = _load_json(component_requirements_path)
    if requirements.get("schemaVersion") != REQUIREMENTS_SCHEMA:
        raise VisionComponentStoreError("component_requirements_schema_invalid")
    runtime_packs = requirements.get("runtimePacks")
    model_required = requirements.get("modelPack")
    if not isinstance(runtime_packs, dict) or not isinstance(model_required, dict):
        raise VisionComponentStoreError("component_requirements_incomplete")
    runtime_required = runtime_packs.get("windows-x86_64-cpu")
    if not isinstance(runtime_required, dict):
        raise VisionComponentStoreError("component_requirements_incomplete")

    source_runtime = _validate_component(
        runtime_pack_root, "runtime-pack-manifest.json", kind="runtime"
    )
    source_model = _validate_component(
        model_pack_root, "model-pack-manifest.json", kind="model"
    )
    for key in (
        "runtimePackId",
        "thirdPartyLockSha256",
        "runtimeRequirementsSha256",
        "nativeAbi",
    ):
        if source_runtime.get(key) != runtime_required.get(key):
            raise VisionComponentStoreError(f"runtime_requirement_mismatch:{key}")
    for key in (
        "modelPackId",
        "modelId",
        "checkpointSha256",
        "resolvedConfigSha256",
    ):
        if source_model.get(key) != model_required.get(key):
            raise VisionComponentStoreError(f"model_requirement_mismatch:{key}")

    runtime_id = str(source_runtime["runtimePackId"])
    model_id = str(source_model["modelPackId"])
    runtime_target = kit_root / "vision" / "runtime" / runtime_id
    model_target = kit_root / "vision" / "models" / model_id
    stored_runtime, runtime_reused = _sync_component(
        runtime_pack_root,
        runtime_target,
        "runtime-pack-manifest.json",
        kind="runtime",
    )
    stored_model, model_reused = _sync_component(
        model_pack_root, model_target, "model-pack-manifest.json", kind="model"
    )

    inventory = {
        "schemaVersion": INVENTORY_SCHEMA,
        "runtimePack": {
            "runtimePackId": runtime_id,
            "relativePath": runtime_target.relative_to(kit_root).as_posix(),
            "materialIdentity": _material_fingerprint(stored_runtime, kind="runtime"),
        },
        "modelPack": {
            "modelPackId": model_id,
            "relativePath": model_target.relative_to(kit_root).as_posix(),
            "materialIdentity": _material_fingerprint(stored_model, kind="model"),
        },
        "applicationOverlay": {
            "revision": application_revision,
            "componentRequirements": component_requirements_path.name,
            "componentRequirementsSha256": _sha256(component_requirements_path),
        },
    }
    inventory_path = kit_root / "vision" / "component-inventory.json"
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    stage_inventory = inventory_path.with_name(
        f".{inventory_path.name}.{os.getpid()}.tmp"
    )
    stage_inventory.write_text(
        json.dumps(inventory, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(stage_inventory, inventory_path)
    return {
        **inventory,
        "runtimeReused": runtime_reused,
        "modelReused": model_reused,
    }


def verify_vision_component_store(kit_root: Path) -> dict[str, object]:
    if not kit_root.is_dir() or kit_root.is_symlink():
        raise VisionComponentStoreError("kit_root_invalid")
    inventory_path = kit_root / "vision" / "component-inventory.json"
    if inventory_path.is_symlink():
        raise VisionComponentStoreError("component_inventory_symlink_forbidden")
    inventory = _load_json(inventory_path)
    if inventory.get("schemaVersion") != INVENTORY_SCHEMA:
        raise VisionComponentStoreError("component_inventory_schema_invalid")
    runtime = inventory.get("runtimePack")
    model = inventory.get("modelPack")
    overlay = inventory.get("applicationOverlay")
    if (
        not isinstance(runtime, dict)
        or not isinstance(model, dict)
        or not isinstance(overlay, dict)
    ):
        raise VisionComponentStoreError("component_inventory_incomplete")

    runtime_relative = _safe_relative(runtime.get("relativePath"))
    model_relative = _safe_relative(model.get("relativePath"))
    runtime_root = kit_root.joinpath(*runtime_relative.parts)
    model_root = kit_root.joinpath(*model_relative.parts)
    runtime_manifest = _validate_component(
        runtime_root, "runtime-pack-manifest.json", kind="runtime"
    )
    model_manifest = _validate_component(
        model_root, "model-pack-manifest.json", kind="model"
    )
    if _material_fingerprint(runtime_manifest, kind="runtime") != runtime.get(
        "materialIdentity"
    ):
        raise VisionComponentStoreError("runtime_inventory_mismatch")
    if _material_fingerprint(model_manifest, kind="model") != model.get(
        "materialIdentity"
    ):
        raise VisionComponentStoreError("model_inventory_mismatch")
    if runtime_manifest.get("runtimePackId") != runtime.get("runtimePackId"):
        raise VisionComponentStoreError("runtime_inventory_id_mismatch")
    if model_manifest.get("modelPackId") != model.get("modelPackId"):
        raise VisionComponentStoreError("model_inventory_id_mismatch")
    revision = overlay.get("revision")
    sha = overlay.get("componentRequirementsSha256")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise VisionComponentStoreError("application_inventory_revision_invalid")
    if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
        raise VisionComponentStoreError("application_inventory_requirements_invalid")
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--kit-root", type=Path, required=True)
    sync.add_argument("--runtime-pack", type=Path, required=True)
    sync.add_argument("--model-pack", type=Path, required=True)
    sync.add_argument("--component-requirements", type=Path, required=True)
    sync.add_argument("--application-revision", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--kit-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "sync":
            result = sync_vision_components(
                kit_root=args.kit_root,
                runtime_pack_root=args.runtime_pack,
                model_pack_root=args.model_pack,
                component_requirements_path=args.component_requirements,
                application_revision=args.application_revision,
            )
        else:
            result = verify_vision_component_store(args.kit_root)
    except VisionComponentStoreError as exc:
        print(str(exc), file=os.sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
