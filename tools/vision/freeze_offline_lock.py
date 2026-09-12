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

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
if str(VISION_ROOT) not in sys.path:
    sys.path.insert(0, str(VISION_ROOT))

from mavi_vision.runtime.offline_lock import (  # noqa: E402
    LockedDistribution,
    OfflineRuntimeLock,
    canonicalize_distribution_name,
    serialize_offline_runtime_lock,
)


class FreezeOfflineLockError(ValueError):
    """Stable build-time failure while inspecting a prepared wheelhouse."""


@dataclass(frozen=True, slots=True)
class WheelRecord:
    path: Path
    name: str
    version: str
    sha256: str
    python_tags: tuple[str, ...]
    abi_tags: tuple[str, ...]
    platform_tags: tuple[str, ...]


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
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if path.suffix.lower() != ".whl":
        raise FreezeOfflineLockError("non_wheel_entry")

    parts = path.name[:-4].split("-")
    if len(parts) not in {5, 6}:
        raise FreezeOfflineLockError("wheel_filename_invalid")
    if len(parts) == 6 and re.fullmatch(r"[0-9][0-9A-Za-z_]*", parts[2]) is None:
        raise FreezeOfflineLockError("wheel_filename_invalid")

    distribution = parts[0]
    version = parts[1]
    python_tag, abi_tag, platform_tag = parts[-3:]
    component_pattern = re.compile(r"[A-Za-z0-9_.+]+")
    if (
        not distribution
        or not version
        or component_pattern.fullmatch(distribution) is None
        or component_pattern.fullmatch(version) is None
        or component_pattern.fullmatch(python_tag) is None
        or component_pattern.fullmatch(abi_tag) is None
        or component_pattern.fullmatch(platform_tag) is None
    ):
        raise FreezeOfflineLockError("wheel_filename_invalid")

    return (
        canonicalize_distribution_name(distribution),
        version,
        tuple(python_tag.split(".")),
        tuple(abi_tag.split(".")),
        tuple(platform_tag.split(".")),
    )


def _python_tags_compatible(
    record: WheelRecord,
    *,
    python_version: str,
) -> bool:
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.[0-9]+", python_version)
    if match is None:
        raise FreezeOfflineLockError("wheel_python_identity_invalid")
    major = int(match.group(1))
    minor = int(match.group(2))

    for tag in record.python_tags:
        if tag == f"py{major}":
            return True
        if tag in {f"py{major}{minor}", f"cp{major}{minor}"}:
            return True
        abi_match = re.fullmatch(r"cp([0-9])([0-9]+)", tag)
        if (
            abi_match is not None
            and "abi3" in record.abi_tags
            and int(abi_match.group(1)) == major
            and int(abi_match.group(2)) <= minor
        ):
            return True
    return False


def _platform_tags_compatible(
    record: WheelRecord,
    *,
    platform_variant: str,
) -> bool:
    if "any" in record.platform_tags:
        return True
    if platform_variant.startswith("linux-x86_64-"):
        return any(
            (
                tag.startswith("linux_")
                or tag.startswith("manylinux")
            )
            and tag.endswith("_x86_64")
            for tag in record.platform_tags
        )
    if platform_variant.startswith("windows-x86_64-"):
        return "win_amd64" in record.platform_tags
    raise FreezeOfflineLockError("wheel_platform_variant_invalid")


def validate_wheel_record_for_target(
    record: WheelRecord,
    *,
    platform_variant: str,
    python_version: str,
) -> None:
    if not _python_tags_compatible(record, python_version=python_version):
        raise FreezeOfflineLockError("wheel_python_incompatible")
    if not _platform_tags_compatible(record, platform_variant=platform_variant):
        raise FreezeOfflineLockError("wheel_platform_incompatible")


def inspect_wheel(path: Path) -> WheelRecord:
    if not path.is_file() or path.suffix.lower() != ".whl":
        raise FreezeOfflineLockError("non_wheel_entry")

    try:
        with zipfile.ZipFile(path, "r") as archive:
            metadata_names = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
                and name.count("/") == 1
            ]
            if len(metadata_names) != 1:
                raise FreezeOfflineLockError("wheel_metadata_invalid")
            payload = archive.read(metadata_names[0])
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

    (
        filename_name,
        filename_version,
        python_tags,
        abi_tags,
        platform_tags,
    ) = _parse_wheel_filename(path)
    if filename_name != name or filename_version != version:
        raise FreezeOfflineLockError("wheel_filename_metadata_mismatch")

    return WheelRecord(
        path=path,
        name=name,
        version=version,
        sha256=sha256_file(path),
        python_tags=python_tags,
        abi_tags=abi_tags,
        platform_tags=platform_tags,
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

    distributions = tuple(
        LockedDistribution(
            name=record.name,
            version=record.version,
            sha256=record.sha256,
        )
        for record in sorted(by_name.values(), key=lambda item: item.name)
    )
    return OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant=platform_variant,
        python_version=python_version,
        distributions=distributions,
    )


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
