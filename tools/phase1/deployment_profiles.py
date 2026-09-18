#!/usr/bin/env python3
"""Canonical Phase-1 deployment-profile policy.

This module is intentionally dependency-light so promotion, prerequisite,
acceptance and closure tooling consume one fail-closed profile contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DEPLOYMENT_PROFILES = (
    ROOT / "config" / "acceptance" / "phase1-deployment-profiles-v1.json"
)

_ALLOWED_PROFILE_IDS = frozenset({"P1", "P2", "P3"})
_ALLOWED_VARIANTS = frozenset(
    {
        "windows-x86_64-cpu",
        "windows-x86_64-cuda",
        "linux-x86_64-cpu",
        "linux-x86_64-cuda",
    }
)
_ALLOWED_PREREQUISITE_ROLES = frozenset(
    {
        "windows-operational-plane",
        "database",
        "windows-cuda-vision-worker",
        "windows-cpu-vision-worker",
        "linux-vision-worker",
    }
)


class DeploymentProfileError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DeploymentProfile:
    profile_id: str
    name: str
    description: str
    runtime_variant: str
    offline_install_gate: str
    quality_gate: str
    performance_gate: str | None
    required_prerequisite_roles: tuple[str, ...]
    vision_host_role: str
    requires_cuda: bool

    @property
    def qualification_gates(self) -> frozenset[str]:
        gates = {
            self.runtime_variant,
            self.offline_install_gate,
            self.quality_gate,
        }
        if self.performance_gate is not None:
            gates.add(self.performance_gate)
        return frozenset(gates)

    @property
    def required_runtime_variants(self) -> frozenset[str]:
        return frozenset({self.runtime_variant})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_raw(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentProfileError("deployment_profile_policy_invalid") from exc
    if not isinstance(value, dict):
        raise DeploymentProfileError("deployment_profile_policy_invalid")
    return value


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def load_policy(
    path: Path = CANONICAL_DEPLOYMENT_PROFILES,
) -> tuple[dict[str, DeploymentProfile], str]:
    raw = _load_raw(path)
    if raw.get("schemaVersion") != "mavi-phase1-deployment-profiles-v1":
        raise DeploymentProfileError("deployment_profile_schema_invalid")
    profiles_raw = raw.get("profiles")
    if not isinstance(profiles_raw, dict) or set(profiles_raw) != _ALLOWED_PROFILE_IDS:
        raise DeploymentProfileError("deployment_profile_set_invalid")

    result: dict[str, DeploymentProfile] = {}
    for profile_id in sorted(_ALLOWED_PROFILE_IDS):
        item = profiles_raw.get(profile_id)
        if not isinstance(item, dict):
            raise DeploymentProfileError("deployment_profile_invalid:" + profile_id)
        if item.get("id") != profile_id:
            raise DeploymentProfileError("deployment_profile_id_mismatch:" + profile_id)

        name = item.get("name")
        description = item.get("description")
        runtime_variant = item.get("runtimeVariant")
        offline_install_gate = item.get("offlineInstallGate")
        quality_gate = item.get("qualityGate")
        performance_gate = item.get("performanceGate")
        roles = item.get("requiredPrerequisiteRoles")
        vision_host_role = item.get("visionHostRole")
        requires_cuda = item.get("requiresCuda")

        if not all(
            _nonempty_text(value)
            for value in (
                name,
                description,
                runtime_variant,
                offline_install_gate,
                quality_gate,
                vision_host_role,
            )
        ):
            raise DeploymentProfileError("deployment_profile_text_invalid:" + profile_id)
        if runtime_variant not in _ALLOWED_VARIANTS:
            raise DeploymentProfileError("deployment_profile_variant_invalid:" + profile_id)
        if performance_gate is not None and not _nonempty_text(performance_gate):
            raise DeploymentProfileError("deployment_profile_performance_gate_invalid:" + profile_id)
        if (
            not isinstance(roles, list)
            or not roles
            or len(set(roles)) != len(roles)
            or any(role not in _ALLOWED_PREREQUISITE_ROLES for role in roles)
        ):
            raise DeploymentProfileError("deployment_profile_roles_invalid:" + profile_id)
        if vision_host_role not in roles:
            raise DeploymentProfileError("deployment_profile_vision_role_invalid:" + profile_id)
        if not isinstance(requires_cuda, bool):
            raise DeploymentProfileError("deployment_profile_cuda_flag_invalid:" + profile_id)
        if requires_cuda != runtime_variant.endswith("-cuda"):
            raise DeploymentProfileError("deployment_profile_cuda_variant_mismatch:" + profile_id)

        result[profile_id] = DeploymentProfile(
            profile_id=profile_id,
            name=name,
            description=description,
            runtime_variant=runtime_variant,
            offline_install_gate=offline_install_gate,
            quality_gate=quality_gate,
            performance_gate=performance_gate,
            required_prerequisite_roles=tuple(roles),
            vision_host_role=vision_host_role,
            requires_cuda=requires_cuda,
        )

    if result["P1"].runtime_variant != "windows-x86_64-cuda":
        raise DeploymentProfileError("deployment_profile_p1_contract_invalid")
    if result["P2"].runtime_variant != "linux-x86_64-cuda":
        raise DeploymentProfileError("deployment_profile_p2_contract_invalid")
    if result["P3"].runtime_variant != "windows-x86_64-cpu":
        raise DeploymentProfileError("deployment_profile_p3_contract_invalid")

    return result, _sha256_file(path)


def select_profile(
    profile_id: str,
    path: Path = CANONICAL_DEPLOYMENT_PROFILES,
) -> tuple[DeploymentProfile, str]:
    profiles, policy_sha = load_policy(path)
    try:
        return profiles[profile_id], policy_sha
    except KeyError as exc:
        raise DeploymentProfileError(
            "deployment_profile_unknown:" + profile_id
        ) from exc


def required_qualification_gates(
    profile_ids: Iterable[str],
    path: Path = CANONICAL_DEPLOYMENT_PROFILES,
) -> tuple[frozenset[str], str]:
    profiles, policy_sha = load_policy(path)
    selected = tuple(profile_ids)
    if not selected or len(set(selected)) != len(selected):
        raise DeploymentProfileError("deployment_profile_selection_invalid")
    gates: set[str] = set()
    for profile_id in selected:
        try:
            gates.update(profiles[profile_id].qualification_gates)
        except KeyError as exc:
            raise DeploymentProfileError(
                "deployment_profile_unknown:" + profile_id
            ) from exc
    return frozenset(gates), policy_sha


def required_runtime_variants(
    profile_ids: Iterable[str],
    path: Path = CANONICAL_DEPLOYMENT_PROFILES,
) -> tuple[frozenset[str], str]:
    profiles, policy_sha = load_policy(path)
    selected = tuple(profile_ids)
    if not selected or len(set(selected)) != len(selected):
        raise DeploymentProfileError("deployment_profile_selection_invalid")
    variants: set[str] = set()
    for profile_id in selected:
        try:
            variants.update(profiles[profile_id].required_runtime_variants)
        except KeyError as exc:
            raise DeploymentProfileError(
                "deployment_profile_unknown:" + profile_id
            ) from exc
    return frozenset(variants), policy_sha
