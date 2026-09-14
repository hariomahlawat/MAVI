#!/usr/bin/env python3
"""Build and verify a deterministic manifest for a published MAVI application artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any


class ApplicationArtifactError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_files(root: Path, *, excluded: Path | None = None) -> list[Path]:
    root = root.resolve(strict=True)
    result: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        if excluded is not None and path.resolve() == excluded.resolve():
            continue
        if path.is_symlink():
            raise ApplicationArtifactError("application_artifact_link_forbidden")
        if path.is_file():
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ApplicationArtifactError("application_artifact_path_escape") from exc
            result.append(path)
    return result


def build_manifest(root: Path, *, source_commit: str, build: str, excluded: Path | None = None) -> dict[str, Any]:
    if len(source_commit) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in source_commit):
        raise ApplicationArtifactError("application_source_commit_invalid")
    if not build or build != build.strip():
        raise ApplicationArtifactError("application_build_invalid")
    if not root.is_dir():
        raise ApplicationArtifactError("application_artifact_root_invalid")

    files = []
    for path in safe_files(root, excluded=excluded):
        relative = path.relative_to(root).as_posix()
        logical = PurePosixPath(relative)
        if logical.is_absolute() or ".." in logical.parts:
            raise ApplicationArtifactError("application_artifact_path_invalid")
        files.append({
            "relativePath": relative,
            "sizeBytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    if not files:
        raise ApplicationArtifactError("application_artifact_empty")
    return {
        "schemaVersion": "mavi-application-artifact-v1",
        "sourceCommit": source_commit,
        "build": build,
        "files": files,
    }


def verify_manifest(root: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != "mavi-application-artifact-v1":
        raise ApplicationArtifactError("application_manifest_schema_invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ApplicationArtifactError("application_manifest_files_invalid")
    expected: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"relativePath", "sizeBytes", "sha256"}:
            raise ApplicationArtifactError("application_manifest_entry_invalid")
        relative = item["relativePath"]
        if not isinstance(relative, str) or not relative or relative in expected:
            raise ApplicationArtifactError("application_manifest_path_invalid")
        logical = PurePosixPath(relative)
        if logical.is_absolute() or ".." in logical.parts or "\\" in relative:
            raise ApplicationArtifactError("application_manifest_path_invalid")
        expected.add(relative)
        path = root.joinpath(*logical.parts)
        if path.is_symlink() or not path.is_file():
            raise ApplicationArtifactError("application_manifest_file_missing")
        if path.stat().st_size != item["sizeBytes"] or sha256_file(path) != item["sha256"]:
            raise ApplicationArtifactError("application_manifest_integrity_failed")

    root_manifest = (root / "mavi-application-manifest.json").resolve()
    actual = {
        path.relative_to(root).as_posix()
        for path in safe_files(root)
        if path.resolve() != root_manifest
    }
    if actual != expected:
        raise ApplicationArtifactError("application_manifest_file_set_mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    try:
        if args.verify_only:
            manifest = json.loads(args.output.read_text(encoding="utf-8"))
            verify_manifest(args.artifact_root, manifest)
        else:
            if args.output.exists():
                raise ApplicationArtifactError("application_manifest_output_exists")
            manifest = build_manifest(
                args.artifact_root,
                source_commit=args.source_commit,
                build=args.build,
                excluded=args.output,
            )
            args.output.write_text(
                json.dumps(manifest, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            verify_manifest(args.artifact_root, manifest)
    except (ApplicationArtifactError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({
        "ok": True,
        "manifestSha256": sha256_file(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
