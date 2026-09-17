"""Deterministic application runtime-requirements projection."""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

_SCHEMA = "mavi-vision-runtime-requirements-v1"
_SUPPORTED_VARIANTS = frozenset(
    {
        "linux-x86_64-cpu",
        "windows-x86_64-cpu",
        "linux-x86_64-cuda",
        "windows-x86_64-cuda",
    }
)
_PYTHON_VERSION_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")


class RuntimeRequirementsError(ValueError):
    """Stable validation failure while projecting application runtime roots."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RuntimeRequirementsProjection:
    schema_version: str
    platform_variant: str
    python_version: str
    requirements: tuple[str, ...]


def _target_marker_environment(
    *,
    platform_variant: str,
    python_version: str,
) -> dict[str, str]:
    if platform_variant not in _SUPPORTED_VARIANTS:
        raise RuntimeRequirementsError("runtime_requirement_platform_invalid")
    match = _PYTHON_VERSION_RE.fullmatch(python_version)
    if match is None:
        raise RuntimeRequirementsError("runtime_requirement_python_version_invalid")
    try:
        Version(python_version)
    except InvalidVersion as exc:
        raise RuntimeRequirementsError(
            "runtime_requirement_python_version_invalid"
        ) from exc

    major, minor, _patch = match.groups()
    if platform_variant.startswith("windows-x86_64-"):
        os_name = "nt"
        sys_platform = "win32"
        platform_system = "Windows"
        platform_machine = "AMD64"
    else:
        os_name = "posix"
        sys_platform = "linux"
        platform_system = "Linux"
        platform_machine = "x86_64"

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
        "extra": "",
    }


def _normalized_requirement(requirement: Requirement) -> str:
    name = canonicalize_name(requirement.name)
    extras = sorted(canonicalize_name(extra) for extra in requirement.extras)
    rendered_extras = f"[{','.join(extras)}]" if extras else ""
    specifiers = sorted(str(item) for item in requirement.specifier)
    rendered_specifiers = ",".join(specifiers)
    return f"{name}{rendered_extras}{rendered_specifiers}"


def _load_requirement_rows(pyproject_path: Path) -> tuple[str, ...]:
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeRequirementsError("runtime_requirement_pyproject_invalid") from exc

    project = payload.get("project")
    if not isinstance(project, dict):
        raise RuntimeRequirementsError("runtime_requirement_project_missing")

    dependencies = project.get("dependencies", [])
    optional = project.get("optional-dependencies", {})
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise RuntimeRequirementsError("runtime_requirement_dependencies_invalid")
    if not isinstance(optional, dict):
        raise RuntimeRequirementsError("runtime_requirement_optional_invalid")
    vision_runtime = optional.get("vision-runtime", [])
    if not isinstance(vision_runtime, list) or not all(
        isinstance(item, str) for item in vision_runtime
    ):
        raise RuntimeRequirementsError("runtime_requirement_vision_runtime_invalid")

    return tuple(dependencies) + tuple(vision_runtime)


def build_runtime_requirements_projection(
    pyproject_path: Path,
    *,
    platform_variant: str,
    python_version: str,
) -> RuntimeRequirementsProjection:
    environment = _target_marker_environment(
        platform_variant=platform_variant,
        python_version=python_version,
    )
    rendered: list[str] = []
    for raw in _load_requirement_rows(pyproject_path):
        try:
            requirement = Requirement(raw)
        except InvalidRequirement as exc:
            raise RuntimeRequirementsError("runtime_requirement_invalid") from exc
        if requirement.url is not None:
            raise RuntimeRequirementsError(
                "runtime_requirement_direct_url_forbidden"
            )
        marker = requirement.marker
        if marker is not None:
            marker_text = str(marker)
            if re.search(r"\b(?:platform_release|platform_version)\b", marker_text):
                raise RuntimeRequirementsError(
                    "runtime_requirement_marker_unsupported"
                )
            try:
                applies = marker.evaluate(environment=environment)
            except (KeyError, ValueError) as exc:
                raise RuntimeRequirementsError(
                    "runtime_requirement_marker_invalid"
                ) from exc
            if not applies:
                continue
        rendered.append(_normalized_requirement(requirement))

    requirements = tuple(sorted(rendered))
    if not requirements:
        raise RuntimeRequirementsError("runtime_requirement_projection_empty")
    return RuntimeRequirementsProjection(
        schema_version=_SCHEMA,
        platform_variant=platform_variant,
        python_version=python_version,
        requirements=requirements,
    )


def serialize_runtime_requirements_projection(
    projection: RuntimeRequirementsProjection,
) -> bytes:
    if projection.schema_version != _SCHEMA:
        raise RuntimeRequirementsError("runtime_requirement_schema_invalid")
    _target_marker_environment(
        platform_variant=projection.platform_variant,
        python_version=projection.python_version,
    )
    if not projection.requirements:
        raise RuntimeRequirementsError("runtime_requirement_projection_empty")
    if projection.requirements != tuple(sorted(projection.requirements)):
        raise RuntimeRequirementsError("runtime_requirement_projection_not_sorted")
    if any(
        not item or item != item.strip() or "\r" in item or "\n" in item
        for item in projection.requirements
    ):
        raise RuntimeRequirementsError("runtime_requirement_projection_invalid")

    rows = [
        f"# schema: {projection.schema_version}",
        f"# platform-variant: {projection.platform_variant}",
        f"# python-version: {projection.python_version}",
        *projection.requirements,
    ]
    return ("\n".join(rows) + "\n").encode("utf-8")


def runtime_requirements_sha256(
    projection: RuntimeRequirementsProjection,
) -> str:
    return hashlib.sha256(
        serialize_runtime_requirements_projection(projection)
    ).hexdigest()


__all__ = [
    "RuntimeRequirementsError",
    "RuntimeRequirementsProjection",
    "build_runtime_requirements_projection",
    "runtime_requirements_sha256",
    "serialize_runtime_requirements_projection",
]
