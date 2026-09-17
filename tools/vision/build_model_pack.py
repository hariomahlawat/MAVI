#!/usr/bin/env python3
"""Build the reusable content-addressed MAVI Vision Model Pack."""

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

from mavi_vision.runtime.component_identity import (  # noqa: E402
    ModelPackIdentityInputs,
    model_pack_id,
)

_SCHEMA = "mavi-vision-model-pack-v1"
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ModelPackError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ModelPackArtifact:
    relativePath: str
    sizeBytes: int
    sha256: str
    purpose: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ModelPackError("model_pack_asset_unreadable") from exc
    return digest.hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath:
    if not value or value != value.strip() or "\\" in value or "\x00" in value:
        raise ModelPackError("model_pack_path_invalid")
    logical = PurePosixPath(value)
    parts = value.split("/")
    if logical.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise ModelPackError("model_pack_path_invalid")
    if ":" in parts[0]:
        raise ModelPackError("model_pack_path_invalid")
    return logical


def _read_source_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelPackError("model_pack_source_manifest_invalid") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != "1.0":
        raise ModelPackError("model_pack_source_manifest_invalid")
    if not isinstance(payload.get("modelId"), str) or not payload["modelId"]:
        raise ModelPackError("model_pack_source_manifest_invalid")
    for section in ("checkpoint", "resolvedConfig"):
        value = payload.get(section)
        if not isinstance(value, dict):
            raise ModelPackError("model_pack_source_manifest_invalid")
        sha = value.get("sha256")
        relative = value.get("relativePath")
        if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
            raise ModelPackError("model_pack_source_manifest_invalid")
        if not isinstance(relative, str):
            raise ModelPackError("model_pack_source_manifest_invalid")
        _safe_relative_path(relative)
    return payload


def _copy_asset(stage: Path, source: Path, relative_path: str, purpose: str) -> ModelPackArtifact:
    if not source.is_file() or source.is_symlink():
        raise ModelPackError("model_pack_asset_invalid")
    logical = _safe_relative_path(relative_path)
    destination = stage.joinpath(*logical.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ModelPackError("model_pack_duplicate_destination")
    shutil.copyfile(source, destination)
    source_hash = _sha256(source)
    if _sha256(destination) != source_hash:
        raise ModelPackError("model_pack_copy_hash_mismatch")
    return ModelPackArtifact(
        relativePath=relative_path,
        sizeBytes=destination.stat().st_size,
        sha256=source_hash,
        purpose=purpose,
    )


def build_model_pack(
    *,
    source_manifest: Path,
    checkpoint: Path,
    resolved_config: Path,
    assembled_from_commit: str,
    output: Path,
) -> dict[str, object]:
    if not _SHA1_RE.fullmatch(assembled_from_commit):
        raise ModelPackError("model_pack_source_commit_invalid")
    source = _read_source_manifest(source_manifest)
    checkpoint_section = source["checkpoint"]
    config_section = source["resolvedConfig"]
    assert isinstance(checkpoint_section, dict)
    assert isinstance(config_section, dict)

    checkpoint_sha = _sha256(checkpoint)
    config_sha = _sha256(resolved_config)
    if checkpoint_sha != checkpoint_section["sha256"]:
        raise ModelPackError("model_pack_checkpoint_hash_mismatch")
    if config_sha != config_section["sha256"]:
        raise ModelPackError("model_pack_resolved_config_hash_mismatch")

    model_id = str(source["modelId"])
    pack_id = model_pack_id(
        ModelPackIdentityInputs(
            model_id=model_id,
            checkpoint_sha256=checkpoint_sha,
            resolved_config_sha256=config_sha,
        )
    )

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
        artifacts = [
            _copy_asset(
                stage,
                checkpoint,
                str(checkpoint_section["relativePath"]),
                "model-checkpoint",
            ),
            _copy_asset(
                stage,
                resolved_config,
                str(config_section["relativePath"]),
                "resolved-model-config",
            ),
        ]
        manifest: dict[str, object] = {
            "schemaVersion": _SCHEMA,
            "modelPackId": pack_id,
            "modelId": model_id,
            "checkpointSha256": checkpoint_sha,
            "resolvedConfigSha256": config_sha,
            "assembledFromCommit": assembled_from_commit,
            "artifacts": [
                asdict(item)
                for item in sorted(artifacts, key=lambda item: item.relativePath)
            ],
        }
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n"
        ).encode("utf-8")
        (stage / "model-pack-manifest.json").write_bytes(manifest_bytes)
        if preexisting_empty_output:
            output.rmdir()
        os.replace(stage, output)
        published = True
        return manifest
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--resolved-config", type=Path, required=True)
    parser.add_argument("--assembled-from-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        manifest = build_model_pack(
            source_manifest=args.source_manifest,
            checkpoint=args.checkpoint,
            resolved_config=args.resolved_config,
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
