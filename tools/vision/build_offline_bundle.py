#!/usr/bin/env python3
"""Build one deterministic, integrity-checked MAVI offline vision bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
TOOLS_ROOT = Path(__file__).resolve().parent
for candidate in (VISION_ROOT, TOOLS_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from freeze_offline_lock import inspect_wheel, sha256_file  # noqa: E402
from mavi_vision.runtime.manifest import ReleaseMetadataError  # noqa: E402
from mavi_vision.runtime.offline_lock import (  # noqa: E402
    OfflineLockError,
    load_offline_runtime_lock,
)
from mavi_vision.runtime.qualification import (  # noqa: E402
    MANDATORY_QUALIFICATION_GATES,
    load_runtime_profile,
    verify_release_selection,
    verify_runtime_release_locks,
)


class OfflineBundleError(ValueError):
    """Stable deterministic-bundle build failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BundleArtifact:
    relative_path: str
    size_bytes: int
    sha256: str
    purpose: str
    package: str | None
    version: str | None
    platform_variant: str


@dataclass(frozen=True, slots=True)
class BundleManifest:
    schema_version: Literal["1.0"]
    bundle_id: str
    release_status: Literal["qualification-candidate", "production"]
    source_commit: str
    platform_variant: str
    python_version: str
    model_id: str
    runtime_profile_id: str
    lock_sha256: str
    artifacts: tuple[BundleArtifact, ...]


@dataclass(frozen=True, slots=True)
class VerifiedBundleInputs:
    source_commit: str
    release_status: Literal["qualification-candidate", "production"]
    platform_variant: str
    python_version: str
    model_id: str
    runtime_profile_id: str
    model_manifest_path: Path
    qualification_path: Path
    pipeline_profile_path: Path
    runtime_profile_path: Path
    runtime_lock_path: Path
    checkpoint_path: Path
    resolved_config_path: Path
    checkpoint_sha256: str
    resolved_config_sha256: str
    wheelhouse: Path


def validate_bundle_relative_path(value: str) -> PurePosixPath:
    if not value or value != value.strip() or "\\" in value or "\x00" in value:
        raise OfflineBundleError("bundle_path_invalid")
    logical = PurePosixPath(value)
    parts = value.split("/")
    if logical.is_absolute() or not parts:
        raise OfflineBundleError("bundle_path_invalid")
    if any(part in {"", ".", ".."} for part in parts):
        raise OfflineBundleError("bundle_path_invalid")
    if ":" in parts[0]:
        raise OfflineBundleError("bundle_path_invalid")
    return logical


def validate_release_mode(
    release_status: str,
    *,
    verification_status: str,
    runtime_qualification_status: str,
    qualification_overall_result: str,
    all_mandatory_gates_passed: bool,
) -> None:
    if release_status not in {"qualification-candidate", "production"}:
        raise OfflineBundleError("bundle_release_status_invalid")
    if release_status == "qualification-candidate":
        return
    if (
        verification_status != "verified"
        or runtime_qualification_status != "qualified"
        or qualification_overall_result != "passed"
        or not all_mandatory_gates_passed
    ):
        raise OfflineBundleError("production_release_not_qualified")


