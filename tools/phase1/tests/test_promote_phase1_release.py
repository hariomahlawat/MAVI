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
        "deployment_profile_id": "P1",
        "deployment_profile_policy_sha256": "f" * 64,
        "runtime_variant": "windows-x86_64-cuda",
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


def test_runtime_ready_checks_only_selected_profile_variant():
    value = qualified_runtime()
    value["platformVariants"]["linux-x86_64-cuda"]["status"] = "pending-hardware-qualification"

    # P1 does not inherit or depend on P2 Linux-CUDA qualification.
    mod._assert_runtime_ready(value, frozenset({"windows-x86_64-cuda"}))

    value["platformVariants"]["windows-x86_64-cuda"]["status"] = "pending-hardware-qualification"
    with pytest.raises(
        mod.PromotionError,
        match="promotion_runtime_variant_not_qualified:windows-x86_64-cuda",
    ):
        mod._assert_runtime_ready(value, frozenset({"windows-x86_64-cuda"}))


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
            deployment_profile_id="P1",
            deployment_profile_policy_sha256="f" * 64,
            required_gates=frozenset({
                "windows-x86_64-cuda",
                "windows-offline-install",
                "cctv-quality-baseline",
            }),
            required_variants=frozenset({"windows-x86_64-cuda"}),
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
        mod._validate_performance_evidence(
            value,
            "c" * 64,
            policy(),
            "build-a",
            deployment_profile_id="P2",
            deployment_profile_policy_sha256="f" * 64,
            runtime_variant="linux-x86_64-cuda",
        )


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
        mod._validate_performance_evidence(
            value,
            "a" * 64,
            policy(),
            "build-a",
            deployment_profile_id="P2",
            deployment_profile_policy_sha256="f" * 64,
            runtime_variant="linux-x86_64-cuda",
        )


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
        mod._validate_offline_aggregate_bindings(
            gates,
            frozenset({"windows-x86_64-cuda"}),
        )


