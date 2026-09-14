#!/usr/bin/env python3
"""Canonical Task-17 policy identities.

Formal qualification must use repository-owned policy files. A caller-provided
JSON file with a compatible schema is not an accepted substitute.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ACCEPTANCE_PROFILE = (
    ROOT / "config" / "acceptance" / "phase1-acceptance-v1.json"
)
CANONICAL_SUPPORTED_UPDATES = (
    ROOT / "config" / "acceptance" / "phase1-supported-updates-v1.json"
)
CANONICAL_PRODUCTION_PREREQUISITES = (
    ROOT / "config" / "acceptance" / "phase1-production-prerequisites-v1.json"
)


class PolicyIdentityError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_canonical(path: Path, canonical: Path, code: str) -> Path:
    try:
        observed = path.resolve(strict=True)
        expected = canonical.resolve(strict=True)
    except OSError as exc:
        raise PolicyIdentityError(code) from exc
    if observed != expected:
        raise PolicyIdentityError(code)
    return expected


def canonical_acceptance_profile(path: Path) -> tuple[Path, str]:
    resolved = require_canonical(
        path,
        CANONICAL_ACCEPTANCE_PROFILE,
        "acceptance_profile_not_canonical",
    )
    return resolved, sha256_file(resolved)


def canonical_supported_updates(path: Path) -> tuple[Path, str]:
    resolved = require_canonical(
        path,
        CANONICAL_SUPPORTED_UPDATES,
        "supported_updates_policy_not_canonical",
    )
    return resolved, sha256_file(resolved)


def canonical_production_prerequisites(path: Path) -> tuple[Path, str]:
    resolved = require_canonical(
        path,
        CANONICAL_PRODUCTION_PREREQUISITES,
        "production_prerequisite_policy_not_canonical",
    )
    return resolved, sha256_file(resolved)
