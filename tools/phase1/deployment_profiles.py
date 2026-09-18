#!/usr/bin/env python3
"""Phase-1 deployment-profile policy adapter for repository tooling."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
if str(VISION_ROOT) not in sys.path:
    sys.path.insert(0, str(VISION_ROOT))

from mavi_vision.runtime.deployment_profiles import (  # noqa: E402
    DeploymentProfile,
    DeploymentProfileError,
    load_policy as _load_policy,
    required_qualification_gates as _required_qualification_gates,
    required_runtime_variants as _required_runtime_variants,
    select_profile as _select_profile,
)

CANONICAL_DEPLOYMENT_PROFILES = (
    ROOT
    / "config"
    / "acceptance"
    / "phase1-deployment-profiles-v1.json"
)


def load_policy(
    path: Path = CANONICAL_DEPLOYMENT_PROFILES,
) -> tuple[dict[str, DeploymentProfile], str]:
    return _load_policy(path)


def select_profile(
    profile_id: str,
    path: Path = CANONICAL_DEPLOYMENT_PROFILES,
) -> tuple[DeploymentProfile, str]:
    return _select_profile(profile_id, path)


def required_qualification_gates(
    profile_ids: Iterable[str],
    path: Path = CANONICAL_DEPLOYMENT_PROFILES,
) -> tuple[frozenset[str], str]:
    return _required_qualification_gates(profile_ids, path)


def required_runtime_variants(
    profile_ids: Iterable[str],
    path: Path = CANONICAL_DEPLOYMENT_PROFILES,
) -> tuple[frozenset[str], str]:
    return _required_runtime_variants(profile_ids, path)
