#!/usr/bin/env python3
"""Build one deterministic, integrity-checked MAVI offline vision bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from email.parser import Parser
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
TOOLS_ROOT = Path(__file__).resolve().parent
for candidate in (VISION_ROOT, TOOLS_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from freeze_offline_lock import (  # noqa: E402
    inspect_wheel,
    sha256_file,
    validate_wheel_record_for_target,
    validate_wheelhouse_dependency_closure,
)
from mavi_vision.runtime.deployment_profiles import (  # noqa: E402
    DeploymentProfile,
    DeploymentProfileError,
    load_policy as load_deployment_profile_policy,
)
from mavi_vision.runtime.manifest import (  # noqa: E402
    ReleaseMetadataError,
    load_model_manifest,
)
from mavi_vision.runtime.offline_lock import (  # noqa: E402
    OfflineLockError,
    load_offline_runtime_lock,
)
from mavi_vision.runtime.qualification import (  # noqa: E402
    load_runtime_profile,
    verify_release_selection,
    verify_runtime_release_locks,
)


CANONICAL_DEPLOYMENT_PROFILE_POLICY = (
    ROOT / "config" / "acceptance" / "phase1-deployment-profiles-v1.json"
)


class OfflineBundleError(ValueError):
    """Stable deterministic-bundle build failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BundleHostCompatibility:
    os_family: str
    architecture: str
    distribution: str | None
    distribution_version: str | None
    native_abi: str
    portability: str


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
    host_compatibility: BundleHostCompatibility
    deployment_profile: str | None
    deployment_profile_policy_sha256: str
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
    deployment_profile_policy_path: Path
    deployment_profile_policy_sha256: str
    deployment_profile_id: str | None = None
    python_installer_path: Path | None = None


def _bundle_host_compatibility(platform_variant: str) -> BundleHostCompatibility:
    if platform_variant.startswith("linux-x86_64-"):
        return BundleHostCompatibility(
            os_family="linux",
            architecture="x86_64",
            distribution="ubuntu",
            distribution_version="24.04",
            native_abi="glibc-2.39-libstdcxx-GLIBCXX_3.4.33-linux_x86_64",
            portability="qualified-host-only",
        )
    if platform_variant.startswith("windows-x86_64-"):
        return BundleHostCompatibility(
            os_family="windows",
            architecture="x86_64",
            distribution=None,
            distribution_version=None,
            native_abi="win_amd64",
            portability="qualified-platform",
        )
    raise OfflineBundleError("bundle_host_compatibility_unknown")


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
    _validate_source_commit_against_checkout(inputs.source_commit, ROOT)
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
    if inputs.python_installer_path is not None:
        _assert_safe_regular_file(inputs.python_installer_path)
        if not inputs.platform_variant.startswith("windows-"):
            raise OfflineBundleError("python_installer_platform_mismatch")
    verified_locks = _revalidate_assembly_boundary(inputs)
    for lock_path in verified_locks.values():
        _assert_safe_regular_file(lock_path)

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
    _verify_mavi_wheel_source(
        wheel_records=wheel_records,
        source_root=VISION_ROOT,
    )

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
        for variant, lock_path in sorted(verified_locks.items()):
            add_file(
                lock_path,
                (
                    "release/runtime/mmdetection-phase1-v1/"
                    f"{variant}.lock"
                ),
                purpose="runtime-lock",
                platform_variant=variant,
            )

        if inputs.python_installer_path is not None:
            add_file(
                inputs.python_installer_path,
                f"prerequisites/python/{inputs.python_installer_path.name}",
                purpose="python-runtime-installer",
                package="cpython",
                version=inputs.python_version,
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
        _verify_bundled_release_selection(stage, inputs.release_status)
        bundle_id = _bundle_id(inputs, verified_locks)
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
            host_compatibility=_bundle_host_compatibility(inputs.platform_variant),
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
    python_installer_path: Path | None = None,
) -> VerifiedBundleInputs:
    _validate_source_commit_against_checkout(source_commit, ROOT)
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
        python_installer_path=python_installer_path,
    )


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _infer_model_root(inputs: VerifiedBundleInputs) -> Path:
    try:
        manifest = load_model_manifest(inputs.model_manifest_path)
    except ReleaseMetadataError as exc:
        raise OfflineBundleError(exc.code) from exc

    root = _absolute_path(inputs.checkpoint_path)
    for _ in PurePosixPath(manifest.checkpoint.relative_path).parts:
        root = root.parent
    return root


