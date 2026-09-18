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


EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
CONTEXT_SHA = "c" * 64
CONTEXT_STARTED = "2026-09-14T17:59:00Z"


def approved_policy() -> dict:
    return {
        "approvalStatus": "approved",
        "windowsOperationalPlane": {
            "windowsProductName": "Windows Server 2025",
            "windowsVersion": "24H2",
            "windowsBuild": "26100",
            "architecture": "AMD64",
            "iisVersion": "Version 10.0",
            "dotnetRuntimeVersion": "10.0.11",
        },
        "database": {
            "postgresVersion": "18.0",
            "pgvectorVersion": "0.8.1",
        },
        "windowsCudaVisionWorker": {
            "architecture": "AMD64",
            "pythonVersion": "3.12.10",
            "pythonImplementation": "CPython",
            "nvidiaDriverVersion": "580.82",
            "cudaRuntimeVersion": "12.4",
        },
        "windowsCpuVisionWorker": {
            "architecture": "AMD64",
            "pythonVersion": "3.12.10",
            "pythonImplementation": "CPython",
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


def observation(role: str, values: dict, topology: str) -> dict:
    return {
        "schemaVersion": "mavi-production-prerequisite-observation-v1",
        "acceptanceExecutionId": EXECUTION_ID,
        "acceptanceContextSha256": CONTEXT_SHA,
        "role": role,
        "capturedAtUtc": "2026-09-14T18:00:00Z",
        "topologyIdentity": topology,
        "values": dict(values),
    }


def p1_observations(policy: dict) -> dict[str, dict]:
    return {
        "windows-operational-plane": observation(
            "windows-operational-plane",
            policy["windowsOperationalPlane"],
            "1" * 64,
        ),
        "database": observation(
            "database",
            policy["database"],
            "2" * 64,
        ),
        "windows-cuda-vision-worker": observation(
            "windows-cuda-vision-worker",
            policy["windowsCudaVisionWorker"],
            "1" * 64,
        ),
    }


def p2_observations(policy: dict) -> dict[str, dict]:
    return {
        "windows-operational-plane": observation(
            "windows-operational-plane",
            policy["windowsOperationalPlane"],
            "1" * 64,
        ),
        "database": observation(
            "database",
            policy["database"],
            "2" * 64,
        ),
        "linux-vision-worker": observation(
            "linux-vision-worker",
            policy["linuxVisionWorker"],
            "3" * 64,
        ),
    }


def test_pending_prerequisite_policy_cannot_pass():
    policy = approved_policy()
    observations = p1_observations(policy)
    policy["approvalStatus"] = "pending"
    with pytest.raises(
        mod.PrerequisiteEvidenceError,
        match="production_prerequisite_policy_not_approved",
    ):
        mod.validate_observations(
            policy,
            observations,
            tuple(observations),
            acceptance_execution_id=EXECUTION_ID,
            acceptance_context_sha256=CONTEXT_SHA,
            context_started_at=CONTEXT_STARTED,
        )


def test_p1_exact_observations_pass():
    policy = approved_policy()
    observations = p1_observations(policy)
    mod.validate_observations(
        policy,
        observations,
        tuple(observations),
        acceptance_execution_id=EXECUTION_ID,
        acceptance_context_sha256=CONTEXT_SHA,
        context_started_at=CONTEXT_STARTED,
    )


def test_p2_exact_observations_pass():
    policy = approved_policy()
    observations = p2_observations(policy)
    mod.validate_observations(
        policy,
        observations,
        tuple(observations),
        acceptance_execution_id=EXECUTION_ID,
        acceptance_context_sha256=CONTEXT_SHA,
        context_started_at=CONTEXT_STARTED,
    )


def test_unclaimed_profile_observation_is_rejected():
    policy = approved_policy()
    observations = p1_observations(policy)
    observations["linux-vision-worker"] = observation(
        "linux-vision-worker",
        policy["linuxVisionWorker"],
        "3" * 64,
    )
    with pytest.raises(
        mod.PrerequisiteEvidenceError,
        match="production_prerequisite_observation_set_mismatch",
    ):
        mod.validate_observations(
            policy,
            observations,
            (
                "windows-operational-plane",
                "database",
                "windows-cuda-vision-worker",
            ),
            acceptance_execution_id=EXECUTION_ID,
            acceptance_context_sha256=CONTEXT_SHA,
            context_started_at=CONTEXT_STARTED,
        )


def test_mismatched_observed_prerequisite_cannot_pass():
    policy = approved_policy()
    observations = p2_observations(policy)
    observations["linux-vision-worker"]["values"]["nvidiaDriverVersion"] = "different"
    with pytest.raises(
        mod.PrerequisiteEvidenceError,
        match="production_prerequisite_observation_mismatch:linux-vision-worker",
    ):
        mod.validate_observations(
            policy,
            observations,
            tuple(observations),
            acceptance_execution_id=EXECUTION_ID,
            acceptance_context_sha256=CONTEXT_SHA,
            context_started_at=CONTEXT_STARTED,
        )


def test_missing_topology_identity_cannot_pass():
    policy = approved_policy()
    observations = p1_observations(policy)
    del observations["windows-cuda-vision-worker"]["topologyIdentity"]
    with pytest.raises(
        mod.PrerequisiteEvidenceError,
        match="production_prerequisite_policy_not_frozen:windows-cuda-vision-worker",
    ):
        mod.validate_observations(
            policy,
            observations,
            tuple(observations),
            acceptance_execution_id=EXECUTION_ID,
            acceptance_context_sha256=CONTEXT_SHA,
            context_started_at=CONTEXT_STARTED,
        )


def test_stale_observation_before_acceptance_context_cannot_pass():
    policy = approved_policy()
    observations = p1_observations(policy)
    observations["windows-operational-plane"]["capturedAtUtc"] = "2026-09-13T18:00:00Z"
    with pytest.raises(
        mod.PrerequisiteEvidenceError,
        match="production_prerequisite_context_mismatch:windows-operational-plane",
    ):
        mod.validate_observations(
            policy,
            observations,
            tuple(observations),
            acceptance_execution_id=EXECUTION_ID,
            acceptance_context_sha256=CONTEXT_SHA,
            context_started_at=CONTEXT_STARTED,
        )
