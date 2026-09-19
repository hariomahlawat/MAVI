#!/usr/bin/env python3
"""Freeze one prepared wheelhouse into MAVI's deterministic offline lock format."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import parse_tag
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
if str(VISION_ROOT) not in sys.path:
    sys.path.insert(0, str(VISION_ROOT))

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from vision_package_bootstrap import (  # noqa: E402
    install_lightweight_vision_package,
)

# Must run before the first `mavi_vision` import: the package's eager
# re-exports would otherwise pull in NumPy and Torch, which this tool
# exists to help acquire.
install_lightweight_vision_package()

from mavi_vision.runtime.offline_lock import (  # noqa: E402
    LockedDistribution,
    OfflineLockError,
    OfflineRuntimeLock,
    canonicalize_distribution_name,
    serialize_offline_runtime_lock,
    validate_accelerator_distribution_versions,
)


class FreezeOfflineLockError(ValueError):
    """Stable build-time failure while inspecting a prepared wheelhouse."""


@dataclass(frozen=True, slots=True)
class WheelRecord:
    path: Path
    name: str
    version: str
    sha256: str
    tags: tuple[tuple[str, str, str], ...]
    requires_python: str | None
    requires_dist: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise FreezeOfflineLockError("wheel_unreadable") from exc
    return digest.hexdigest()


def _parse_wheel_filename(
    path: Path,
) -> tuple[str, Version, tuple[tuple[str, str, str], ...]]:
    if path.suffix.lower() != ".whl":
        raise FreezeOfflineLockError("non_wheel_entry")
    try:
        distribution, version, _build, tags = parse_wheel_filename(path.name)
    except InvalidWheelFilename as exc:
        raise FreezeOfflineLockError("wheel_filename_invalid") from exc
    return (
        canonicalize_distribution_name(str(distribution)),
        version,
        tuple(
            sorted(
                (tag.interpreter, tag.abi, tag.platform)
                for tag in tags
            )
        ),
    )


def _target_python_identity(python_version: str) -> tuple[int, int]:
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.[0-9]+", python_version)
    if match is None:
        raise FreezeOfflineLockError("wheel_python_identity_invalid")
    return int(match.group(1)), int(match.group(2))


def _target_marker_environment(
    *,
    platform_variant: str,
    python_version: str,
    extra: str,
) -> dict[str, str]:
    major, minor = _target_python_identity(python_version)
    if platform_variant.startswith("linux-x86_64-"):
        os_name = "posix"
        sys_platform = "linux"
        platform_system = "Linux"
        platform_machine = "x86_64"
    elif platform_variant.startswith("windows-x86_64-"):
        os_name = "nt"
        sys_platform = "win32"
        platform_system = "Windows"
        platform_machine = "AMD64"
    else:
        raise FreezeOfflineLockError("wheel_platform_variant_invalid")

    return {
        "implementation_name": "cpython",
        "implementation_version": python_version,
        "os_name": os_name,
        "platform_machine": platform_machine,
        "platform_release": "",
        "platform_system": platform_system,
        "platform_version": "",
        "python_full_version": python_version,
        "platform_python_implementation": "CPython",
        "python_version": f"{major}.{minor}",
        "sys_platform": sys_platform,
        "extra": extra,
    }


def _validated_requires_python(message) -> str | None:
    values = message.get_all("Requires-Python", [])
    if len(values) > 1:
        raise FreezeOfflineLockError("wheel_metadata_invalid")
    if not values:
        return None

    value = str(values[0]).strip()
    if not value:
        raise FreezeOfflineLockError("wheel_metadata_invalid")
    try:
        SpecifierSet(value)
    except InvalidSpecifier as exc:
        raise FreezeOfflineLockError("wheel_metadata_invalid") from exc
    return value


def _validated_requires_dist(message) -> tuple[str, ...]:
    requirements: list[str] = []
    for raw_value in message.get_all("Requires-Dist", []):
        value = str(raw_value).strip()
        if not value:
            raise FreezeOfflineLockError("wheel_metadata_invalid")
        try:
            Requirement(value)
        except InvalidRequirement as exc:
            raise FreezeOfflineLockError("wheel_metadata_invalid") from exc
        requirements.append(value)
    return tuple(requirements)


def _requirement_applies(
    requirement: Requirement,
    *,
    platform_variant: str,
    python_version: str,
    extra: str,
) -> bool:
    marker = requirement.marker
    if marker is None:
        return True

    marker_text = str(marker)
    if re.search(r"\b(?:platform_release|platform_version)\b", marker_text):
        raise FreezeOfflineLockError("wheel_dependency_marker_unsupported")

    environment = _target_marker_environment(
        platform_variant=platform_variant,
        python_version=python_version,
        extra=extra,
    )
    return marker.evaluate(environment=environment, context="requirement")


def validate_wheelhouse_dependency_closure(
    records: dict[str, WheelRecord],
    *,
    platform_variant: str,
    python_version: str,
) -> None:
    pending = [(name, "") for name in sorted(records)]
    processed: set[tuple[str, str]] = set()

    while pending:
        name, extra = pending.pop(0)
        context = (name, extra)
        if context in processed:
            continue
        processed.add(context)

        record = records[name]
        for raw_requirement in record.requires_dist:
            requirement = Requirement(raw_requirement)
            if not _requirement_applies(
                requirement,
                platform_variant=platform_variant,
                python_version=python_version,
                extra=extra,
            ):
                continue
            if requirement.url is not None:
                raise FreezeOfflineLockError(
                    "wheel_dependency_direct_url_forbidden"
                )

            dependency_name = canonicalize_distribution_name(requirement.name)
            dependency = records.get(dependency_name)
            if dependency is None:
                raise FreezeOfflineLockError("wheel_dependency_missing")

            dependency_version = Version(dependency.version)
            if requirement.specifier and not requirement.specifier.contains(
                dependency_version,
                prereleases=None,
            ):
                raise FreezeOfflineLockError(
                    "wheel_dependency_version_mismatch"
                )

            for requested_extra in sorted(requirement.extras):
                pending.append(
                    (
                        dependency_name,
                        canonicalize_name(requested_extra),
                    )
                )


def _pure_python_tag_compatible(
    python_tag: str,
    *,
    major: int,
    minor: int,
) -> bool:
    if python_tag == f"py{major}":
        return True
    match = re.fullmatch(r"py([0-9])([0-9]+)", python_tag)
    return (
        match is not None
        and int(match.group(1)) == major
        and int(match.group(2)) <= minor
    )


def _interpreter_tag_compatible(
    python_tag: str,
    abi_tag: str,
    *,
    major: int,
    minor: int,
) -> bool:
    if abi_tag == "none" and _pure_python_tag_compatible(
        python_tag,
        major=major,
        minor=minor,
    ):
        return True
    if python_tag == f"cp{major}{minor}":
        return True
    abi_match = re.fullmatch(r"cp([0-9])([0-9]+)", python_tag)
    return (
        abi_match is not None
        and abi_tag == "abi3"
        and int(abi_match.group(1)) == major == 3
        and 2 <= int(abi_match.group(2)) <= minor
    )


def _python_abi_pair_compatible(
    python_tag: str,
    abi_tag: str,
    *,
    major: int,
    minor: int,
) -> bool:
    if abi_tag == "none" and _pure_python_tag_compatible(
        python_tag,
        major=major,
        minor=minor,
    ):
        return True
    if python_tag == f"cp{major}{minor}":
        return abi_tag in {f"cp{major}{minor}", "abi3", "none"}

    abi_match = re.fullmatch(r"cp([0-9])([0-9]+)", python_tag)
    return (
        abi_match is not None
        and abi_tag == "abi3"
        and int(abi_match.group(1)) == major == 3
        and 2 <= int(abi_match.group(2)) <= minor
    )


def _platform_tag_compatible(
    platform_tag: str,
    *,
    platform_variant: str,
) -> bool:
    if platform_tag == "any":
        return True
    if platform_variant.startswith("linux-x86_64-"):
        if platform_tag == "linux_x86_64":
            return True
        if platform_tag in {
            "manylinux1_x86_64",
            "manylinux2010_x86_64",
            "manylinux2014_x86_64",
        }:
            return True
        manylinux = re.fullmatch(
            r"manylinux_([0-9]+)_([0-9]+)_x86_64",
            platform_tag,
        )
        if manylinux is None:
            return False
        glibc_major = int(manylinux.group(1))
        glibc_minor = int(manylinux.group(2))
        return glibc_major == 2 and 5 <= glibc_minor <= 39
    if platform_variant.startswith("windows-x86_64-"):
        return platform_tag == "win_amd64"
    raise FreezeOfflineLockError("wheel_platform_variant_invalid")


def _wheel_tag_triple_compatible(
    python_tag: str,
    abi_tag: str,
    platform_tag: str,
    *,
    platform_variant: str,
    major: int,
    minor: int,
) -> bool:
    if not _python_abi_pair_compatible(
        python_tag,
        abi_tag,
        major=major,
        minor=minor,
    ):
        return False
    if not _platform_tag_compatible(
        platform_tag,
        platform_variant=platform_variant,
    ):
        return False
    if platform_tag == "any" and abi_tag != "none":
        return False
    return True


def validate_wheel_record_for_target(
    record: WheelRecord,
    *,
    platform_variant: str,
    python_version: str,
) -> None:
    major, minor = _target_python_identity(python_version)
    if record.requires_python is not None:
        requires_python = SpecifierSet(record.requires_python)
        if not requires_python.contains(
            Version(python_version),
            prereleases=None,
        ):
            raise FreezeOfflineLockError("wheel_requires_python_incompatible")

    has_interpreter = any(
        _interpreter_tag_compatible(
            python_tag,
            abi_tag,
            major=major,
            minor=minor,
        )
        for python_tag, abi_tag, _platform_tag in record.tags
    )
    if not has_interpreter:
        raise FreezeOfflineLockError("wheel_python_incompatible")

    has_platform = any(
        _platform_tag_compatible(
            platform_tag,
            platform_variant=platform_variant,
        )
        for _python_tag, _abi_tag, platform_tag in record.tags
    )
    if not has_platform:
        raise FreezeOfflineLockError("wheel_platform_incompatible")

    if any(
        _wheel_tag_triple_compatible(
            python_tag,
            abi_tag,
            platform_tag,
            platform_variant=platform_variant,
            major=major,
            minor=minor,
        )
        for python_tag, abi_tag, platform_tag in record.tags
    ):
        return

    raise FreezeOfflineLockError("wheel_tag_incompatible")

def inspect_wheel(path: Path) -> WheelRecord:
    if not path.is_file() or path.suffix.lower() != ".whl":
        raise FreezeOfflineLockError("non_wheel_entry")

    try:
        with zipfile.ZipFile(path, "r") as archive:
            archive_names = archive.namelist()
            metadata_names = [
                name
                for name in archive_names
                if name.endswith(".dist-info/METADATA")
                and name.count("/") == 1
            ]
            if len(metadata_names) != 1:
                raise FreezeOfflineLockError("wheel_metadata_invalid")
            metadata_dir = metadata_names[0].split("/", 1)[0]
            wheel_names = [
                name
                for name in archive_names
                if name == f"{metadata_dir}/WHEEL"
            ]
            record_names = [
                name
                for name in archive_names
                if name == f"{metadata_dir}/RECORD"
            ]
            if len(wheel_names) != 1 or len(record_names) != 1:
                raise FreezeOfflineLockError("wheel_metadata_invalid")
            payload = archive.read(metadata_names[0])
            wheel_payload = archive.read(wheel_names[0])
    except FreezeOfflineLockError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise FreezeOfflineLockError("wheel_invalid") from exc

    message = BytesParser(policy=default).parsebytes(payload)
    raw_name = message.get("Name")
    version = message.get("Version")
    if not raw_name or not version:
        raise FreezeOfflineLockError("wheel_metadata_invalid")

    name = canonicalize_distribution_name(str(raw_name).strip())
    version = str(version).strip()
    if not name or not version:
        raise FreezeOfflineLockError("wheel_metadata_invalid")

    filename_name, filename_version, tags = _parse_wheel_filename(path)
    try:
        metadata_version = Version(version)
    except InvalidVersion as exc:
        raise FreezeOfflineLockError("wheel_metadata_invalid") from exc
    if filename_name != name or filename_version != metadata_version:
        raise FreezeOfflineLockError("wheel_filename_metadata_mismatch")

    if not metadata_dir.endswith(".dist-info"):
        raise FreezeOfflineLockError("wheel_dist_info_identity_mismatch")
    dist_info_identity = metadata_dir[: -len(".dist-info")]
    dist_info_name, separator, dist_info_version = dist_info_identity.rpartition("-")
    if not separator or not dist_info_name or not dist_info_version:
        raise FreezeOfflineLockError("wheel_dist_info_identity_mismatch")
    try:
        parsed_dist_info_version = Version(dist_info_version)
    except InvalidVersion as exc:
        raise FreezeOfflineLockError("wheel_dist_info_identity_mismatch") from exc
    if (
        canonicalize_distribution_name(dist_info_name) != filename_name
        or parsed_dist_info_version != filename_version
    ):
        raise FreezeOfflineLockError("wheel_dist_info_identity_mismatch")

    wheel_message = BytesParser(policy=default).parsebytes(wheel_payload)
    if str(wheel_message.get("Wheel-Version", "")).strip() != "1.0":
        raise FreezeOfflineLockError("wheel_metadata_invalid")
    if str(wheel_message.get("Root-Is-Purelib", "")).strip().lower() not in {
        "true",
        "false",
    }:
        raise FreezeOfflineLockError("wheel_metadata_invalid")
    raw_wheel_tags = [
        str(value).strip()
        for value in wheel_message.get_all("Tag", [])
        if str(value).strip()
    ]
    if not raw_wheel_tags:
        raise FreezeOfflineLockError("wheel_metadata_invalid")
    try:
        wheel_tags = {
            (tag.interpreter, tag.abi, tag.platform)
            for value in raw_wheel_tags
            for tag in parse_tag(value)
        }
    except (TypeError, ValueError) as exc:
        raise FreezeOfflineLockError("wheel_metadata_invalid") from exc
    if wheel_tags != set(tags):
        raise FreezeOfflineLockError("wheel_metadata_invalid")

    requires_python = _validated_requires_python(message)
    requires_dist = _validated_requires_dist(message)

    return WheelRecord(
        path=path,
        name=name,
        version=version,
        sha256=sha256_file(path),
        tags=tags,
        requires_python=requires_python,
        requires_dist=requires_dist,
    )


def freeze_wheelhouse(
    wheelhouse: Path,
    *,
    platform_variant: str,
    python_version: str,
) -> OfflineRuntimeLock:
    if not wheelhouse.is_dir():
        raise FreezeOfflineLockError("wheelhouse_invalid")

    records: list[WheelRecord] = []
    for entry in wheelhouse.iterdir():
        if not entry.is_file() or entry.suffix.lower() != ".whl":
            raise FreezeOfflineLockError("non_wheel_entry")
        record = inspect_wheel(entry)
        validate_wheel_record_for_target(
            record,
            platform_variant=platform_variant,
            python_version=python_version,
        )
        records.append(record)

    if not records:
        raise FreezeOfflineLockError("wheelhouse_empty")

    by_name: dict[str, WheelRecord] = {}
    for record in records:
        if record.name in by_name:
            raise FreezeOfflineLockError("duplicate_distribution")
        by_name[record.name] = record

    validate_wheelhouse_dependency_closure(
        by_name,
        platform_variant=platform_variant,
        python_version=python_version,
    )

    distributions = tuple(
        LockedDistribution(
            name=record.name,
            version=record.version,
            sha256=record.sha256,
        )
        for record in sorted(by_name.values(), key=lambda item: item.name)
    )
    lock = OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant=platform_variant,
        python_version=python_version,
        distributions=distributions,
    )
    try:
        validate_accelerator_distribution_versions(
            lock,
            expected_variant=platform_variant,
        )
    except OfflineLockError as exc:
        raise FreezeOfflineLockError(exc.code) from exc
    return lock


def write_lock(
    output: Path,
    lock: OfflineRuntimeLock,
    *,
    replace: bool,
) -> None:
    payload = serialize_offline_runtime_lock(lock)
    if output.exists():
        try:
            current = output.read_bytes()
        except OSError as exc:
            raise FreezeOfflineLockError("output_unreadable") from exc
        if current == payload:
            return
        if not replace:
            raise FreezeOfflineLockError("output_differs")

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.write_bytes(payload)
    except OSError as exc:
        raise FreezeOfflineLockError("output_unwritable") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze a prepared wheelhouse into a deterministic MAVI lock.",
    )
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--platform-variant", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing differing lock. Never use in reproduction CI.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        lock = freeze_wheelhouse(
            args.wheelhouse,
            platform_variant=args.platform_variant,
            python_version=args.python_version,
        )
        write_lock(args.output, lock, replace=args.replace)
    except FreezeOfflineLockError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