def _revalidate_assembly_boundary(
    inputs: VerifiedBundleInputs,
) -> Mapping[str, Path]:
    if inputs.release_status not in {"qualification-candidate", "production"}:
        raise OfflineBundleError("bundle_release_status_invalid")

    model_root = _infer_model_root(inputs)
    allow_unverified = inputs.release_status == "qualification-candidate"
    try:
        selection = verify_release_selection(
            model_root=model_root,
            manifest_path=inputs.model_manifest_path,
            profile_path=inputs.pipeline_profile_path,
            runtime_profile_path=inputs.runtime_profile_path,
            qualification_path=inputs.qualification_path,
            allow_unverified=allow_unverified,
        )
        runtime_profile = load_runtime_profile(inputs.runtime_profile_path)
        verified_locks = verify_runtime_release_locks(
            inputs.runtime_profile_path,
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
        inputs.release_status,
        verification_status=selection.verification_status,
        runtime_qualification_status=selection.runtime_qualification_status,
        qualification_overall_result=qualification.overall_result,
        all_mandatory_gates_passed=all_gates_passed,
    )

    lock_path = verified_locks.get(inputs.platform_variant)
    platform = selection.runtime_platform_variants.get(inputs.platform_variant)
    if (
        lock_path is None
        or platform is None
        or platform.python_identity is None
        or selection.manifest.model_id != inputs.model_id
        or selection.runtime_profile_id != inputs.runtime_profile_id
        or platform.python_identity.version != inputs.python_version
        or _absolute_path(lock_path) != _absolute_path(inputs.runtime_lock_path)
        or _absolute_path(selection.checkpoint_path) != _absolute_path(inputs.checkpoint_path)
        or _absolute_path(selection.resolved_config_path)
        != _absolute_path(inputs.resolved_config_path)
        or selection.manifest.checkpoint.sha256 != inputs.checkpoint_sha256
        or selection.manifest.resolved_config.sha256 != inputs.resolved_config_sha256
    ):
        raise OfflineBundleError("bundle_verified_inputs_mismatch")

    return verified_locks


