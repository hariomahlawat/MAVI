#!/usr/bin/env python3
"""Verify strict ownership boundaries in the offline Vision component store."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

INVENTORY_SCHEMA = "mavi-offline-vision-component-inventory-v2"
RUNTIME_SCHEMA = "mavi-vision-runtime-pack-v2"
MODEL_SCHEMA = "mavi-vision-model-pack-v2"
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
    """Every pack in its own place, no artefact bytes shared between any two packs.

    Since S2a.3 a kit holds any number of Runtime Packs and Model Packs (plan
    §7); the ownership boundary is pairwise across all of them, and the
    Application Overlay inventory carries binding metadata only.
    """
    if not kit_root.is_dir() or kit_root.is_symlink():
        raise ComponentOwnershipError("kit_root_invalid")
    inventory = _load_json(kit_root / "vision" / "component-inventory.json")
    if inventory.get("schemaVersion") != INVENTORY_SCHEMA:
        raise ComponentOwnershipError("component_inventory_schema_invalid")
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
        raise ComponentOwnershipError("component_inventory_incomplete")

    owners: dict[str, str] = {}
    counts: dict[str, int] = {"runtime": 0, "model": 0}
    identities: dict[str, list[str]] = {"runtime": [], "model": []}
    for entries, kind, folder, manifest_name, id_key, schema in (
        (runtimes, "runtime", "runtime", "runtime-pack-manifest.json", "runtimePackId", RUNTIME_SCHEMA),
        (models, "model", "models", "model-pack-manifest.json", "modelPackId", MODEL_SCHEMA),
    ):
        for entry in entries:
            if not isinstance(entry, dict):
                raise ComponentOwnershipError("component_inventory_incomplete")
            identifier = entry.get(id_key)
            relative = _safe_relative(entry.get("relativePath"))
            if relative.parts != ("vision", folder, str(identifier)):
                raise ComponentOwnershipError(f"{kind}_component_location_invalid")
            manifest = _load_json(kit_root.joinpath(*relative.parts) / manifest_name)
            if manifest.get("schemaVersion") != schema or manifest.get(id_key) != identifier:
                raise ComponentOwnershipError(f"{kind}_component_identity_invalid")
            hashes = _artifact_hashes(manifest, kind=kind)
            counts[kind] += len(hashes)
            identities[kind].append(str(identifier))
            for path, sha in hashes.items():
                owner = f"{kind}:{identifier}:{path}"
                previous = owners.get(sha)
                if previous is not None and previous.split(":", 2)[:2] != owner.split(":", 2)[:2]:
                    raise ComponentOwnershipError(f"cross_component_artifact_duplicate:{sha}:{previous}:{owner}")
                owners.setdefault(sha, owner)

    expected_overlay_keys = {"revision", "componentBinding", "componentBindingSha256"}
    if set(overlay) != expected_overlay_keys:
        raise ComponentOwnershipError("application_overlay_inventory_boundary_invalid")
    revision = overlay.get("revision")
    binding_name = overlay.get("componentBinding")
    binding_sha = overlay.get("componentBindingSha256")
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise ComponentOwnershipError("application_overlay_revision_invalid")
    if (
        not isinstance(binding_name, str)
        or not binding_name
        or PurePosixPath(binding_name).name != binding_name
        or "\\" in binding_name
    ):
        raise ComponentOwnershipError("application_overlay_binding_name_invalid")
    if not isinstance(binding_sha, str) or not SHA256_RE.fullmatch(binding_sha):
        raise ComponentOwnershipError("application_overlay_binding_sha_invalid")

    return {
        "schemaVersion": "mavi-offline-vision-component-ownership-v2",
        "runtimePackIds": sorted(identities["runtime"]),
        "modelPackIds": sorted(identities["model"]),
        "runtimeArtifactCount": counts["runtime"],
        "modelArtifactCount": counts["model"],
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
