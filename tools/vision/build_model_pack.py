#!/usr/bin/env python3
"""Build one content-addressed MAVI Vision Model Pack (``mavi-vision-model-pack-v2``).

The source is a v2 model manifest (``models/manifests/*.json``). Every declared
artefact, the licence notice included (plan P-15), is supplied by role,
re-hashed against the manifest and copied to its ``relativePath``; nothing the
manifest does not declare enters the pack. The ``modelPackId`` is derived from
the material inputs (plan P-3) by the one loader every consumer uses, and each
``sizeBytes`` is measured here, never authored (P-14).

Output layout (P-10), consumed by ``Install-MaviVisionModelPack.ps1`` v2::

    <output>/model-pack-manifest.json
    <output>/<packDirectory>/...        (every artefact at its relativePath)
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
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
if str(VISION_ROOT) not in sys.path:
    sys.path.insert(0, str(VISION_ROOT))

from mavi_vision.runtime.manifest import ReleaseMetadataError  # noqa: E402
from mavi_vision.runtime.model_manifest_v2 import (  # noqa: E402
    ModelManifestV2,
    load_model_manifest_v2,
)

MODEL_PACK_SCHEMA = "mavi-vision-model-pack-v2"
MODEL_PACK_MANIFEST = "model-pack-manifest.json"
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class ModelPackError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ModelPackArtifact:
    relativePath: str
    sizeBytes: int
    sha256: str
    artifactRole: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ModelPackError("model_pack_asset_unreadable") from exc
    return digest.hexdigest()


def _read_source_manifest(path: Path) -> ModelManifestV2:
    try:
        return load_model_manifest_v2(path)
    except ReleaseMetadataError as exc:
        # A v1 source manifest is refused here, never converted (plan §5: no dual reader).
        raise ModelPackError(f"model_pack_source_manifest_invalid:{exc.code}") from exc


def _copy_asset(stage: Path, source: Path, relative_path: str) -> Path:
    if not source.is_file() or source.is_symlink():
        raise ModelPackError("model_pack_asset_invalid")
    destination = stage.joinpath(*PurePosixPath(relative_path).parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ModelPackError("model_pack_duplicate_destination")
    shutil.copyfile(source, destination)
    return destination


def serialize_model_pack_manifest(manifest: dict[str, object]) -> bytes:
    return (json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def build_model_pack(
    *,
    source_manifest: Path,
    artifacts: dict[str, Path],
    assembled_from_commit: str,
    output: Path,
) -> dict[str, object]:
    """Build the pack, or fail with a stable code and leave no partial output."""
    if not _SHA1_RE.fullmatch(assembled_from_commit):
        raise ModelPackError("model_pack_source_commit_invalid")
    source = _read_source_manifest(source_manifest)
    declared = {artifact.artifact_role: artifact for artifact in source.artifacts}
    for role in sorted(set(declared) - set(artifacts)):
        raise ModelPackError(f"model_pack_artifact_missing:{role}")
    for role in sorted(set(artifacts) - set(declared)):
        raise ModelPackError(f"model_pack_artifact_undeclared:{role}")
    for role in sorted(declared):
        if _sha256(artifacts[role]) != declared[role].sha256:
            raise ModelPackError(f"model_pack_artifact_hash_mismatch:{role}")

    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ModelPackError("model_pack_destination_not_empty")
        preexisting_empty_output = True
    else:
        preexisting_empty_output = False
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    published = False
    try:
        built: list[ModelPackArtifact] = []
        for role in sorted(declared):
            item = declared[role]
            destination = _copy_asset(stage, artifacts[role], item.relative_path)
            # The copy is what ships: its bytes are hashed and measured, not the source's.
            if _sha256(destination) != item.sha256:
                raise ModelPackError(f"model_pack_copy_hash_mismatch:{role}")
            built.append(
                ModelPackArtifact(
                    relativePath=item.relative_path,
                    sizeBytes=destination.stat().st_size,
                    sha256=item.sha256,
                    artifactRole=role,
                )
            )
        manifest: dict[str, object] = {
            "schemaVersion": MODEL_PACK_SCHEMA,
            "modelPackId": source.model_pack_id,
            "modelId": source.model_id,
            "modelVersion": source.model_version,
            "capabilityIds": list(source.capability_ids),
            "assembledFromCommit": assembled_from_commit,
            "artifacts": [asdict(item) for item in sorted(built, key=lambda item: item.relativePath)],
        }
        (stage / MODEL_PACK_MANIFEST).write_bytes(serialize_model_pack_manifest(manifest))
        if preexisting_empty_output:
            output.rmdir()
        os.replace(stage, output)
        published = True
        return manifest
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def _parse_artifact(value: str) -> tuple[str, Path]:
    role, separator, path = value.partition("=")
    if not separator or not role or not path:
        raise argparse.ArgumentTypeError("--artifact expects ROLE=PATH")
    return role, Path(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument(
        "--artifact",
        type=_parse_artifact,
        action="append",
        default=[],
        required=True,
        help="ROLE=PATH, once per artefact the source manifest declares (licence-notice included)",
    )
    parser.add_argument("--assembled-from-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifacts: dict[str, Path] = {}
    for role, path in args.artifact:
        if role in artifacts:
            print(f"model_pack_artifact_duplicate:{role}", file=sys.stderr)
            return 2
        artifacts[role] = path
    try:
        manifest = build_model_pack(
            source_manifest=args.source_manifest,
            artifacts=artifacts,
            assembled_from_commit=args.assembled_from_commit,
            output=args.output,
        )
    except ModelPackError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