def _verify_bundled_release_selection(
    stage: Path,
    release_status: str,
) -> None:
    try:
        verify_release_selection(
            model_root=stage / "release" / "models",
            manifest_path=(
                stage
                / "release"
                / "models"
                / "manifests"
                / "rtmdet-m-coco-phase1-v1.json"
            ),
            profile_path=(
                stage
                / "release"
                / "config"
                / "pipelines"
                / "phase1-detection-tracking-v1.json"
            ),
            runtime_profile_path=(
                stage
                / "release"
                / "runtime"
                / "mmdetection-phase1-v1"
                / "runtime.json"
            ),
            qualification_path=(
                stage
                / "release"
                / "models"
                / "qualifications"
                / "rtmdet-m-coco-phase1-v1.json"
            ),
            allow_unverified=release_status == "qualification-candidate",
        )
    except ReleaseMetadataError as exc:
        raise OfflineBundleError(exc.code) from exc


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
    python_installer_path: Path | None = None,
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
        python_installer_path=python_installer_path,
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
            validate_wheel_record_for_target(
                record,
                platform_variant=lock.platform_variant,
                python_version=lock.python_version,
            )
        except ValueError as exc:
            raise OfflineBundleError(str(exc)) from exc
        if record.name in records:
            raise OfflineBundleError("wheelhouse_duplicate_distribution")
        records[record.name] = record

    try:
        validate_wheelhouse_dependency_closure(
            records,
            platform_variant=lock.platform_variant,
            python_version=lock.python_version,
        )
    except ValueError as exc:
        raise OfflineBundleError(str(exc)) from exc

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
    host = _bundle_host_compatibility(inputs.platform_variant)
    if host.os_family == "linux":
        host_lines = (
            "Qualified host: Ubuntu 24.04 x86_64\n"
            "Native ABI: glibc 2.39 / linux_x86_64\n"
            "libstdc++ ABI: GLIBCXX_3.4.33 available\n"
            "Portability: qualified-host-only\n"
            "This native Linux bundle is not qualified for other distributions/releases.\n"
        )
    else:
        host_lines = (
            "Qualified host: Windows x86_64\n"
            "Native ABI: win_amd64\n"
            f"Portability: {host.portability}\n"
        )
    return (
        "MAVI Offline Vision Runtime Bundle\n"
        f"Release status: {inputs.release_status}\n"
        f"Source commit: {inputs.source_commit}\n"
        f"Platform variant: {inputs.platform_variant}\n"
        f"Required Python: CPython {inputs.python_version}\n"
        + host_lines
        + "\n"
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


def _bundle_id(
    inputs: VerifiedBundleInputs,
    verified_locks: Mapping[str, Path],
) -> str:
    identity = {
        "sourceCommit": inputs.source_commit,
        "platformVariant": inputs.platform_variant,
        "runtimeProfileId": inputs.runtime_profile_id,
        "runtimeProfileSha256": sha256_file(inputs.runtime_profile_path),
        "modelManifestSha256": sha256_file(inputs.model_manifest_path),
        "pipelineProfileSha256": sha256_file(inputs.pipeline_profile_path),
        "qualificationRecordSha256": sha256_file(inputs.qualification_path),
        "releaseLockSha256": sha256_file(inputs.runtime_lock_path),
        "qualifiedReleaseLocks": {
            variant: sha256_file(path)
            for variant, path in sorted(verified_locks.items())
        },
        "hostCompatibility": asdict(
            _bundle_host_compatibility(inputs.platform_variant)
        ),
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
        "hostCompatibility": {
            "osFamily": manifest.host_compatibility.os_family,
            "architecture": manifest.host_compatibility.architecture,
            "distribution": manifest.host_compatibility.distribution,
            "distributionVersion": manifest.host_compatibility.distribution_version,
            "nativeAbi": manifest.host_compatibility.native_abi,
            "portability": manifest.host_compatibility.portability,
        },
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
    root_manifest = (stage / "bundle-manifest.json").resolve()
    actual = {
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file() and path.resolve() != root_manifest
    }
    if actual != set(expected):
        raise OfflineBundleError("bundle_artifact_set_mismatch")
    for relative_path, artifact in expected.items():
        path = stage.joinpath(*PurePosixPath(relative_path).parts)
        if path.stat().st_size != artifact.size_bytes:
            raise OfflineBundleError("bundle_artifact_size_mismatch")
        if sha256_file(path) != artifact.sha256:
            raise OfflineBundleError("bundle_artifact_hash_mismatch")


def _normalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _canonical_specifiers(value: str) -> tuple[str, ...]:
    return tuple(
        sorted(part.strip() for part in value.split(",") if part.strip())
    )


def _canonical_requirement(
    value: str,
    *,
    expected_extra: str | None = None,
) -> tuple[str, tuple[str, ...], str | None]:
    requirement, separator, marker = value.partition(";")
    match = re.fullmatch(
        r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?\s*(.*)\s*",
        requirement,
    )
    if match is None:
        raise OfflineBundleError("mavi_wheel_metadata_mismatch")
    name = _normalize_distribution_name(match.group(1))
    specifiers = _canonical_specifiers(match.group(2))
    actual_extra: str | None = None
    if separator:
        marker_match = re.fullmatch(
            r"""\s*extra\s*==\s*["']([^"']+)["']\s*""",
            marker,
        )
        if marker_match is None:
            raise OfflineBundleError("mavi_wheel_metadata_mismatch")
        actual_extra = marker_match.group(1)
    if actual_extra != expected_extra:
        raise OfflineBundleError("mavi_wheel_metadata_mismatch")
    return name, specifiers, actual_extra


def _expected_project_requirements(project: dict) -> set[tuple[str, tuple[str, ...], str | None]]:
    expected = {
        _canonical_requirement(value)
        for value in project.get("dependencies", [])
    }
    for extra, requirements in project.get("optional-dependencies", {}).items():
        # PEP 621 stores the extra name in the table key. Wheel METADATA
        # represents that same relationship as a PEP 508 extra marker.
        expected.update(
            _canonical_requirement(
                f'{value}; extra == "{extra}"',
                expected_extra=extra,
            )
            for value in requirements
        )
    return expected


def _actual_wheel_requirements(metadata) -> set[tuple[str, tuple[str, ...], str | None]]:
    actual: set[tuple[str, tuple[str, ...], str | None]] = set()
    for value in metadata.get_all("Requires-Dist", []):
        requirement, separator, marker = value.partition(";")
        expected_extra: str | None = None
        if separator:
            marker_match = re.fullmatch(
                r"""\s*extra\s*==\s*["']([^"']+)["']\s*""",
                marker,
            )
            if marker_match is None:
                raise OfflineBundleError("mavi_wheel_metadata_mismatch")
            expected_extra = marker_match.group(1)
        actual.add(
            _canonical_requirement(
                requirement + (
                    f'; extra == "{expected_extra}"'
                    if expected_extra is not None
                    else ""
                ),
                expected_extra=expected_extra,
            )
        )
    return actual


def _verify_mavi_wheel_source(*, wheel_records: dict, source_root: Path) -> None:
    _assert_safe_directory(source_root)
    package_root = source_root / "mavi_vision"
    project_path = source_root / "pyproject.toml"
    _assert_safe_directory(package_root)
    _assert_safe_regular_file(project_path)

    record = wheel_records.get("mavi-vision")
    if record is None:
        raise OfflineBundleError("mavi_wheel_missing")

    source_files: dict[str, bytes] = {}
    for path in sorted(package_root.rglob("*")):
        relative_to_package = path.relative_to(package_root)
        if "__pycache__" in relative_to_package.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if _path_is_link_or_reparse(path):
            raise OfflineBundleError("bundle_input_link_forbidden")
        if path.is_dir():
            continue
        _assert_safe_regular_file(path)
        logical = path.relative_to(source_root).as_posix()
        source_files[logical] = path.read_bytes()

    try:
        project_document = tomllib.loads(project_path.read_text(encoding="utf-8"))
        project = project_document["project"]
        with zipfile.ZipFile(record.path) as archive:
            member_names = [
                info.filename
                for info in archive.infolist()
                if not info.is_dir()
            ]
            if len(member_names) != len(set(member_names)):
                raise OfflineBundleError("mavi_wheel_source_mismatch")
            for name in member_names:
                try:
                    validate_bundle_relative_path(name)
                except OfflineBundleError as exc:
                    raise OfflineBundleError("mavi_wheel_source_mismatch") from exc

            metadata_names = [
                name
                for name in member_names
                if name.endswith(".dist-info/METADATA")
                and name.count("/") == 1
            ]
            if len(metadata_names) != 1:
                raise OfflineBundleError("mavi_wheel_metadata_mismatch")
            dist_info_root = metadata_names[0].split("/", 1)[0]
            installable_members = {
                name
                for name in member_names
                if not name.startswith(dist_info_root + "/")
            }
            if installable_members != set(source_files):
                raise OfflineBundleError("mavi_wheel_source_mismatch")
            for logical, expected_bytes in source_files.items():
                if archive.read(logical) != expected_bytes:
                    raise OfflineBundleError("mavi_wheel_source_mismatch")

            metadata = Parser().parsestr(
                archive.read(metadata_names[0]).decode("utf-8")
            )
    except OfflineBundleError:
        raise
    except (KeyError, OSError, UnicodeDecodeError, ValueError, zipfile.BadZipFile) as exc:
        raise OfflineBundleError("mavi_wheel_metadata_mismatch") from exc

    if _normalize_distribution_name(metadata.get("Name", "")) != "mavi-vision":
        raise OfflineBundleError("mavi_wheel_metadata_mismatch")
    if metadata.get("Version") != project.get("version"):
        raise OfflineBundleError("mavi_wheel_metadata_mismatch")
    if _canonical_specifiers(metadata.get("Requires-Python", "")) != _canonical_specifiers(
        str(project.get("requires-python", ""))
    ):
        raise OfflineBundleError("mavi_wheel_metadata_mismatch")
    if _actual_wheel_requirements(metadata) != _expected_project_requirements(project):
        raise OfflineBundleError("mavi_wheel_metadata_mismatch")


def _repository_head(repository_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OfflineBundleError("bundle_source_commit_unverifiable") from exc
    head = completed.stdout.strip()
    _validate_source_commit(head)
    return head


def _is_mavi_wheel_build_input(logical_path: str) -> bool:
    path = PurePosixPath(logical_path)
    parts = path.parts
    if len(parts) >= 3 and parts[:3] == ("src", "vision", "mavi_vision"):
        package_parts = parts[3:]
        if "__pycache__" in package_parts or path.suffix in {".pyc", ".pyo"}:
            return False
        return True
    return len(parts) == 3 and parts[:2] == ("src", "vision")


def _git_changed_paths(repository_root: Path) -> set[str]:
    commands = (
        (
            "diff",
            "--name-only",
            "-z",
            "HEAD",
            "--",
            "src/vision",
        ),
        (
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "src/vision",
        ),
        (
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            "src/vision",
        ),
    )
    changed: set[str] = set()
    try:
        for arguments in commands:
            completed = subprocess.run(
                ["git", "-C", str(repository_root), *arguments],
                check=True,
                capture_output=True,
            )
            changed.update(
                os.fsdecode(raw_path)
                for raw_path in completed.stdout.split(b"\0")
                if raw_path
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OfflineBundleError("bundle_source_commit_unverifiable") from exc
    return changed


def _assert_packaged_source_clean(repository_root: Path) -> None:
    if any(
        _is_mavi_wheel_build_input(path)
        for path in _git_changed_paths(repository_root)
    ):
        raise OfflineBundleError("bundle_source_dirty")


def _validate_source_commit_against_checkout(
    value: str,
    repository_root: Path,
) -> None:
    _validate_source_commit(value)
    _assert_packaged_source_clean(repository_root)
    if _repository_head(repository_root) != value:
        raise OfflineBundleError("bundle_source_commit_mismatch")


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
    parser.add_argument("--python-installer", type=Path)
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
            python_installer_path=args.python_installer,
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