def test_profile_promotion_does_not_require_unclaimed_linux_cuda(tmp_path: Path, monkeypatch):
    runtime = qualified_runtime()
    runtime["qualificationStatus"] = "partial"
    runtime["platformVariants"]["linux-x86_64-cuda"]["status"] = "pending-hardware-qualification"
    runtime["releaseLocks"]["linux-x86_64-cuda"]["status"] = "pending-hardware-qualification"

    required = frozenset({
        "windows-x86_64-cuda",
        "windows-offline-install",
        "cctv-quality-baseline",
    })
    qualification = {
        "qualificationId": "q1",
        "overallResult": "pending",
        "requiredGates": {
            gate: "pending"
            for gate in mod.MANDATORY_QUALIFICATION_GATES
        },
        "evidence": {},
        "qualifiedProfiles": [],
        "profileQualifications": {},
    }

    gate_files = {}
    for gate in required:
        path = tmp_path / (gate + ".json")
        value = {}
        if gate == "windows-offline-install":
            value = {
                "deploymentProfile": "P1",
                "deploymentProfilePolicySha256": "f" * 64,
            }
        path.write_text(json.dumps(value), encoding="utf-8")
        gate_files[gate] = path

    monkeypatch.setattr(
        mod,
        "load_gate_evidence",
        lambda path, **kwargs: {
            "kind": "file",
            "reference": path.name,
            "sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(mod, "_validate_offline_aggregate_bindings", lambda *_: None)
    monkeypatch.setattr(
        mod,
        "build_target_manifest",
        lambda manifest, qualification_id: (
            json.dumps({
                **manifest,
                "verificationStatus": "verified",
                "qualificationId": qualification_id,
            }).encode("utf-8")
        ),
    )
    monkeypatch.setattr(mod, "target_sha256_bytes", lambda *_: "b" * 64)

    _, qualification_bytes = mod.build_promoted_metadata(
        manifest_raw={"verificationStatus": "unverified", "qualificationId": None},
        qualification_raw=qualification,
        runtime_raw=runtime,
        gate_evidence=gate_files,
        expected_source_commit="a" * 40,
        acceptance_profile_sha256="c" * 64,
        acceptance_profile=policy(),
        quality_corpus_manifest=tmp_path / "corpus.json",
        quality_case_evidence={},
        quality_ground_truth={},
        expected_mavi_build="build-a",
        deployment_profile_id="P1",
        deployment_profile_policy_sha256="f" * 64,
        required_gates=required,
        required_variants=frozenset({"windows-x86_64-cuda"}),
    )
    promoted = json.loads(qualification_bytes)
    assert promoted["qualifiedProfiles"] == ["P1"]
    assert promoted["requiredGates"]["linux-x86_64-cuda"] == "pending"
    assert promoted["overallResult"] == "pending"
    assert set(
        promoted["profileQualifications"]["P1"]["evidence"]
    ) == required
    assert (
        promoted["profileQualifications"]["P1"][
            "deploymentProfilePolicySha256"
        ]
        == "f" * 64
    )
    assert (
        promoted["profileQualifications"]["P1"]["runtimeVariant"]
        == "windows-x86_64-cuda"
    )


def _fake_profile_gate_files(
    tmp_path: Path,
    *,
    profile_id: str,
    policy_sha: str,
    required: frozenset[str],
) -> dict[str, Path]:
    result = {}
    for gate in required:
        path = tmp_path / f"{profile_id}-{gate}.json"
        value = {}
        if gate in {"windows-offline-install", "linux-offline-install"}:
            value = {
                "deploymentProfile": profile_id,
                "deploymentProfilePolicySha256": policy_sha,
            }
        path.write_text(json.dumps(value), encoding="utf-8")
        result[gate] = path
    return result


def _patch_profile_evidence_validation(monkeypatch):
    monkeypatch.setattr(
        mod,
        "load_gate_evidence",
        lambda path, **kwargs: {
            "kind": "file",
            "reference": path.name,
            "sha256": mod.sha256_file_bytes(path),
        },
    )
    monkeypatch.setattr(
        mod,
        "_validate_offline_aggregate_bindings",
        lambda *_: None,
    )


def test_additive_promotion_preserves_existing_profile(
    tmp_path: Path,
    monkeypatch,
):
    _patch_profile_evidence_validation(monkeypatch)
    runtime = qualified_runtime()
    policy_sha = "f" * 64

    p1_required = frozenset({
        "windows-x86_64-cuda",
        "windows-offline-install",
        "cctv-quality-baseline",
    })
    initial_qualification = {
        "qualificationId": "q1",
        "overallResult": "pending",
        "requiredGates": {
            gate: "pending"
            for gate in mod.MANDATORY_QUALIFICATION_GATES
        },
        "evidence": {},
        "qualifiedProfiles": [],
        "profileQualifications": {},
    }
    manifest_bytes, q1_bytes = mod.build_promoted_metadata(
        manifest_raw={
            "verificationStatus": "unverified",
            "qualificationId": None,
        },
        qualification_raw=initial_qualification,
        runtime_raw=runtime,
        gate_evidence=_fake_profile_gate_files(
            tmp_path,
            profile_id="P1",
            policy_sha=policy_sha,
            required=p1_required,
        ),
        expected_source_commit="a" * 40,
        acceptance_profile_sha256="c" * 64,
        acceptance_profile=policy(),
        quality_corpus_manifest=tmp_path / "corpus.json",
        quality_case_evidence={},
        quality_ground_truth={},
        expected_mavi_build="build-a",
        deployment_profile_id="P1",
        deployment_profile_policy_sha256=policy_sha,
        required_gates=p1_required,
        required_variants=frozenset({"windows-x86_64-cuda"}),
    )

    verified_manifest = json.loads(manifest_bytes)
    q1 = json.loads(q1_bytes)
    assert verified_manifest["verificationStatus"] == "verified"

    p2_required = frozenset({
        "linux-x86_64-cuda",
        "linux-offline-install",
        "cctv-quality-baseline",
        "linux-nvidia-recovery-performance",
    })
    manifest_bytes_2, q2_bytes = mod.build_promoted_metadata(
        manifest_raw=verified_manifest,
        qualification_raw=q1,
        runtime_raw=runtime,
        gate_evidence=_fake_profile_gate_files(
            tmp_path,
            profile_id="P2",
            policy_sha=policy_sha,
            required=p2_required,
        ),
        expected_source_commit="a" * 40,
        acceptance_profile_sha256="c" * 64,
        acceptance_profile=policy(),
        quality_corpus_manifest=tmp_path / "corpus.json",
        quality_case_evidence={},
        quality_ground_truth={},
        expected_mavi_build="build-a",
        deployment_profile_id="P2",
        deployment_profile_policy_sha256=policy_sha,
        required_gates=p2_required,
        required_variants=frozenset({"linux-x86_64-cuda"}),
        current_manifest_bytes=manifest_bytes,
    )

    assert manifest_bytes_2 == manifest_bytes
    q2 = json.loads(q2_bytes)
    assert q2["qualifiedProfiles"] == ["P1", "P2"]
    assert set(q2["profileQualifications"]) == {"P1", "P2"}
    assert (
        q2["profileQualifications"]["P1"]
        == q1["profileQualifications"]["P1"]
    )
    assert set(
        q2["profileQualifications"]["P2"]["evidence"]
    ) == p2_required


def test_requalifying_same_profile_is_monotonic_and_idempotent_in_index(
    tmp_path: Path,
    monkeypatch,
):
    _patch_profile_evidence_validation(monkeypatch)
    runtime = qualified_runtime()
    policy_sha = "f" * 64
    required = frozenset({
        "windows-x86_64-cpu",
        "windows-offline-install",
        "cctv-quality-baseline",
    })
    initial = {
        "qualificationId": "q1",
        "overallResult": "pending",
        "requiredGates": {
            gate: "pending"
            for gate in mod.MANDATORY_QUALIFICATION_GATES
        },
        "evidence": {},
        "qualifiedProfiles": [],
        "profileQualifications": {},
    }
    manifest_bytes, first_bytes = mod.build_promoted_metadata(
        manifest_raw={
            "verificationStatus": "unverified",
            "qualificationId": None,
        },
        qualification_raw=initial,
        runtime_raw=runtime,
        gate_evidence=_fake_profile_gate_files(
            tmp_path,
            profile_id="P3",
            policy_sha=policy_sha,
            required=required,
        ),
        expected_source_commit="a" * 40,
        acceptance_profile_sha256="c" * 64,
        acceptance_profile=policy(),
        quality_corpus_manifest=tmp_path / "corpus.json",
        quality_case_evidence={},
        quality_ground_truth={},
        expected_mavi_build="build-a",
        deployment_profile_id="P3",
        deployment_profile_policy_sha256=policy_sha,
        required_gates=required,
        required_variants=frozenset({"windows-x86_64-cpu"}),
    )
    first = json.loads(first_bytes)
    _, second_bytes = mod.build_promoted_metadata(
        manifest_raw=json.loads(manifest_bytes),
        qualification_raw=first,
        runtime_raw=runtime,
        gate_evidence=_fake_profile_gate_files(
            tmp_path,
            profile_id="P3",
            policy_sha=policy_sha,
            required=required,
        ),
        expected_source_commit="a" * 40,
        acceptance_profile_sha256="c" * 64,
        acceptance_profile=policy(),
        quality_corpus_manifest=tmp_path / "corpus.json",
        quality_case_evidence={},
        quality_ground_truth={},
        expected_mavi_build="build-a",
        deployment_profile_id="P3",
        deployment_profile_policy_sha256=policy_sha,
        required_gates=required,
        required_variants=frozenset({"windows-x86_64-cpu"}),
        current_manifest_bytes=manifest_bytes,
    )
    second = json.loads(second_bytes)
    assert second["qualifiedProfiles"] == ["P3"]
    assert set(second["profileQualifications"]) == {"P3"}


def test_verified_manifest_cannot_change_qualification_identity(
    tmp_path: Path,
):
    manifest = {
        "verificationStatus": "verified",
        "qualificationId": "q1",
    }
    qualification = {
        "qualificationId": "q2",
        "modelManifestSha256": "a" * 64,
        "overallResult": "pending",
        "requiredGates": {
            gate: "pending"
            for gate in mod.MANDATORY_QUALIFICATION_GATES
        },
        "evidence": {},
        "qualifiedProfiles": [],
        "profileQualifications": {},
    }
    with pytest.raises(
        mod.PromotionError,
        match="promotion_manifest_qualification_mismatch",
    ):
        mod.build_promoted_metadata(
            manifest_raw=manifest,
            qualification_raw=qualification,
            runtime_raw=qualified_runtime(),
            gate_evidence={},
            expected_source_commit="a" * 40,
            acceptance_profile_sha256="c" * 64,
            acceptance_profile=policy(),
            quality_corpus_manifest=tmp_path / "corpus.json",
            quality_case_evidence={},
            quality_ground_truth={},
            expected_mavi_build="build-a",
            deployment_profile_id="P1",
            deployment_profile_policy_sha256="f" * 64,
            required_gates=frozenset(),
            required_variants=frozenset({"windows-x86_64-cuda"}),
            current_manifest_bytes=mod.canonical_json(manifest),
        )


def test_existing_profile_index_cannot_be_dropped(tmp_path: Path):
    qualification = {
        "qualificationId": "q1",
        "modelManifestSha256": "a" * 64,
        "overallResult": "pending",
        "requiredGates": {
            gate: "pending"
            for gate in mod.MANDATORY_QUALIFICATION_GATES
        },
        "evidence": {},
        "qualifiedProfiles": ["P1"],
        "profileQualifications": {},
    }
    with pytest.raises(
        mod.PromotionError,
        match="promotion_existing_profile_index_invalid",
    ):
        mod.build_promoted_metadata(
            manifest_raw={
                "verificationStatus": "verified",
                "qualificationId": "q1",
            },
            qualification_raw=qualification,
            runtime_raw=qualified_runtime(),
            gate_evidence={},
            expected_source_commit="a" * 40,
            acceptance_profile_sha256="c" * 64,
            acceptance_profile=policy(),
            quality_corpus_manifest=tmp_path / "corpus.json",
            quality_case_evidence={},
            quality_ground_truth={},
            expected_mavi_build="build-a",
            deployment_profile_id="P1",
            deployment_profile_policy_sha256="f" * 64,
            required_gates=frozenset(),
            required_variants=frozenset({"windows-x86_64-cuda"}),
            current_manifest_bytes=mod.canonical_json({
                "verificationStatus": "verified",
                "qualificationId": "q1",
            }),
        )
