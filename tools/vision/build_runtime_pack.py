#!/usr/bin/env python3
"""Build the reusable, third-party-only MAVI Vision Runtime Binary Pack."""

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
TOOLS_ROOT = Path(__file__).resolve().parent
for candidate in (VISION_ROOT, TOOLS_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from freeze_offline_lock import (  # noqa: E402
    FreezeOfflineLockError,
    inspect_wheel,
    sha256_file,
    validate_wheel_record_for_target,
    validate_wheelhouse_dependency_closure,
)
from mavi_vision.runtime.component_identity import (  # noqa: E402
    RuntimePackIdentityInputs,
    runtime_pack_id,
)
from mavi_vision.runtime.offline_lock import (  # noqa: E402
    OfflineLockError,
    load_offline_runtime_lock,
    validate_offline_runtime_lock_for_runtime,
)
from mavi_vision.runtime.requirements_projection import (  # noqa: E402
    RuntimeRequirementsError,
    parse_runtime_requirements_projection,
    runtime_requirements_sha256,
)

_SCHEMA = "mavi-vision-runtime-pack-v2"
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class RuntimePackError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RuntimePackArtifact:
    relativePath: str
    sizeBytes: int
    sha256: str
    purpose: str
    package: str | None = None
    version: str | None = None


def _safe_relative_path(value: str) -> PurePosixPath:
    if not value or value != value.strip() or "\\" in value or "\x00" in value:
        raise RuntimePackError("runtime_pack_path_invalid")
    logical = PurePosixPath(value)
    parts = value.split("/")
    if logical.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise RuntimePackError("runtime_pack_path_invalid")
    if ":" in parts[0]:
        raise RuntimePackError("runtime_pack_path_invalid")
    return logical


def _copy_artifact(
    stage: Path,
    source: Path,
    relative_path: str,
    *,
    purpose: str,
    package: str | None = None,
    version: str | None = None,
) -> RuntimePackArtifact:
    if not source.is_file() or source.is_symlink():
        raise RuntimePackError("runtime_pack_source_invalid")
    logical = _safe_relative_path(relative_path)
    destination = stage.joinpath(*logical.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimePackError("runtime_pack_duplicate_destination")
    shutil.copyfile(source, destination)
    source_hash = sha256_file(source)
    if sha256_file(destination) != source_hash:
        raise RuntimePackError("runtime_pack_copy_hash_mismatch")
    return RuntimePackArtifact(
        relativePath=relative_path,
        sizeBytes=destination.stat().st_size,
        sha256=source_hash,
        purpose=purpose,
        package=package,
        version=version,
    )


def _load_runtime_inputs(
    *,
    wheelhouse: Path,
    lock_path: Path,
    requirements_path: Path,
    platform_variant: str,
    python_version: str,
):
    if not wheelhouse.is_dir() or wheelhouse.is_symlink():
        raise RuntimePackError("runtime_pack_wheelhouse_invalid")
    try:
        lock = load_offline_runtime_lock(lock_path)
        projection = parse_runtime_requirements_projection(requirements_path.read_bytes())
    except (OfflineLockError, RuntimeRequirementsError, OSError) as exc:
        code = getattr(exc, "code", "runtime_pack_input_unreadable")
        raise RuntimePackError(str(code)) from exc

    if lock.platform_variant != platform_variant or projection.platform_variant != platform_variant:
        raise RuntimePackError("runtime_pack_variant_mismatch")
    if lock.python_version != python_version or projection.python_version != python_version:
        raise RuntimePackError("runtime_pack_python_version_mismatch")
    if any(item.name == "mavi-vision" for item in lock.distributions):
        raise RuntimePackError("runtime_pack_first_party_wheel_forbidden")

    records = {}
    try:
        for path in sorted(wheelhouse.iterdir()):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() != ".whl":
                raise RuntimePackError("runtime_pack_wheelhouse_non_wheel")
            record = inspect_wheel(path)
            if record.name == "mavi-vision":
                raise RuntimePackError("runtime_pack_first_party_wheel_forbidden")
            validate_wheel_record_for_target(
                record,
                platform_variant=platform_variant,
                python_version=python_version,
            )
            if record.name in records:
                raise RuntimePackError("runtime_pack_duplicate_distribution")
            records[record.name] = record
        validate_wheelhouse_dependency_closure(
            records,
            platform_variant=platform_variant,
            python_version=python_version,
        )
    except FreezeOfflineLockError as exc:
        raise RuntimePackError(str(exc)) from exc

    locked = {item.name: item for item in lock.distributions}
    if set(records) != set(locked):
        raise RuntimePackError("runtime_pack_wheelhouse_lock_mismatch")
    for name, record in records.items():
        item = locked[name]
        if record.version != item.version or record.sha256 != item.sha256:
            raise RuntimePackError("runtime_pack_wheelhouse_lock_mismatch")

    try:
        validate_offline_runtime_lock_for_runtime(
            lock,
            expected_variant=platform_variant,
            expected_python_version=python_version,
            semantic_graph={},
            binary_versions=None,
            root_requirements=projection.requirements,
        )
    except OfflineLockError as exc:
        raise RuntimePackError(exc.code) from exc

    return lock, projection, records


def _validate_native_abi_for_variant(
    native_abi: str,
    platform_variant: str,
) -> None:
    _validate_native_abi_for_variant(
        native_abi,
        platform_variant,
    )
    has_cuda_identity = re.search(
        r"(?:^|-)cuda\d+(?:\.\d+)?(?:-|$)",
        native_abi,
    ) is not None
    has_arch_identity = re.search(
        r"(?:^|-)sm\d+(?:-|$)",
        native_abi,
    ) is not None
    if platform_variant.endswith("-cuda"):
        if not has_cuda_identity or not has_arch_identity:
            raise RuntimePackError(
                "runtime_pack_cuda_native_abi_incomplete"
            )
    elif has_cuda_identity or has_arch_identity:
        raise RuntimePackError(
            "runtime_pack_cpu_native_abi_contains_cuda"
        )


def build_runtime_pack(
    *,
    wheelhouse: Path,
    lock_path: Path,
    requirements_path: Path,
    platform_variant: str,
    python_version: str,
    native_abi: str,
    python_installer: Path | None,
    assembled_from_commit: str,
    output: Path,
) -> dict[str, object]:
    if not native_abi or native_abi != native_abi.strip():
        raise RuntimePackError("runtime_pack_native_abi_invalid")
    if not _SHA1_RE.fullmatch(assembled_from_commit):
        raise RuntimePackError("runtime_pack_source_commit_invalid")
    if platform_variant.startswith("windows-") and python_installer is None:
        raise RuntimePackError("runtime_pack_python_installer_required")
    if python_installer is not None and not platform_variant.startswith("windows-"):
        raise RuntimePackError("runtime_pack_python_installer_platform_mismatch")

    lock, projection, records = _load_runtime_inputs(
        wheelhouse=wheelhouse,
        lock_path=lock_path,
        requirements_path=requirements_path,
        platform_variant=platform_variant,
        python_version=python_version,
    )
    lock_sha = sha256_file(lock_path)
    requirements_sha = runtime_requirements_sha256(projection)
    pack_id = runtime_pack_id(
        RuntimePackIdentityInputs(
            platform_variant=platform_variant,
            python_version=python_version,
            third_party_lock_sha256=lock_sha,
            runtime_requirements_sha256=requirements_sha,
            native_abi=native_abi,
        )
    )

    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise RuntimePackError("runtime_pack_destination_not_empty")
        preexisting_empty_output = True
    else:
        preexisting_empty_output = False
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    published = False
    try:
        artifacts: list[RuntimePackArtifact] = []
        for name in sorted(records):
            record = records[name]
            artifacts.append(
                _copy_artifact(
                    stage,
                    record.path,
                    f"wheels/{record.path.name}",
                    purpose="third-party-python-wheel",
                    package=record.name,
                    version=record.version,
                )
            )
        artifacts.append(
            _copy_artifact(
                stage,
                lock_path,
                f"runtime/{platform_variant}.lock",
                purpose="third-party-runtime-lock",
            )
        )
        artifacts.append(
            _copy_artifact(
                stage,
                requirements_path,
                f"runtime/{platform_variant}.requirements.txt",
                purpose="application-runtime-requirements",
            )
        )
        if python_installer is not None:
            artifacts.append(
                _copy_artifact(
                    stage,
                    python_installer,
                    f"prerequisites/python/{python_installer.name}",
                    purpose="python-runtime-installer",
                    package="cpython",
                    version=python_version,
                )
            )

        manifest: dict[str, object] = {
            "schemaVersion": _SCHEMA,
            "runtimePackId": pack_id,
            "platformVariant": platform_variant,
            "pythonVersion": python_version,
            "nativeAbi": native_abi,
            "thirdPartyLockSha256": lock_sha,
            "runtimeRequirementsSha256": requirements_sha,
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
        (stage / "runtime-pack-manifest.json").write_bytes(manifest_bytes)

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
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--lock", dest="lock_path", type=Path, required=True)
    parser.add_argument("--requirements", dest="requirements_path", type=Path, required=True)
    parser.add_argument("--platform-variant", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--native-abi", required=True)
    parser.add_argument("--python-installer", type=Path)
    parser.add_argument("--assembled-from-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        manifest = build_runtime_pack(
            wheelhouse=args.wheelhouse,
            lock_path=args.lock_path,
            requirements_path=args.requirements_path,
            platform_variant=args.platform_variant,
            python_version=args.python_version,
            native_abi=args.native_abi,
            python_installer=args.python_installer,
            assembled_from_commit=args.assembled_from_commit,
            output=args.output,
        )
    except RuntimePackError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