def build_bundle_from_verified_inputs(
    inputs: VerifiedBundleInputs,
    output: Path,
) -> BundleManifest:
    _validate_source_commit(inputs.source_commit)
    if inputs.release_status not in {"qualification-candidate", "production"}:
        raise OfflineBundleError("bundle_release_status_invalid")

    for path in (
        inputs.model_manifest_path,
        inputs.qualification_path,
        inputs.pipeline_profile_path,
        inputs.runtime_profile_path,
        inputs.runtime_lock_path,
        inputs.checkpoint_path,
        inputs.resolved_config_path,
    ):
        _assert_safe_regular_file(path)
    _assert_safe_directory(inputs.wheelhouse)

    if sha256_file(inputs.checkpoint_path) != inputs.checkpoint_sha256:
        raise OfflineBundleError("checkpoint_hash_mismatch")
    if sha256_file(inputs.resolved_config_path) != inputs.resolved_config_sha256:
        raise OfflineBundleError("resolved_config_hash_mismatch")

    try:
        lock = load_offline_runtime_lock(inputs.runtime_lock_path)
    except OfflineLockError as exc:
        raise OfflineBundleError(exc.code) from exc
    if lock.platform_variant != inputs.platform_variant:
        raise OfflineBundleError("offline_lock_variant_mismatch")
    if lock.python_version != inputs.python_version:
        raise OfflineBundleError("offline_lock_python_version_mismatch")

    wheel_records = _validate_wheelhouse(inputs.wheelhouse, lock)

    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise OfflineBundleError("bundle_destination_not_empty")
        preexisting_empty_output = True
    else:
        preexisting_empty_output = False

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.",
            dir=output.parent,
        )
    )
    published = False
    try:
        artifacts: list[BundleArtifact] = []

        def add_file(
            source: Path,
            relative_path: str,
            *,
            purpose: str,
            package: str | None = None,
            version: str | None = None,
            platform_variant: str = "shared",
        ) -> None:
            logical = validate_bundle_relative_path(relative_path)
            destination = stage.joinpath(*logical.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise OfflineBundleError("bundle_duplicate_destination")
            shutil.copyfile(source, destination)
            source_hash = sha256_file(source)
            destination_hash = sha256_file(destination)
            if source_hash != destination_hash:
                raise OfflineBundleError("bundle_copy_hash_mismatch")
            artifacts.append(
                BundleArtifact(
                    relative_path=relative_path,
                    size_bytes=destination.stat().st_size,
                    sha256=destination_hash,
                    purpose=purpose,
                    package=package,
                    version=version,
                    platform_variant=platform_variant,
                )
            )

        for record in sorted(wheel_records.values(), key=lambda item: item.name):
            add_file(
                record.path,
                f"wheels/{record.path.name}",
                purpose="python-wheel",
                package=record.name,
                version=record.version,
                platform_variant=inputs.platform_variant,
            )

        add_file(
            inputs.model_manifest_path,
            "release/models/manifests/rtmdet-m-coco-phase1-v1.json",
            purpose="model-manifest",
        )
        add_file(
            inputs.qualification_path,
            "release/models/qualifications/rtmdet-m-coco-phase1-v1.json",
            purpose="qualification-record",
        )
        add_file(
            inputs.checkpoint_path,
            f"release/models/rtmdet-m-coco-phase1-v1/{inputs.checkpoint_path.name}",
            purpose="mavi-model-checkpoint",
        )
        add_file(
            inputs.resolved_config_path,
            f"release/models/rtmdet-m-coco-phase1-v1/{inputs.resolved_config_path.name}",
            purpose="resolved-model-config",
        )
        add_file(
            inputs.pipeline_profile_path,
            "release/config/pipelines/phase1-detection-tracking-v1.json",
            purpose="pipeline-profile",
        )
        add_file(
            inputs.runtime_profile_path,
            "release/runtime/mmdetection-phase1-v1/runtime.json",
            purpose="runtime-profile",
        )
        add_file(
            inputs.runtime_lock_path,
            (
                "release/runtime/mmdetection-phase1-v1/"
                f"{inputs.platform_variant}.lock"
            ),
            purpose="runtime-lock",
            platform_variant=inputs.platform_variant,
        )

        install_path = stage / "INSTALL.txt"
        install_payload = _install_instructions(inputs).encode("utf-8")
        install_path.write_bytes(install_payload)
        artifacts.append(
            BundleArtifact(
                relative_path="INSTALL.txt",
                size_bytes=len(install_payload),
                sha256=sha256_file(install_path),
                purpose="install-instructions",
                package=None,
                version=None,
                platform_variant=inputs.platform_variant,
            )
        )

        artifacts = sorted(artifacts, key=lambda item: item.relative_path)
        bundle_id = _bundle_id(inputs)
        manifest = BundleManifest(
            schema_version="1.0",
            bundle_id=bundle_id,
            release_status=inputs.release_status,
            source_commit=inputs.source_commit,
            platform_variant=inputs.platform_variant,
            python_version=inputs.python_version,
            model_id=inputs.model_id,
            runtime_profile_id=inputs.runtime_profile_id,
            lock_sha256=sha256_file(inputs.runtime_lock_path),
            artifacts=tuple(artifacts),
        )
        manifest_path = stage / "bundle-manifest.json"
        manifest_path.write_bytes(_serialize_manifest(manifest))

        _verify_staged_bundle(stage, manifest)

        if preexisting_empty_output:
            try:
                output.rmdir()
            except OSError as exc:
                raise OfflineBundleError("bundle_destination_changed") from exc
        try:
            os.replace(stage, output)
        except OSError as exc:
            raise OfflineBundleError("bundle_publish_failed") from exc
        published = True
        return manifest
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def resolve_verified_bundle_inputs(
    *,
    source_commit: str,
    release_status: str,
    platform_variant: str,
    model_root: Path,
    manifest_path: Path,
    qualification_path: Path,
    pipeline_profile_path: Path,
    runtime_profile_path: Path,
    wheelhouse: Path,
) -> VerifiedBundleInputs:
    try:
        selection = verify_release_selection(
            model_root=model_root,
            manifest_path=manifest_path,
            profile_path=pipeline_profile_path,
            runtime_profile_path=runtime_profile_path,
            qualification_path=qualification_path,
            allow_unverified=release_status == "qualification-candidate",
        )
        runtime_profile = load_runtime_profile(runtime_profile_path)
        verified_locks = verify_runtime_release_locks(
            runtime_profile_path,
            runtime_profile,
        )
    except ReleaseMetadataError as exc:
        raise OfflineBundleError(exc.code) from exc

    qualification = selection.qualification
    if qualification is None:
        raise OfflineBundleError("qualification_record_required")
    all_gates_passed = all(
        qualification.required_gates.get(gate) == "passed"
        for gate in MANDATORY_QUALIFICATION_GATES
    )
    validate_release_mode(
        release_status,
        verification_status=selection.verification_status,
        runtime_qualification_status=selection.runtime_qualification_status,
        qualification_overall_result=qualification.overall_result,
        all_mandatory_gates_passed=all_gates_passed,
    )

    lock_path = verified_locks.get(platform_variant)
    if lock_path is None:
        raise OfflineBundleError("bundle_platform_lock_not_qualified")
    platform = selection.runtime_platform_variants.get(platform_variant)
    if platform is None or platform.python_identity is None:
        raise OfflineBundleError("bundle_platform_identity_missing")

    return VerifiedBundleInputs(
        source_commit=source_commit,
        release_status=release_status,  # type: ignore[arg-type]
        platform_variant=platform_variant,
        python_version=platform.python_identity.version,
        model_id=selection.manifest.model_id,
        runtime_profile_id=selection.runtime_profile_id,
        model_manifest_path=manifest_path,
        qualification_path=qualification_path,
        pipeline_profile_path=pipeline_profile_path,
        runtime_profile_path=runtime_profile_path,
        runtime_lock_path=lock_path,
        checkpoint_path=selection.checkpoint_path,
        resolved_config_path=selection.resolved_config_path,
        checkpoint_sha256=selection.manifest.checkpoint.sha256,
        resolved_config_sha256=selection.manifest.resolved_config.sha256,
        wheelhouse=wheelhouse,
    )


def build_offline_bundle(
    *,
    source_commit: str,
    release_status: str,
    platform_variant: str,
    model_root: Path,
    manifest_path: Path,
    qualification_path: Path,
    pipeline_profile_path: Path,
    runtime_profile_path: Path,
    wheelhouse: Path,
    output: Path,
) -> BundleManifest:
    inputs = resolve_verified_bundle_inputs(
        source_commit=source_commit,
        release_status=release_status,
        platform_variant=platform_variant,
        model_root=model_root,
        manifest_path=manifest_path,
        qualification_path=qualification_path,
        pipeline_profile_path=pipeline_profile_path,
        runtime_profile_path=runtime_profile_path,
        wheelhouse=wheelhouse,
    )
    return build_bundle_from_verified_inputs(inputs, output)


def _validate_wheelhouse(wheelhouse: Path, lock):
    records = {}
    for entry in wheelhouse.iterdir():
        _assert_safe_regular_file(entry)
        if entry.suffix.lower() != ".whl":
            raise OfflineBundleError("wheelhouse_non_wheel_entry")
        try:
            record = inspect_wheel(entry)
        except ValueError as exc:
            raise OfflineBundleError(str(exc)) from exc
        if record.name in records:
            raise OfflineBundleError("wheelhouse_duplicate_distribution")
        records[record.name] = record

    expected = {item.name: item for item in lock.distributions}
    if set(records) != set(expected):
        raise OfflineBundleError("wheelhouse_distribution_mismatch")
    for name, item in expected.items():
        record = records[name]
        if record.version != item.version:
            raise OfflineBundleError("wheel_version_mismatch")
        if record.sha256 != item.sha256:
            raise OfflineBundleError("wheel_hash_mismatch")
    return records


def _install_instructions(inputs: VerifiedBundleInputs) -> str:
    lock_rel = (
        "./release/runtime/mmdetection-phase1-v1/"
        f"{inputs.platform_variant}.lock"
    )
    return (
        "MAVI Offline Vision Runtime Bundle\n"
        f"Release status: {inputs.release_status}\n"
        f"Source commit: {inputs.source_commit}\n"
        f"Platform variant: {inputs.platform_variant}\n"
        f"Required Python: CPython {inputs.python_version}\n"
        "\n"
        "Install from the bundle root only:\n"
        "python -m pip install --no-index --only-binary=:all: "
        f"--require-hashes --find-links ./wheels -r {lock_rel}\n"
        "python -m pip check\n"
        "\n"
        "Runtime release paths:\n"
        "MAVI_MODEL_ROOT=./release/models\n"
        "MAVI_MODEL_MANIFEST_PATH="
        "./release/models/manifests/rtmdet-m-coco-phase1-v1.json\n"
        "MAVI_QUALIFICATION_RECORD_PATH="
        "./release/models/qualifications/rtmdet-m-coco-phase1-v1.json\n"
        "MAVI_PIPELINE_PROFILE_PATH="
        "./release/config/pipelines/phase1-detection-tracking-v1.json\n"
        "MAVI_RUNTIME_PROFILE_PATH="
        "./release/runtime/mmdetection-phase1-v1/runtime.json\n"
    )


def _bundle_id(inputs: VerifiedBundleInputs) -> str:
    identity = {
        "sourceCommit": inputs.source_commit,
        "platformVariant": inputs.platform_variant,
        "runtimeProfileId": inputs.runtime_profile_id,
        "runtimeProfileSha256": sha256_file(inputs.runtime_profile_path),
        "modelManifestSha256": sha256_file(inputs.model_manifest_path),
        "pipelineProfileSha256": sha256_file(inputs.pipeline_profile_path),
        "qualificationRecordSha256": sha256_file(inputs.qualification_path),
        "releaseLockSha256": sha256_file(inputs.runtime_lock_path),
    }
    payload = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _serialize_manifest(manifest: BundleManifest) -> bytes:
    payload = {
        "schemaVersion": manifest.schema_version,
        "bundleId": manifest.bundle_id,
        "releaseStatus": manifest.release_status,
        "sourceCommit": manifest.source_commit,
        "platformVariant": manifest.platform_variant,
        "pythonVersion": manifest.python_version,
        "modelId": manifest.model_id,
        "runtimeProfileId": manifest.runtime_profile_id,
        "lockSha256": manifest.lock_sha256,
        "artifacts": [
            {
                "relativePath": item.relative_path,
                "sizeBytes": item.size_bytes,
                "sha256": item.sha256,
                "purpose": item.purpose,
                "package": item.package,
                "version": item.version,
                "platformVariant": item.platform_variant,
            }
            for item in manifest.artifacts
        ],
    }
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _verify_staged_bundle(stage: Path, manifest: BundleManifest) -> None:
    expected = {item.relative_path: item for item in manifest.artifacts}
    actual = {
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file() and path.name != "bundle-manifest.json"
    }
    if actual != set(expected):
        raise OfflineBundleError("bundle_artifact_set_mismatch")
    for relative_path, artifact in expected.items():
        path = stage.joinpath(*PurePosixPath(relative_path).parts)
        if path.stat().st_size != artifact.size_bytes:
            raise OfflineBundleError("bundle_artifact_size_mismatch")
        if sha256_file(path) != artifact.sha256:
            raise OfflineBundleError("bundle_artifact_hash_mismatch")


def _validate_source_commit(value: str) -> None:
    if (
        len(value) not in {40, 64}
        or value.lower() != value
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise OfflineBundleError("bundle_source_commit_invalid")


def _path_is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise OfflineBundleError("bundle_input_missing") from exc
    if stat.S_ISLNK(info.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(reparse and attributes & reparse)


def _assert_no_link_ancestry(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if not current.exists():
            raise OfflineBundleError("bundle_input_missing")
        if _path_is_link_or_reparse(current):
            raise OfflineBundleError("bundle_input_link_forbidden")


def _assert_safe_regular_file(path: Path) -> None:
    _assert_no_link_ancestry(path)
    if not path.is_file():
        raise OfflineBundleError("bundle_input_not_file")


def _assert_safe_directory(path: Path) -> None:
    _assert_no_link_ancestry(path)
    if not path.is_dir():
        raise OfflineBundleError("wheelhouse_invalid")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic offline MAVI vision runtime bundle.",
    )
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--release-status",
        choices=("qualification-candidate", "production"),
        required=True,
    )
    parser.add_argument("--platform-variant", required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--pipeline-profile", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        manifest = build_offline_bundle(
            source_commit=args.source_commit,
            release_status=args.release_status,
            platform_variant=args.platform_variant,
            model_root=args.model_root,
            manifest_path=args.manifest,
            qualification_path=args.qualification,
            pipeline_profile_path=args.pipeline_profile,
            runtime_profile_path=args.runtime_profile,
            wheelhouse=args.wheelhouse,
            output=args.output,
        )
    except (OfflineBundleError, ReleaseMetadataError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": "passed",
                "bundleId": manifest.bundle_id,
                "platformVariant": manifest.platform_variant,
                "releaseStatus": manifest.release_status,
                "artifactCount": len(manifest.artifacts),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
