#!/usr/bin/env python3
"""Build the reusable, third-party-only MAVI Vision Runtime Binary Pack."""

from __future__ import annotations

import argparse
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
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from vision_package_bootstrap import (  # noqa: E402
    install_lightweight_vision_package,
)

# Must run before the first `mavi_vision` import: the package's eager
# re-exports would otherwise pull in NumPy and Torch, which this tool
# exists to help acquire.
install_lightweight_vision_package()

from mavi_vision.runtime.component_identity import (  # noqa: E402
    RuntimePackIdentityInputs,
    runtime_pack_id,
)
from mavi_vision.runtime.offline_lock import (  # noqa: E402
    OfflineLockError,
    load_offline_runtime_lock,
    validate_accelerator_distribution_versions,
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
        validate_accelerator_distribution_versions(
            lock,
            expected_variant=platform_variant,
        )
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


class NativeAbiDerivationError(RuntimePackError):
    """The build contract cannot produce a native ABI identity."""


_CUDA_TOOLKIT_SHAPE = re.compile(r"^\d+\.\d+$")
_MSVC_TOOLSET_SHAPE = re.compile(r"^\d+\.\d+\.\d+$")
_WINDOWS_SDK_SHAPE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_COMPUTE_CAPABILITY_SHAPE = re.compile(r"^\d+\.\d+$")


def derive_native_abi(contract: dict) -> str:
    """Derive the CUDA Runtime Pack's native ABI from the frozen build contract.

    The native ABI exists to make a pack's identity reflect the facts that
    decide whether its native ops will actually run: the platform, the host
    compiler that compiled them, the SDK, the CUDA runtime family and the
    target GPU architecture. Hand-typing that string in a workflow is how it
    drifts away from the toolchain that was actually verified, so it is derived
    from the contract and never written by hand.

    The MSVC toolset is carried at full precision, unlike the CPU pack's
    two-component form, because a CUDA pack's native ops depend on the exact
    toolset build that R1 proved.
    """
    toolchain = contract.get("toolchain")
    if not isinstance(toolchain, dict):
        raise NativeAbiDerivationError("native_abi_contract_toolchain_missing")
    if toolchain.get("verificationStatus") != "verified":
        # An unverified toolchain has no proven identity to name.
        raise NativeAbiDerivationError("native_abi_toolchain_not_verified")

    target = contract.get("targetGpu")
    if not isinstance(target, dict):
        raise NativeAbiDerivationError("native_abi_contract_target_missing")

    fields = {
        "cudaToolkitVersion": (toolchain.get("cudaToolkitVersion"), _CUDA_TOOLKIT_SHAPE),
        "msvcToolset": (toolchain.get("msvcToolset"), _MSVC_TOOLSET_SHAPE),
        "windowsSdkVersion": (toolchain.get("windowsSdkVersion"), _WINDOWS_SDK_SHAPE),
        "computeCapability": (target.get("computeCapability"), _COMPUTE_CAPABILITY_SHAPE),
    }
    for name, (value, shape) in fields.items():
        if not isinstance(value, str) or shape.fullmatch(value) is None:
            raise NativeAbiDerivationError("native_abi_contract_field_invalid:" + name)

    platform_variant = contract.get("platformVariant")
    if platform_variant != "windows-x86_64-cuda":
        raise NativeAbiDerivationError("native_abi_platform_variant_unsupported")

    major, minor = fields["computeCapability"][0].split(".")
    native_abi = (
        "win_amd64"
        f"-msvc-{fields['msvcToolset'][0]}"
        f"-sdk-{fields['windowsSdkVersion'][0]}"
        f"-cuda{fields['cudaToolkitVersion'][0]}"
        f"-sm{major}{minor}"
    )
    # The derived string must satisfy the same rule any supplied one does.
    _validate_native_abi_for_variant(native_abi, platform_variant)
    return native_abi


def _validate_native_abi_for_variant(
    native_abi: str,
    platform_variant: str,
) -> None:
    if not native_abi or native_abi != native_abi.strip():
        raise RuntimePackError("runtime_pack_native_abi_invalid")
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
    _validate_native_abi_for_variant(
        native_abi,
        platform_variant,
    )
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
    # The ABI is derived from the frozen build contract, not typed. A `-cuda`
    # pack's identity is a hash over this string, so a hand-typed one that
    # happens to spell the qualified toolchain while the build used another is
    # a Runtime Pack ID that is wrong about what it identifies.
    parser.add_argument("--native-abi")
    parser.add_argument(
        "--contract",
        type=Path,
        help="build contract to derive --native-abi from; required for a "
        "-cuda variant",
    )
    parser.add_argument("--python-installer", type=Path)
    parser.add_argument("--assembled-from-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _resolve_native_abi(args: argparse.Namespace) -> str:
    if args.contract is not None:
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        derived = derive_native_abi(contract)
        if args.native_abi is not None and args.native_abi != derived:
            # Both were supplied and they disagree. Silently preferring either
            # one would hide exactly the drift this argument exists to catch.
            raise NativeAbiDerivationError("native_abi_contract_conflict")
        return derived
    if args.native_abi is None:
        raise NativeAbiDerivationError("native_abi_not_supplied")
    if args.platform_variant.endswith("-cuda"):
        raise NativeAbiDerivationError("native_abi_contract_required_for_cuda")
    return args.native_abi


def main() -> int:
    args = _parse_args()
    try:
        native_abi = _resolve_native_abi(args)
    except (NativeAbiDerivationError, OSError, json.JSONDecodeError) as exc:
        code = getattr(exc, "code", "native_abi_contract_unreadable")
        print(code, file=sys.stderr)
        return 2
    try:
        manifest = build_runtime_pack(
            wheelhouse=args.wheelhouse,
            lock_path=args.lock_path,
            requirements_path=args.requirements_path,
            platform_variant=args.platform_variant,
            python_version=args.python_version,
            native_abi=native_abi,
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
