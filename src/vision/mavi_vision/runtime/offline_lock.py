from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_SCHEMA = "mavi-offline-lock-v1"
_SUPPORTED_VARIANTS = frozenset(
    {
        "linux-x86_64-cpu",
        "windows-x86_64-cpu",
        "linux-x86_64-cuda",
        "windows-x86_64-cuda",
    }
)
_PYTHON_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.+!_-]*[A-Za-z0-9])?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_REQUIREMENT_TOKENS = (
    "@",
    "://",
    "git+",
    " -e ",
    "--index-url",
    "--extra-index-url",
    "--find-links",
    "--trusted-host",
    "--no-index",
    ";",
)


class OfflineLockError(ValueError):
    """Stable validation failure for deterministic offline runtime locks."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LockedDistribution:
    name: str
    version: str
    sha256: str


@dataclass(frozen=True, slots=True)
class OfflineRuntimeLock:
    schema_version: str
    platform_variant: str
    python_version: str
    distributions: tuple[LockedDistribution, ...]


def canonicalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_offline_runtime_lock(path: Path) -> OfflineRuntimeLock:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise OfflineLockError("offline_lock_unreadable") from exc
    return parse_offline_runtime_lock(payload)


def parse_offline_runtime_lock(payload: bytes) -> OfflineRuntimeLock:
    if payload.startswith(codecs.BOM_UTF8):
        raise OfflineLockError("offline_lock_bom_forbidden")
    if b"\r" in payload:
        raise OfflineLockError("offline_lock_cr_forbidden")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise OfflineLockError("offline_lock_utf8_invalid") from exc

    lines = text.splitlines()
    if len(lines) < 3:
        raise OfflineLockError("offline_lock_header_invalid")

    schema = _parse_header(lines[0], "# schema: ")
    variant = _parse_header(lines[1], "# platform-variant: ")
    python_version = _parse_header(lines[2], "# python-version: ")

    if schema != _SCHEMA:
        raise OfflineLockError("offline_lock_schema_invalid")
    if variant not in _SUPPORTED_VARIANTS:
        raise OfflineLockError("offline_lock_variant_invalid")
    if not _PYTHON_VERSION_RE.fullmatch(python_version):
        raise OfflineLockError("offline_lock_python_version_invalid")

    package_lines = lines[3:]
    if not package_lines:
        raise OfflineLockError("offline_lock_empty")
    if any(not line for line in package_lines):
        raise OfflineLockError("offline_lock_requirement_invalid")

    distributions = tuple(_parse_requirement(line) for line in package_lines)
    names = tuple(item.name for item in distributions)
    if len(set(names)) != len(names):
        raise OfflineLockError("offline_lock_duplicate_distribution")
    if names != tuple(sorted(names)):
        raise OfflineLockError("offline_lock_not_sorted")

    return OfflineRuntimeLock(
        schema_version=schema,
        platform_variant=variant,
        python_version=python_version,
        distributions=distributions,
    )


def serialize_offline_runtime_lock(lock: OfflineRuntimeLock) -> bytes:
    if lock.schema_version != _SCHEMA:
        raise OfflineLockError("offline_lock_schema_invalid")
    if lock.platform_variant not in _SUPPORTED_VARIANTS:
        raise OfflineLockError("offline_lock_variant_invalid")
    if not _PYTHON_VERSION_RE.fullmatch(lock.python_version):
        raise OfflineLockError("offline_lock_python_version_invalid")
    if not lock.distributions:
        raise OfflineLockError("offline_lock_empty")

    names = tuple(item.name for item in lock.distributions)
    if len(set(names)) != len(names):
        raise OfflineLockError("offline_lock_duplicate_distribution")
    if names != tuple(sorted(names)):
        raise OfflineLockError("offline_lock_not_sorted")

    rows = [
        f"# schema: {lock.schema_version}",
        f"# platform-variant: {lock.platform_variant}",
        f"# python-version: {lock.python_version}",
    ]
    for item in lock.distributions:
        canonical = canonicalize_distribution_name(item.name)
        if canonical != item.name or not _NAME_RE.fullmatch(item.name):
            raise OfflineLockError("offline_lock_name_noncanonical")
        if not _valid_exact_version(item.version):
            raise OfflineLockError("offline_lock_requirement_invalid")
        if not _SHA256_RE.fullmatch(item.sha256):
            raise OfflineLockError("offline_lock_hash_invalid")
        rows.append(
            f"{item.name}=={item.version} --hash=sha256:{item.sha256}"
        )
    return ("\n".join(rows) + "\n").encode("utf-8")


def validate_offline_runtime_lock_for_runtime(
    lock: OfflineRuntimeLock,
    *,
    expected_variant: str,
    expected_python_version: str,
    semantic_graph: Mapping[str, str],
    binary_versions: Mapping[str, str] | None,
    platform_status: str | None = None,
) -> None:
    if lock.platform_variant != expected_variant:
        raise OfflineLockError("offline_lock_variant_mismatch")
    if lock.python_version != expected_python_version:
        raise OfflineLockError("offline_lock_python_version_mismatch")

    if platform_status is not None:
        allowed_status = (
            "qualified-hardware"
            if expected_variant.endswith("-cuda")
            else "qualified-hosted-cpu"
        )
        if platform_status != allowed_status:
            raise OfflineLockError("offline_lock_platform_not_qualified")

    by_name = {item.name: item for item in lock.distributions}
    if "mavi-vision" not in by_name:
        raise OfflineLockError("offline_lock_mavi_missing")

    normalized_semantic = {
        canonicalize_distribution_name(name): version
        for name, version in semantic_graph.items()
        if canonicalize_distribution_name(name) != "opencv"
    }
    for name, expected_version in normalized_semantic.items():
        item = by_name.get(name)
        if item is None:
            raise OfflineLockError("offline_lock_semantic_distribution_missing")
        if name in {"torch", "torchvision"} and binary_versions is not None:
            continue
        if item.version != expected_version:
            raise OfflineLockError("offline_lock_semantic_version_mismatch")

    if binary_versions is not None:
        for raw_name, expected_version in binary_versions.items():
            name = canonicalize_distribution_name(raw_name)
            item = by_name.get(name)
            if item is None:
                raise OfflineLockError("offline_lock_semantic_distribution_missing")
            if item.version != expected_version:
                raise OfflineLockError("offline_lock_binary_version_mismatch")


def _parse_header(line: str, prefix: str) -> str:
    if not line.startswith(prefix):
        raise OfflineLockError("offline_lock_header_invalid")
    value = line[len(prefix) :]
    if not value or value != value.strip():
        raise OfflineLockError("offline_lock_header_invalid")
    return value


def _parse_requirement(line: str) -> LockedDistribution:
    lowered = f" {line.lower()} "
    if any(token in lowered for token in _FORBIDDEN_REQUIREMENT_TOKENS):
        raise OfflineLockError("offline_lock_requirement_invalid")

    hash_marker = " --hash="
    if hash_marker not in line:
        if "==" in line:
            raise OfflineLockError("offline_lock_hash_invalid")
        raise OfflineLockError("offline_lock_requirement_invalid")
    if line.count(hash_marker) != 1:
        raise OfflineLockError("offline_lock_requirement_invalid")

    requirement, hash_spec = line.split(hash_marker, 1)
    if not hash_spec.startswith("sha256:"):
        raise OfflineLockError("offline_lock_hash_invalid")
    digest = hash_spec[len("sha256:") :]
    if not _SHA256_RE.fullmatch(digest):
        raise OfflineLockError("offline_lock_hash_invalid")

    if requirement.count("==") != 1:
        raise OfflineLockError("offline_lock_requirement_invalid")
    name, version = requirement.split("==", 1)
    if not name or not version:
        raise OfflineLockError("offline_lock_requirement_invalid")
    if not _NAME_RE.fullmatch(name):
        raise OfflineLockError("offline_lock_requirement_invalid")
    if canonicalize_distribution_name(name) != name:
        raise OfflineLockError("offline_lock_name_noncanonical")
    if not _valid_exact_version(version):
        raise OfflineLockError("offline_lock_requirement_invalid")

    return LockedDistribution(
        name=name,
        version=version,
        sha256=digest,
    )


def _valid_exact_version(version: str) -> bool:
    if not _VERSION_RE.fullmatch(version):
        return False
    return not any(token in version for token in ("*", "<", ">", "=", "~"))


__all__ = [
    "LockedDistribution",
    "OfflineLockError",
    "OfflineRuntimeLock",
    "canonicalize_distribution_name",
    "load_offline_runtime_lock",
    "parse_offline_runtime_lock",
    "serialize_offline_runtime_lock",
    "validate_offline_runtime_lock_for_runtime",
]
