from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "deployment_profiles.py"
SPEC = importlib.util.spec_from_file_location("deployment_profiles_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_canonical_profiles_have_expected_variants():
    profiles, policy_sha = mod.load_policy()
    assert set(profiles) == {"P1", "P2", "P3"}
    assert len(policy_sha) == 64
    assert profiles["P1"].runtime_variant == "windows-x86_64-cuda"
    assert profiles["P2"].runtime_variant == "linux-x86_64-cuda"
    assert profiles["P3"].runtime_variant == "windows-x86_64-cpu"


def test_profile_gate_sets_are_independent():
    profiles, _ = mod.load_policy()
    assert profiles["P1"].qualification_gates == {
        "windows-x86_64-cuda",
        "windows-offline-install",
        "cctv-quality-baseline",
    }
    assert profiles["P2"].qualification_gates == {
        "linux-x86_64-cuda",
        "linux-offline-install",
        "cctv-quality-baseline",
        "linux-nvidia-recovery-performance",
    }
    assert profiles["P3"].qualification_gates == {
        "windows-x86_64-cpu",
        "windows-offline-install",
        "cctv-quality-baseline",
    }


def test_profile_selection_rejects_duplicates():
    with pytest.raises(mod.DeploymentProfileError, match="deployment_profile_selection_invalid"):
        mod.required_qualification_gates(["P1", "P1"])


def test_policy_rejects_cuda_flag_variant_mismatch(tmp_path: Path):
    raw = json.loads(mod.CANONICAL_DEPLOYMENT_PROFILES.read_text(encoding="utf-8"))
    raw["profiles"]["P1"]["requiresCuda"] = False
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(
        mod.DeploymentProfileError,
        match="deployment_profile_cuda_variant_mismatch:P1",
    ):
        mod.load_policy(path)
