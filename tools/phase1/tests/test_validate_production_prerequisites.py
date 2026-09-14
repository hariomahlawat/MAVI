from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "validate_production_prerequisites.py"
)
SPEC = importlib.util.spec_from_file_location(
    "production_prerequisites",
    MODULE_PATH,
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def approved_policy() -> dict:
    return {
        "approvalStatus": "approved",
        "windowsOperationalPlane": {
            "windowsProductName": "Windows Server 2025",
            "windowsVersion": "10.0",
            "windowsBuild": "26100",
            "architecture": "AMD64",
            "iisVersion": "Version 10.0",
            "dotnetRuntimeVersion": "8.0.20",
        },
        "database": {
            "postgresVersion": "17.6",
            "pgvectorVersion": "0.8.1",
        },
        "linuxVisionWorker": {
            "distribution": "ubuntu",
            "release": "24.04",
            "architecture": "x86_64",
            "pythonVersion": "3.12.14",
            "pythonImplementation": "CPython",
            "nvidiaDriverVersion": "580.82.07",
            "cudaRuntimeVersion": "12.4",
        },
    }


def observation(role: str, values: dict) -> dict:
    topology = {
        "windows-operational-plane": "1" * 64,
        "database": "mavi|10.0.0.20|5432",
        "linux-vision-worker": "2" * 64,
    }[role]
    return {
        "schemaVersion": "mavi-production-prerequisite-observation-v1",
        "role": role,
        "capturedAtUtc": "2026-09-14T18:00:00Z",
        "topologyIdentity": topology,
        "values": dict(values),
    }


def observations(policy: dict):
    return (
        observation(
            "windows-operational-plane",
            policy["windowsOperationalPlane"],
        ),
        observation("database", policy["database"]),
        observation(
            "linux-vision-worker",
            policy["linuxVisionWorker"],
        ),
    )


def test_pending_prerequisite_policy_cannot_pass():
    policy = approved_policy()
    policy["approvalStatus"] = "pending"
    windows, database, linux = observations(approved_policy())
    with pytest.raises(
        mod.PrerequisiteEvidenceError,
        match="production_prerequisite_policy_not_approved",
    ):
        mod.validate_observations(policy, windows, database, linux)


def test_mismatched_observed_prerequisite_cannot_pass():
    policy = approved_policy()
    windows, database, linux = observations(policy)
    linux["values"]["nvidiaDriverVersion"] = "different"
    with pytest.raises(
        mod.PrerequisiteEvidenceError,
        match="production_prerequisite_observation_mismatch:linux-vision-worker",
    ):
        mod.validate_observations(policy, windows, database, linux)


def test_exact_approved_observations_pass():
    policy = approved_policy()
    windows, database, linux = observations(policy)
    mod.validate_observations(policy, windows, database, linux)


def test_missing_topology_identity_cannot_pass():
    policy = approved_policy()
    windows, database, linux = observations(policy)
    del linux["topologyIdentity"]
    with pytest.raises(
        mod.PrerequisiteEvidenceError,
        match="production_prerequisite_policy_not_frozen:linux-vision-worker",
    ):
        mod.validate_observations(policy, windows, database, linux)
