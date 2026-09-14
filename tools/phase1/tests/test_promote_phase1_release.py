from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "promote_phase1_release.py"
SPEC = importlib.util.spec_from_file_location("phase1_promotion", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def evidence(path: Path, commit: str, passed=True) -> Path:
    value = {
        "sourceCommit": commit,
        "targetVerifiedManifestSha256": "c" * 64,
        "result": {"passed": passed, "failureCodes": [] if passed else ["failed"]},
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_gate_evidence_requires_exact_source_commit(tmp_path: Path):
    path = evidence(tmp_path / "e.json", "a" * 40)
    with pytest.raises(mod.PromotionError, match="promotion_evidence_source_mismatch"):
        mod.load_gate_evidence(path, gate="cctv-quality-baseline", expected_source_commit="b" * 40, target_verified_manifest_sha256="c" * 64)


def test_generic_passing_json_cannot_promote_quality_gate(tmp_path: Path):
    path = evidence(tmp_path / "e.json", "a" * 40, passed=True)
    with pytest.raises(mod.PromotionError, match="promotion_evidence_schema_invalid"):
        mod.load_gate_evidence(
            path,
            gate="cctv-quality-baseline",
            expected_source_commit="a" * 40,
            target_verified_manifest_sha256="c" * 64,
        )


def test_gate_argument_rejects_unknown_or_duplicate(tmp_path: Path):
    with pytest.raises(mod.PromotionError, match="promotion_gate_argument_invalid"):
        mod.parse_gate_arguments(["unknown=x.json"])
    with pytest.raises(mod.PromotionError, match="promotion_gate_argument_invalid"):
        mod.parse_gate_arguments([
            "cctv-quality-baseline=a.json",
            "cctv-quality-baseline=b.json",
        ])


def test_runtime_ready_requires_all_four_qualified_variants_and_locks():
    variants = {}
    locks = {}
    for variant in (
        "windows-x86_64-cpu",
        "windows-x86_64-cuda",
        "linux-x86_64-cpu",
        "linux-x86_64-cuda",
    ):
        variants[variant] = {
            "status": "qualified-hardware" if variant.endswith("-cuda") else "qualified-hosted-cpu"
        }
        locks[variant] = {"status": "qualified-offline-lock"}
    mod._assert_runtime_ready({
        "qualificationStatus": "qualified",
        "platformVariants": variants,
        "releaseLocks": locks,
    })
    variants["linux-x86_64-cuda"]["status"] = "pending-hardware-qualification"
    with pytest.raises(mod.PromotionError, match="promotion_runtime_variant_not_qualified"):
        mod._assert_runtime_ready({
            "qualificationStatus": "qualified",
            "platformVariants": variants,
            "releaseLocks": locks,
        })
