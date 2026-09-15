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


def policy() -> dict:
    return {
        "mode": "qualification",
        "qualificationCorpusManifestSha256": "9" * 64,
        "classThresholds": {
            "Person": {"precision": 0.8, "recall": 0.8, "f1": 0.8},
            "Vehicle": {"precision": 0.8, "recall": 0.8, "f1": 0.8},
        },
        "performanceThresholds": {
            "minimumProcessingFps": 10.0,
            "maximumP95LatencyMs": 1000.0,
            "maximumSoakGrowthBytes": 20,
        },
    }


def evidence(path: Path, commit: str, passed: bool = True) -> Path:
    value = {
        "sourceCommit": commit,
        "targetVerifiedManifestSha256": "c" * 64,
        "result": {"passed": passed, "failureCodes": [] if passed else ["failed"]},
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def validation_kwargs(tmp_path: Path) -> dict:
    return {
        "acceptance_profile": policy(),
        "quality_corpus_manifest": tmp_path / "corpus.json",
        "quality_case_evidence": {},
        "quality_ground_truth": {},
        "expected_mavi_build": "build-a",
    }


def test_gate_evidence_requires_exact_source_commit(tmp_path: Path):
    path = evidence(tmp_path / "e.json", "a" * 40)
    with pytest.raises(mod.PromotionError, match="promotion_evidence_source_mismatch"):
        mod.load_gate_evidence(
            path,
            gate="cctv-quality-baseline",
            expected_source_commit="b" * 40,
            target_verified_manifest_sha256="c" * 64,
            acceptance_profile_sha256="d" * 64,
            **validation_kwargs(tmp_path),
        )


def test_generic_passing_json_cannot_promote_quality_gate(tmp_path: Path):
    path = evidence(tmp_path / "e.json", "a" * 40, passed=True)
    with pytest.raises(mod.PromotionError, match="promotion_quality_invalid:"):
        mod.load_gate_evidence(
            path,
            gate="cctv-quality-baseline",
            expected_source_commit="a" * 40,
            target_verified_manifest_sha256="c" * 64,
            acceptance_profile_sha256="d" * 64,
            **validation_kwargs(tmp_path),
        )


def test_gate_argument_rejects_unknown_or_duplicate():
    with pytest.raises(mod.PromotionError, match="promotion_gate_argument_invalid"):
        mod.parse_gate_arguments(["unknown=x.json"])
    with pytest.raises(mod.PromotionError, match="promotion_gate_argument_invalid"):
        mod.parse_gate_arguments([
            "cctv-quality-baseline=a.json",
            "cctv-quality-baseline=b.json",
        ])


def qualified_runtime() -> dict:
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
    return {
        "qualificationStatus": "qualified",
        "platformVariants": variants,
        "releaseLocks": locks,
    }


def test_runtime_ready_requires_all_four_qualified_variants_and_locks():
    value = qualified_runtime()
    mod._assert_runtime_ready(value)
    value["platformVariants"]["linux-x86_64-cuda"]["status"] = "pending-hardware-qualification"
    with pytest.raises(mod.PromotionError, match="promotion_runtime_variant_not_qualified"):
        mod._assert_runtime_ready(value)


def test_promotion_reopens_every_gate_even_if_qualification_record_already_says_passed(tmp_path: Path):
    gates = {gate: "passed" for gate in mod.MANDATORY_QUALIFICATION_GATES}
    qualification = {
        "qualificationId": "q1",
        "overallResult": "pending",
        "requiredGates": gates,
        "evidence": {gate: {"kind": "old", "reference": "old", "sha256": "a" * 64} for gate in gates},
    }
    with pytest.raises(mod.PromotionError, match="promotion_evidence_missing"):
        mod.build_promoted_metadata(
            manifest_raw={"verificationStatus": "unverified", "qualificationId": None},
            qualification_raw=qualification,
            runtime_raw=qualified_runtime(),
            gate_evidence={},
            expected_source_commit="a" * 40,
            acceptance_profile_sha256="b" * 64,
            acceptance_profile=policy(),
            quality_corpus_manifest=tmp_path / "corpus.json",
            quality_case_evidence={},
            quality_ground_truth={},
            expected_mavi_build="build-a",
        )


def test_quality_gate_surfaces_independent_corpus_validation_failure(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        mod.quality_corpus,
        "validate_quality_corpus_evidence",
        lambda *_, **__: (_ for _ in ()).throw(
            mod.quality_corpus.QualityCorpusError(
                "quality_corpus_evidence_recalculation_mismatch"
            )
        ),
    )
    with pytest.raises(
        mod.PromotionError,
        match="promotion_quality_invalid:quality_corpus_evidence_recalculation_mismatch",
    ):
        mod._validate_quality_evidence(
            {"schemaVersion": "mavi-cctv-quality-corpus-evidence-v1"},
            "b" * 40,
            "c" * 64,
            policy(),
            tmp_path / "corpus.json",
            {},
            {},
            "build-a",
            "d" * 64,
        )


def test_performance_gate_rejects_wrong_frozen_profile_hash(monkeypatch):
    value = {
        "acceptanceProfileSha256": "a" * 64,
        "maviBuild": "build-a",
        "result": {"passed": True, "failureCodes": []},
    }
    monkeypatch.setattr(mod, "_validate_schema", lambda *_: None)
    with pytest.raises(mod.PromotionError, match="promotion_performance_profile_mismatch"):
        mod._validate_performance_evidence(value, "c" * 64, policy(), "build-a")


def test_performance_gate_rejects_forged_easier_thresholds(monkeypatch):
    value = {
        "acceptanceProfileSha256": "a" * 64,
        "maviBuild": "build-a",
        "thresholds": {
            "minimumProcessingFps": 1.0,
            "maximumP95LatencyMs": 99999.0,
            "maximumSoakGrowthBytes": 99999,
        },
        "processingFps": 2.0,
        "p95EndToEndLatencyMs": 5000.0,
        "memoryGrowthBytes": 5000,
        "result": {"passed": True, "failureCodes": []},
    }
    monkeypatch.setattr(mod, "_validate_schema", lambda *_: None)
    with pytest.raises(mod.PromotionError, match="promotion_performance_thresholds_mismatch"):
        mod._validate_performance_evidence(value, "a" * 64, policy(), "build-a")


def test_offline_aggregate_rejects_cross_spliced_variant_evidence(tmp_path: Path):
    cpu = tmp_path / "cpu.json"
    cuda = tmp_path / "cuda.json"
    aggregate = tmp_path / "offline.json"
    cpu.write_text('{"variant":"windows-x86_64-cpu"}', encoding="utf-8")
    cuda.write_text('{"variant":"windows-x86_64-cuda"}', encoding="utf-8")
    aggregate.write_text(json.dumps({
        "variantEvidenceSha256": {
            "windows-x86_64-cpu": mod.sha256_file_bytes(cpu),
            "windows-x86_64-cuda": "0" * 64,
        }
    }), encoding="utf-8")
    gates = {
        "windows-x86_64-cpu": cpu,
        "windows-x86_64-cuda": cuda,
        "windows-offline-install": aggregate,
    }
    with pytest.raises(
        mod.PromotionError,
        match="promotion_offline_variant_evidence_binding_mismatch",
    ):
        mod._validate_offline_aggregate_bindings(gates)
