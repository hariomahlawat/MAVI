#!/usr/bin/env python3
"""Synchronize reusable Vision Runtime/Model packs into an offline component store.

The component store lives inside (or beside) MAVI-Offline-Binary-Kit and is
content-addressed by stable Runtime Pack / Model Pack IDs. Re-running the
synchronizer with a pack assembled from another application commit reuses the
existing heavy bytes when the material component identity is unchanged.

Since S2a.3 the store is described by the component binding v2 (plan §7): any
number of Runtime Packs and Model Packs, and a kit is complete only when every
id the binding reaches for the synchronized variants is present
(``kit_incomplete:<id>``) and nothing unbound is (``kit_unbound_component:<id>``).

``plan`` is the Setup preflight (S2a.4): from the repository binding it names the
Runtime Pack and every enabled Model Pack a role needs on one variant and, given a
kit, checks the kit against that binding and returns each pack's source by id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath

VISION_ROOT = Path(__file__).resolve().parents[2] / "src" / "vision"
if str(VISION_ROOT) not in sys.path:
    sys.path.insert(0, str(VISION_ROOT))

from mavi_vision.runtime.binding import ComponentBindingV2, load_component_binding  # noqa: E402
from mavi_vision.runtime.manifest import ReleaseMetadataError  # noqa: E402

RUNTIME_SCHEMA = "mavi-vision-runtime-pack-v2"
MODEL_SCHEMA = "mavi-vision-model-pack-v2"
INVENTORY_SCHEMA = "mavi-offline-vision-component-inventory-v2"
RUNTIME_ID_RE = re.compile(r"^mavi-runtime-v2-[0-9a-f]{64}$")
MODEL_ID_RE = re.compile(r"^mavi-model-v2-[0-9a-f]{64}$")
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
        keys = ("modelPackId", "modelId", "modelVersion", "capabilityIds")
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
        entry = {
            "relativePath": item.get("relativePath"),
            "sizeBytes": item.get("sizeBytes"),
            "sha256": item.get("sha256"),
        }
        if kind == "model":
            entry["artifactRole"] = item.get("artifactRole")
        normalized.append(entry)
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


def _binding_requirements(
    binding: ComponentBindingV2,
    *,
    variants: set[str],
) -> tuple[dict[str, dict[str, object]], set[str]]:
    """Every Runtime Pack (by id) and Model Pack id the binding reaches for ``variants``."""
    runtime_required: dict[str, dict[str, object]] = {}
    model_required: set[str] = set()
    for role in binding.roles.values():
        family_variants = binding.family_variants(role.runtime_pack_family_id)
        reached = False
        for variant in sorted(variants):
            entry = family_variants.get(variant)
            if entry is None:
                continue
            reached = True
            runtime_required[entry.runtime_pack_id] = {
                "platformVariant": variant,
                "thirdPartyLockSha256": entry.third_party_lock_sha256,
                "runtimeRequirementsSha256": entry.runtime_requirements_sha256,
                "nativeAbi": entry.native_abi,
            }
        if reached:
            for capability_binding in binding.bindings_for_role(role.role_id):
                if capability_binding.enabled:
                    model_required.add(capability_binding.model_pack_id)
    for variant in sorted(variants):
        if not any(variant in binding.family_variants(role.runtime_pack_family_id) for role in binding.roles.values()):
            raise VisionComponentStoreError(f"kit_variant_not_bound:{variant}")
    return runtime_required, model_required


def sync_vision_components(
    *,
    kit_root: Path,
    runtime_pack_roots: list[Path],
    model_pack_roots: list[Path],
    component_binding_path: Path,
    application_revision: str,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", application_revision):
        raise VisionComponentStoreError("application_revision_invalid")
    if kit_root.exists() and (not kit_root.is_dir() or kit_root.is_symlink()):
        raise VisionComponentStoreError("kit_root_invalid")
    try:
        binding = load_component_binding(component_binding_path)
    except ReleaseMetadataError as exc:
        raise VisionComponentStoreError(f"component_binding_invalid:{exc.code}") from exc

    sources_runtime = [
        (root, _validate_component(root, "runtime-pack-manifest.json", kind="runtime"))
        for root in runtime_pack_roots
    ]
    sources_model = [
        (root, _validate_component(root, "model-pack-manifest.json", kind="model"))
        for root in model_pack_roots
    ]
    variants = {str(manifest.get("platformVariant")) for _, manifest in sources_runtime}
    runtime_required, model_required = _binding_requirements(binding, variants=variants)

    runtime_ids = [str(manifest["runtimePackId"]) for _, manifest in sources_runtime]
    model_ids = [str(manifest["modelPackId"]) for _, manifest in sources_model]
    for identifier in sorted(set(runtime_ids) | set(model_ids)):
        if identifier not in runtime_required and identifier not in model_required:
            raise VisionComponentStoreError(f"kit_unbound_component:{identifier}")
    for identifier in sorted(set(runtime_required) | model_required):
        if identifier not in runtime_ids and identifier not in model_ids:
            raise VisionComponentStoreError(f"kit_incomplete:{identifier}")
    if len(set(runtime_ids)) != len(runtime_ids) or len(set(model_ids)) != len(model_ids):
        raise VisionComponentStoreError("kit_component_duplicate")
    for _, manifest in sources_runtime:
        required = runtime_required[str(manifest["runtimePackId"])]
        for key, value in required.items():
            if manifest.get(key) != value:
                raise VisionComponentStoreError(f"runtime_requirement_mismatch:{key}")

    kit_root.mkdir(parents=True, exist_ok=True)
    runtime_entries: list[dict[str, object]] = []
    model_entries: list[dict[str, object]] = []
    reused: dict[str, bool] = {}
    for root, manifest in sorted(sources_runtime, key=lambda item: str(item[1]["runtimePackId"])):
        runtime_id = str(manifest["runtimePackId"])
        target = kit_root / "vision" / "runtime" / runtime_id
        stored, was_reused = _sync_component(root, target, "runtime-pack-manifest.json", kind="runtime")
        reused[runtime_id] = was_reused
        runtime_entries.append(
            {
                "runtimePackId": runtime_id,
                "platformVariant": stored.get("platformVariant"),
                "relativePath": target.relative_to(kit_root).as_posix(),
                "materialIdentity": _material_fingerprint(stored, kind="runtime"),
            }
        )
    for root, manifest in sorted(sources_model, key=lambda item: str(item[1]["modelPackId"])):
        model_id = str(manifest["modelPackId"])
        target = kit_root / "vision" / "models" / model_id
        stored, was_reused = _sync_component(root, target, "model-pack-manifest.json", kind="model")
        reused[model_id] = was_reused
        model_entries.append(
            {
                "modelPackId": model_id,
                "relativePath": target.relative_to(kit_root).as_posix(),
                "materialIdentity": _material_fingerprint(stored, kind="model"),
            }
        )

    inventory = {
        "schemaVersion": INVENTORY_SCHEMA,
        "runtimePacks": runtime_entries,
        "modelPacks": model_entries,
        "applicationOverlay": {
            "revision": application_revision,
            "componentBinding": component_binding_path.name,
            "componentBindingSha256": binding.component_binding_sha256,
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
    return {**inventory, "reused": reused}


def verify_vision_component_store(kit_root: Path) -> dict[str, object]:
    if not kit_root.is_dir() or kit_root.is_symlink():
        raise VisionComponentStoreError("kit_root_invalid")
    inventory_path = kit_root / "vision" / "component-inventory.json"
    if inventory_path.is_symlink():
        raise VisionComponentStoreError("component_inventory_symlink_forbidden")
    inventory = _load_json(inventory_path)
    if inventory.get("schemaVersion") != INVENTORY_SCHEMA:
        # A v1 inventory is refused, never read (no dual reader).
        raise VisionComponentStoreError("component_inventory_schema_invalid")
    runtimes = inventory.get("runtimePacks")
    models = inventory.get("modelPacks")
    overlay = inventory.get("applicationOverlay")
    if (
        not isinstance(runtimes, list)
        or not isinstance(models, list)
        or not runtimes
        or not models
        or not isinstance(overlay, dict)
    ):
        raise VisionComponentStoreError("component_inventory_incomplete")

    for entries, kind, manifest_name, id_key in (
        (runtimes, "runtime", "runtime-pack-manifest.json", "runtimePackId"),
        (models, "model", "model-pack-manifest.json", "modelPackId"),
    ):
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise VisionComponentStoreError("component_inventory_incomplete")
            relative = _safe_relative(entry.get("relativePath"))
            manifest = _validate_component(kit_root.joinpath(*relative.parts), manifest_name, kind=kind)
            if _material_fingerprint(manifest, kind=kind) != entry.get("materialIdentity"):
                raise VisionComponentStoreError(f"{kind}_inventory_mismatch")
            if manifest.get(id_key) != entry.get(id_key):
                raise VisionComponentStoreError(f"{kind}_inventory_id_mismatch")
            if str(entry.get(id_key)) in seen:
                raise VisionComponentStoreError("kit_component_duplicate")
            seen.add(str(entry.get(id_key)))
    revision = overlay.get("revision")
    sha = overlay.get("componentBindingSha256")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise VisionComponentStoreError("application_inventory_revision_invalid")
    if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
        raise VisionComponentStoreError("application_inventory_binding_invalid")
    return inventory


def _role_requirements(
    binding: ComponentBindingV2, *, role_id: str, variant: str
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """The Runtime Pack of ``variant`` and every enabled Model Pack of ``role_id``."""
    try:
        role = binding.role(role_id)
        family_variants = binding.family_variants(role.runtime_pack_family_id)
    except ReleaseMetadataError as exc:
        raise VisionComponentStoreError(f"component_binding_invalid:{exc.code}") from exc
    entry = family_variants.get(variant)
    if entry is None:
        raise VisionComponentStoreError(f"kit_variant_not_bound:{variant}")
    runtime = {
        "platformVariant": variant,
        "runtimePackId": entry.runtime_pack_id,
        "thirdPartyLockSha256": entry.third_party_lock_sha256,
        "runtimeRequirementsSha256": entry.runtime_requirements_sha256,
        "nativeAbi": entry.native_abi,
    }
    capabilities: dict[str, list[str]] = {}
    for capability_binding in binding.bindings_for_role(role_id):
        if capability_binding.enabled:
            capabilities.setdefault(capability_binding.model_pack_id, []).append(capability_binding.capability_id)
    models = [
        {"modelPackId": model_pack_id, "capabilityIds": sorted(capabilities[model_pack_id])}
        for model_pack_id in sorted(capabilities)
    ]
    return runtime, models


def _bound_component_ids(binding: ComponentBindingV2) -> set[str]:
    """Every Runtime Pack and enabled Model Pack id the binding reaches for any role and variant."""
    bound: set[str] = set()
    for role in binding.roles.values():
        bound.update(entry.runtime_pack_id for entry in binding.family_variants(role.runtime_pack_family_id).values())
        bound.update(
            capability_binding.model_pack_id
            for capability_binding in binding.bindings_for_role(role.role_id)
            if capability_binding.enabled
        )
    return bound


def plan_vision_components(
    *,
    component_binding_path: Path,
    role_id: str,
    variant: str,
    optional_variants: list[str] | None = None,
    kit_root: Path | None = None,
) -> dict[str, object]:
    """What Setup must install for ``role_id`` on ``variant``, decided before any installation.

    The requirement comes from the validated repository binding alone. With a
    ``kit_root`` the kit must pass ``verify_vision_component_store`` and match
    that binding: the inventory's binding SHA-256 must be the repository
    binding's (``kit_binding_mismatch``), every required pack must be in the
    inventory (``kit_incomplete:<id>``) and nothing unbound may be
    (``kit_unbound_component:<id>``). Each source is the inventory entry of the
    required id, never a directory found by scanning.

    ``applicationOverlay.revision`` is reported as provenance only: a kit
    assembled at another application commit stays usable while the binding is
    the same, because the binding, not the commit, is the composition identity.
    """
    try:
        binding = load_component_binding(component_binding_path)
    except ReleaseMetadataError as exc:
        raise VisionComponentStoreError(f"component_binding_invalid:{exc.code}") from exc
    runtime, models = _role_requirements(binding, role_id=role_id, variant=variant)
    optional: list[dict[str, object]] = []
    for name in sorted(set(optional_variants or ()) - {variant}):
        try:
            optional.append(_role_requirements(binding, role_id=role_id, variant=name)[0])
        except VisionComponentStoreError:
            # An optional variant the binding does not declare is simply not offered.
            continue

    result: dict[str, object] = {
        "componentBinding": component_binding_path.name,
        "componentBindingSha256": binding.component_binding_sha256,
        "roleId": role_id,
        "runtimePack": runtime,
        "modelPacks": models,
        "optionalRuntimePacks": optional,
        "kit": None,
    }
    if kit_root is None:
        return result

    inventory = verify_vision_component_store(kit_root)
    overlay = inventory["applicationOverlay"]
    assert isinstance(overlay, dict)
    if (
        overlay.get("componentBindingSha256") != binding.component_binding_sha256
        or overlay.get("componentBinding") != component_binding_path.name
    ):
        raise VisionComponentStoreError("kit_binding_mismatch")

    runtimes = {str(entry["runtimePackId"]): entry for entry in inventory["runtimePacks"]}  # type: ignore[index,union-attr]
    stored_models = {str(entry["modelPackId"]): entry for entry in inventory["modelPacks"]}  # type: ignore[index,union-attr]
    bound = _bound_component_ids(binding)
    for identifier in sorted(set(runtimes) | set(stored_models)):
        if identifier not in bound:
            raise VisionComponentStoreError(f"kit_unbound_component:{identifier}")

    def runtime_source(required: dict[str, object]) -> dict[str, object] | None:
        entry = runtimes.get(str(required["runtimePackId"]))
        if entry is None:
            return None
        material = entry.get("materialIdentity")
        if entry.get("platformVariant") != required["platformVariant"] or not isinstance(material, dict):
            raise VisionComponentStoreError("runtime_requirement_mismatch:platformVariant")
        for key in ("platformVariant", "thirdPartyLockSha256", "runtimeRequirementsSha256", "nativeAbi"):
            if material.get(key) != required[key]:
                raise VisionComponentStoreError(f"runtime_requirement_mismatch:{key}")
        return {**required, "sourceRoot": str(kit_root.joinpath(*PurePosixPath(str(entry["relativePath"])).parts))}

    runtime_selected = runtime_source(runtime)
    if runtime_selected is None:
        raise VisionComponentStoreError(f"kit_incomplete:{runtime['runtimePackId']}")
    models_selected = []
    for required in models:
        entry = stored_models.get(str(required["modelPackId"]))
        if entry is None:
            raise VisionComponentStoreError(f"kit_incomplete:{required['modelPackId']}")
        models_selected.append(
            {**required, "sourceRoot": str(kit_root.joinpath(*PurePosixPath(str(entry["relativePath"])).parts))}
        )
    optional_selected = [item for item in (runtime_source(required) for required in optional) if item is not None]
    result["kit"] = {
        "kitRoot": str(kit_root),
        "applicationRevision": overlay["revision"],
        "runtimePack": runtime_selected,
        "modelPacks": models_selected,
        "optionalRuntimePacks": optional_selected,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--kit-root", type=Path, required=True)
    sync.add_argument("--runtime-pack", type=Path, action="append", required=True)
    sync.add_argument("--model-pack", type=Path, action="append", required=True)
    sync.add_argument("--component-binding", type=Path, required=True)
    sync.add_argument("--application-revision", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--kit-root", type=Path, required=True)
    plan = sub.add_parser("plan", help="Setup preflight: what to install for a role, checked against the binding")
    plan.add_argument("--component-binding", type=Path, required=True)
    plan.add_argument("--role", default="vision")
    plan.add_argument("--variant", required=True)
    plan.add_argument("--optional-variant", action="append", default=[])
    plan.add_argument("--kit-root", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = plan_vision_components(
                component_binding_path=args.component_binding,
                role_id=args.role,
                variant=args.variant,
                optional_variants=args.optional_variant,
                kit_root=args.kit_root,
            )
        elif args.command == "sync":
            result = sync_vision_components(
                kit_root=args.kit_root,
                runtime_pack_roots=args.runtime_pack,
                model_pack_roots=args.model_pack,
                component_binding_path=args.component_binding,
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
