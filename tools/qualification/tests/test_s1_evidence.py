"""The S1 evidence checker refuses every incomplete or inconsistent PASS.

Each negative test starts from a record the checker accepts in full, breaks
exactly one thing, and asserts the specific finding, so a checker that rejects
everything, or accepts everything, fails this suite.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import s1_evidence
from s1_evidence import UNIT_REQUIREMENTS, UNITS, check_record, invalidated_units, required_variants, suite_counts_from_junit

SHA = "a" * 40
MERGE = "b" * 40
OTHER = "c" * 40
PROFILE_SHA = "503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _value_for(requirement: s1_evidence.MeasurementRequirement) -> float:
    if requirement.limit_op is None:
        return 1024.0
    return {
        "==": requirement.limit_value,
        "<=": requirement.limit_value / 2 if requirement.limit_value else 0.0,
        "<": requirement.limit_value / 2,
        ">=": requirement.limit_value,
        ">": requirement.limit_value + 1,
    }[requirement.limit_op]


def complete_record() -> dict:
    """A record in which every unit is a complete, consistent PASS."""
    record = {
        "schemaVersion": "s1-qualification-evidence-v1",
        "measuredSha": SHA,
        "identity": {
            "profileId": "phase1-detection-tracking-v1",
            "profileVersion": "1.2.0-candidate",
            "profileSha256": PROFILE_SHA,
            "selectorVersion": "evidence-selector-v1-two-tier",
            "scorerVersion": "quality-v2",
            "encoderVersion": "evidence-jpeg-ladder-v1",
            "completionSchemaVersion": "3.0",
            "digestVersion": "3",
        },
        "hosts": {
            "runner-linux": {
                "cpuModel": "AMD EPYC 7763", "physicalCores": 2, "logicalCores": 4, "ramBytes": 16 * 2**30,
                "os": "Ubuntu", "osBuild": "24.04", "stagingFilesystem": "ext4",
                "acceptedEvidenceFilesystem": "ext4", "storageClass": "hosted-runner",
            },
        },
        "runs": {
            "task10": {"kind": "workflow", "workflow": "task10-runtime-qualification.yml", "runId": 1, "headSha": SHA, "conclusion": "success"},
            "quality": {"kind": "workflow", "workflow": "quality-gate.yml", "runId": 2, "headSha": SHA, "conclusion": "success"},
            "host": {"kind": "local", "host": "runner-linux", "command": "python tools/qualification/s1_memory.py", "cleanTree": True, "headSha": SHA, "conclusion": "success"},
        },
        "retainedArtifacts": {},
        "suites": {},
        "pairedVariantSkips": [],
        "measurements": {},
        "units": {},
        "closure": None,
        "disconnected": {
            "runtimeBundleSourceCommit": SHA,
            "maviVisionWheelSha256": "d" * 64,
            "installProfile": "development",
            "variant": "windows-x86_64-cpu",
            "isolationMethod": "adapter disabled",
            "isolationBefore": {"passed": True, "proxyEnvironmentAbsent": True, "probes": [{"host": "1.1.1.1", "port": 443, "reachable": False}]},
            "isolationAfter": {"passed": True, "proxyEnvironmentAbsent": True, "probes": [{"host": "1.1.1.1", "port": 443, "reachable": False}]},
        },
    }
    for name in UNITS:
        required = UNIT_REQUIREMENTS[name]
        unit = {"verdict": "PASS", "suites": [], "measurements": [], "artifacts": [], "nonClaims": []}
        for suite in required.suites:
            for variant in [v or "any" for v in required_variants(required, suite)]:
                suite_id = f"{name}:{suite}:{variant}"
                junit = f"junit:{suite_id}"
                run = "quality" if variant == "any" else "task10"
                record["retainedArtifacts"][junit] = {"path": f"junit/{abs(hash(suite_id))}.xml", "sha256": _sha256(suite_id), "run": run}
                if variant != "any":
                    record["retainedArtifacts"][junit]["variant"] = variant
                record["suites"][suite_id] = {
                    "suite": suite, "variant": variant, "run": run, "junitArtifact": junit,
                    "passed": 1, "skipped": 0, "failed": 0, "errors": 0,
                    "passedTests": [f"{suite}::test_ok"], "skippedTests": [],
                }
                unit["suites"].append(suite_id)
        for requirement in required.measurements:
            measurement_id = f"{name}:{requirement.metric}"
            entry = {"metric": requirement.metric, "value": _value_for(requirement), "unit": requirement.unit, "host": "runner-linux", "run": "host"}
            if requirement.timing:
                entry.update(samples=30, repeats=3, warmupExcluded=True, stats={"min": 10.0, "p50": 20.0, "p95": 30.0, "max": 40.0, "p50RunSpread": 1.0})
            entry["artifact"] = required.artifacts[0]
            if requirement.metric in ("b3.real-store-completion-wall-ms", "b3.worker-request-timeout-ms"):
                entry["artifact"] = "b3.sealing-scale-output"
            if requirement.metric == "b3.worker-request-timeout-ms":
                entry["value"] = 30000.0
            record["measurements"][measurement_id] = entry
            unit["measurements"].append(measurement_id)
        for artifact in required.artifacts:
            record["retainedArtifacts"][artifact] = {"path": f"records/{artifact}.json", "sha256": _sha256(artifact), "run": "host"}
            unit["artifacts"].append(artifact)
        record["units"][name] = unit
    for outcome in s1_evidence.DISCONNECTED_OUTCOMES:
        artifact = f"disconnected.{outcome}"
        record["retainedArtifacts"][artifact] = {"path": f"records/{artifact}.log", "sha256": _sha256(artifact), "run": "host"}
    return record


def codes(record: dict, **options) -> set[tuple[str, str]]:
    # Rule tests are structural unless they supply a repository to verify against.
    options.setdefault("structural_only", "repo_root" not in options)
    return {(finding.unit, finding.code) for finding in check_record(record, **options)}


def structural(record: dict) -> list:
    return check_record(record, structural_only=True)


def _junit_for(entry: dict) -> str:
    cases = [f'<testcase classname="{t.split("::")[0]}" name="{t.split("::", 1)[1]}"/>' for t in entry["passedTests"]]
    cases += [f'<testcase classname="{t.split("::")[0]}" name="{t.split("::", 1)[1]}"><skipped/></testcase>' for t in entry["skippedTests"]]
    name = "" if entry["variant"] == "any" else f' name="{entry["variant"]}"'
    return f'<?xml version="1.0"?><testsuites><testsuite{name}>' + "".join(cases) + "</testsuite></testsuites>"


def _b2_output(record: dict) -> str:
    values = {
        record["measurements"][mid]["metric"]: {"value": record["measurements"][mid]["value"], "unit": record["measurements"][mid]["unit"]}
        for mid in record["units"]["B2"]["measurements"]
    }
    return json.dumps({
        "schema": "s1-b2-memory-derived-v1",
        "identity": {"sourceSha": record["units"]["B2"].get("measuredSha", record["measuredSha"]), "cleanTree": True},
        "measurements": values,
    })


def _disconnected_run(record: dict) -> str:
    return json.dumps({
        "schema": "s1-disconnected-run-v1",
        "sourceCommit": record["units"]["DISCONNECTED"].get("measuredSha", record["measuredSha"]),
        "variant": record["disconnected"]["variant"],
        "installProfile": "development",
        "outboundConnectionAttempts": [],
        "outcomes": {name: {"passed": True, "evidence": f"disconnected.{name}"} for name in s1_evidence.DISCONNECTED_OUTCOMES},
    })


def _sealing_output(record: dict) -> str:
    wall = next(m for m in record["measurements"].values() if m["metric"] == "b3.real-store-completion-wall-ms")
    timeout = next(m for m in record["measurements"].values() if m["metric"] == "b3.worker-request-timeout-ms")
    return json.dumps({
        "status": "complete", "authoritative": True,
        "shape": {"tracks": 10_000, "sealedObjects": 50_000},
        "workerRequestTimeoutMs": timeout["value"],
        "repeats": wall["repeats"], "warmupExcluded": 1, "p50RunSpreadMs": wall["stats"]["p50RunSpread"],
        "completion": {"n": wall["samples"], **{k: wall["stats"][k] for k in ("min", "p50", "p95", "max")}},
    })


def materialize(record: dict, root: Path) -> dict:
    """Write every retained artifact under ``root`` with real content and hashes:
    JUnit XML matching each suite result, and a matching sealing output."""
    by_junit = {entry["junitArtifact"]: entry for entry in record["suites"].values()}
    for artifact_id, entry in record["retainedArtifacts"].items():
        if artifact_id in by_junit:
            content = _junit_for(by_junit[artifact_id])
        elif artifact_id == "b3.sealing-scale-output":
            content = _sealing_output(record)
        elif artifact_id == "b2.memory-harness-output":
            content = _b2_output(record)
        elif artifact_id == "disconnected.run-record":
            content = _disconnected_run(record)
        else:
            content = artifact_id
        path = root / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        entry["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return record


# --------------------------------------------------------------------------- positive


def test_a_complete_record_passes_with_no_finding() -> None:
    assert structural(complete_record()) == []


def test_open_units_may_be_incomplete_and_are_not_errors() -> None:
    record = complete_record()
    record["units"]["B2"] = {"verdict": "OPEN", "suites": [], "measurements": [], "artifacts": [], "nonClaims": []}
    assert structural(record) == []
    # ... and the checker still reports what a PASS would need.
    missing = s1_evidence.open_requirements(record)["B2"]
    assert any("measurement_missing" in line for line in missing)


def test_the_complete_record_is_schema_valid_and_every_unit_is_required() -> None:
    record = complete_record()
    del record["units"]["DISCONNECTED"]
    assert ("record", "schema_invalid") in codes(record)


# --------------------------------------------------------------------------- identity/structure


@pytest.mark.parametrize("field", ["profileSha256", "selectorVersion", "encoderVersion", "digestVersion"])
def test_missing_identity_field_is_refused(field: str) -> None:
    record = complete_record()
    del record["identity"][field]
    assert ("record", "schema_invalid") in codes(record)


def test_missing_host_identity_field_is_refused() -> None:
    record = complete_record()
    del record["hosts"]["runner-linux"]["acceptedEvidenceFilesystem"]
    assert ("record", "schema_invalid") in codes(record)


def test_a_measurement_on_an_unknown_host_is_refused() -> None:
    record = complete_record()
    record["measurements"]["B2:b2.completion-peak-bytes"]["host"] = "somewhere"
    assert ("B2", "host_missing") in codes(record)


def test_an_invalid_verdict_is_refused() -> None:
    record = complete_record()
    record["units"]["B1"]["verdict"] = "PASSED"
    assert ("record", "schema_invalid") in codes(record)


# --------------------------------------------------------------------------- head_sha binding


def test_a_run_on_another_sha_cannot_carry_a_pass() -> None:
    record = complete_record()
    record["runs"]["task10"]["headSha"] = OTHER
    found = codes(record)
    assert ("B1", "head_sha_mismatch") in found
    assert ("B6", "head_sha_mismatch") in found


def test_a_cancelled_or_failed_run_cannot_carry_a_pass() -> None:
    record = complete_record()
    record["runs"]["task10"]["conclusion"] = "cancelled"
    assert ("B6", "run_not_successful") in codes(record)


def test_a_local_run_must_attest_a_clean_tree_and_a_known_host() -> None:
    record = complete_record()
    record["runs"]["host"]["cleanTree"] = False
    assert ("B2", "run_tree_not_clean") in codes(record)
    record = complete_record()
    record["runs"]["host"]["host"] = "unlisted"
    assert ("B2", "host_missing") in codes(record)


def test_a_unit_measured_on_its_own_sha_binds_to_that_sha() -> None:
    record = complete_record()
    record["units"]["B3"]["measuredSha"] = MERGE
    found = codes(record)
    assert ("B3", "head_sha_mismatch") in found
    assert ("B1", "head_sha_mismatch") not in found


# --------------------------------------------------------------------------- suites and skips


def test_a_failed_or_erroring_suite_cannot_carry_a_pass() -> None:
    record = complete_record()
    suite_id = record["units"]["B1"]["suites"][0]
    record["suites"][suite_id]["failed"] = 1
    assert ("B1", "suite_failed") in codes(record)


def test_a_suite_that_passed_nothing_is_not_evidence() -> None:
    record = complete_record()
    suite_id = record["units"]["B4"]["suites"][0]
    record["suites"][suite_id].update(passed=0, passedTests=[])
    assert ("B4", "suite_empty") in codes(record)


def test_an_unpaired_skip_cannot_carry_a_pass() -> None:
    record = complete_record()
    suite_id = record["units"]["B1"]["suites"][2]
    record["suites"][suite_id].update(skipped=1, skippedTests=["tests.test_evidence_encoder::test_golden"])
    assert ("B1", "skip_not_permitted") in codes(record)


def _paired_record(counterpart_passed: bool) -> dict:
    record = complete_record()
    windows = next(sid for sid in record["units"]["B2"]["suites"] if "test_track_lifecycle.py:windows" in sid)
    linux = windows.replace("windows-x86_64-cpu", "linux-x86_64-cpu")
    test = "tests.test_track_lifecycle::test_posix_descriptor_limit"
    record["suites"][windows].update(skipped=1, skippedTests=[test])
    if counterpart_passed:
        record["suites"][linux].update(passed=2, passedTests=[*record["suites"][linux]["passedTests"], test])
    record["pairedVariantSkips"].append({
        "test": test, "skipsOn": "windows-x86_64-cpu",
        "counterpartSuite": "src/vision/tests/test_track_lifecycle.py",
        "counterpartTest": test, "counterpartVariant": "linux-x86_64-cpu",
    })
    return record


def test_a_paired_variant_skip_passes_only_with_its_counterpart_positively_passing() -> None:
    assert structural(_paired_record(counterpart_passed=True)) == []
    assert ("B2", "skip_not_permitted") in codes(_paired_record(counterpart_passed=False))


def test_a_pair_cannot_name_its_own_variant_as_the_counterpart() -> None:
    record = _paired_record(counterpart_passed=True)
    record["pairedVariantSkips"][0]["counterpartVariant"] = "windows-x86_64-cpu"
    assert ("B2", "skip_not_permitted") in codes(record)


def test_counts_must_match_the_named_tests() -> None:
    record = complete_record()
    suite_id = record["units"]["B1"]["suites"][0]
    record["suites"][suite_id]["passed"] = 5
    assert ("B1", "count_inconsistent") in codes(record)


def test_a_missing_per_variant_result_cannot_carry_a_pass() -> None:
    record = complete_record()
    windows = next(sid for sid in record["units"]["B1"]["suites"] if sid.endswith("windows-x86_64-cpu"))
    record["units"]["B1"]["suites"].remove(windows)
    assert ("B1", "variant_result_missing") in codes(record)


def test_a_cited_suite_must_exist() -> None:
    record = complete_record()
    record["units"]["B5"]["suites"].append("nowhere")
    assert ("B5", "suite_missing") in codes(record)


def test_junit_for_a_suite_must_be_retained() -> None:
    record = complete_record()
    suite_id = record["units"]["B6"]["suites"][0]
    del record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]
    assert ("B6", "junit_not_retained") in codes(record)


# --------------------------------------------------------------------------- measurements


def test_every_plan_metric_is_required_for_a_pass() -> None:
    for name, requirement in UNIT_REQUIREMENTS.items():
        for metric in requirement.measurements:
            record = complete_record()
            record["units"][name]["measurements"].remove(f"{name}:{metric.metric}")
            assert (name, "measurement_missing") in codes(record), metric.metric


@pytest.mark.parametrize(
    ("unit", "metric", "value"),
    [
        ("B2", "b2.per-retired-traced-bytes-slope", 16 * 1024 + 1),
        ("B2", "b2.process-memory-retired-slope", 20_000),
        ("B2", "b2.per-live-held-evidence-bytes-max", 544 * 1024 + 1),
        ("B2", "b2.retired-slope-crop-variation", 0.11),
        ("B1", "b1.real-clip-parameter-note-mismatches", 1),
        ("B3", "b3.python-worst-shape-body-bytes", 40 * 1024 * 1024 + 1),
        ("B5", "b5.real-video-clips", 1),
    ],
)
def test_the_plan_limit_binds_whatever_the_record_declares(unit: str, metric: str, value: float) -> None:
    record = complete_record()
    entry = record["measurements"][f"{unit}:{metric}"]
    entry["value"] = value
    # A record that loosens its own limit to match still fails the plan's.
    entry["limit"] = {"op": "<=", "value": value * 10 + 10, "source": "made up"}
    assert (unit, "limit_violated") in codes(record)


def test_a_declared_limit_is_also_enforced() -> None:
    record = complete_record()
    entry = record["measurements"]["B2:b2.completion-peak-bytes"]
    entry["limit"] = {"op": "<=", "value": 10, "source": "recorded baseline"}
    assert ("B2", "limit_violated") in codes(record)


def test_a_recorded_only_metric_has_no_threshold() -> None:
    record = complete_record()
    record["measurements"]["B2:b2.completion-peak-bytes"]["value"] = 10**12
    assert structural(record) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(samples=29),
        lambda e: e.update(repeats=2),
        lambda e: e.update(warmupExcluded=False),
        lambda e: e["stats"].pop("p50RunSpread"),
        lambda e: e.pop("stats"),
        lambda e: e["stats"].update(p95=5.0),
    ],
)
def test_timing_needs_samples_repeats_warmup_percentiles_and_spread(mutate) -> None:
    record = complete_record()
    mutate(record["measurements"]["B3:b3.real-store-completion-wall-ms"])
    found = codes(record)
    assert ("B3", "timing_incomplete") in found or ("B3", "timing_inconsistent") in found


def test_b3_completion_time_needs_2x_headroom_against_the_worker_timeout() -> None:
    record = complete_record()
    record["measurements"]["B3:b3.real-store-completion-wall-ms"]["stats"]["max"] = 15_001.0
    assert ("B3", "completion_headroom_insufficient") in codes(record)
    record["measurements"]["B3:b3.real-store-completion-wall-ms"]["stats"]["max"] = 15_000.0
    assert ("B3", "completion_headroom_insufficient") not in codes(record)


def test_a_measurement_unit_must_match_the_plan() -> None:
    record = complete_record()
    record["measurements"]["B2:b2.per-retired-traced-bytes-slope"]["unit"] = "bytes"
    assert ("B2", "measurement_unit_mismatch") in codes(record)


# --------------------------------------------------------------------------- artifacts


def test_every_required_artifact_is_needed() -> None:
    for name, requirement in UNIT_REQUIREMENTS.items():
        for artifact in requirement.artifacts:
            record = complete_record()
            record["units"][name]["artifacts"].remove(artifact)
            assert (name, "artifact_missing") in codes(record), artifact


def test_an_artifact_without_a_hash_is_refused() -> None:
    record = complete_record()
    del record["retainedArtifacts"]["b2.memory-harness-output"]["sha256"]
    assert ("record", "schema_invalid") in codes(record)


def test_retained_files_are_verified_against_their_hash(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    assert check_record(record, repo_root=tmp_path, verify_git=False) == []
    (tmp_path / record["retainedArtifacts"]["b1.real-clip-measurement"]["path"]).write_bytes(b"edited")
    assert ("B1", "artifact_hash_mismatch") in codes(record, repo_root=tmp_path, verify_git=False)
    (tmp_path / record["retainedArtifacts"]["b1.real-clip-measurement"]["path"]).unlink()
    assert ("B1", "artifact_file_missing") in codes(record, repo_root=tmp_path, verify_git=False)


def test_an_artifact_path_cannot_escape_the_repository(tmp_path: Path) -> None:
    record = complete_record()
    for entry in record["retainedArtifacts"].values():
        path = tmp_path / "repo" / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        entry["sha256"] = hashlib.sha256(b"x").hexdigest()
    (tmp_path / "outside.json").write_bytes(b"x")
    record["retainedArtifacts"]["b1.real-clip-measurement"]["path"] = "../outside.json"
    assert ("B1", "artifact_file_missing") in codes(record, repo_root=tmp_path / "repo", verify_git=False)


# --------------------------------------------------------------------------- disconnected


def test_the_disconnected_run_must_use_a_bundle_of_the_measured_code() -> None:
    record = complete_record()
    record["disconnected"]["runtimeBundleSourceCommit"] = OTHER
    assert ("DISCONNECTED", "runtime_bundle_not_measured_code") in codes(record)


@pytest.mark.parametrize("phase", ["isolationBefore", "isolationAfter"])
def test_isolation_must_be_evidenced_before_and_after(phase: str) -> None:
    record = complete_record()
    record["disconnected"][phase]["probes"][0]["reachable"] = True
    assert ("DISCONNECTED", "isolation_not_evidenced") in codes(record)


def test_a_production_install_is_not_the_s1_disconnected_run() -> None:
    record = complete_record()
    record["disconnected"]["installProfile"] = "production"
    assert ("record", "schema_invalid") in codes(record)


def test_the_disconnected_block_is_required_for_its_pass() -> None:
    record = complete_record()
    del record["disconnected"]
    assert ("DISCONNECTED", "disconnected_record_missing") in codes(record)


# --------------------------------------------------------------------------- §2.1 / §2.2 / §2.3


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/vision/mavi_vision/evidence/selector.py", {"B1", "B2", "B3", "B5", "B6", "DISCONNECTED"}),
        ("src/vision/mavi_vision/worker/client.py", {"B3", "B4", "B5", "B6", "DISCONNECTED"}),
        ("src/vision/mavi_vision/common/control_plane.py", {"B3", "B4", "B5", "B6", "DISCONNECTED"}),
        ("src/platform/Mavi.Infrastructure/Storage/AcceptedEvidenceStore.cs", {"B3", "B4", "B5", "DISCONNECTED"}),
        ("src/web/mavi-web/src/features/video-review/TrackEvidenceSet.tsx", {"B5", "DISCONNECTED"}),
        ("src/vision/runtime/mmdetection-phase1-v1.json", {"B1", "B6", "DISCONNECTED"}),
        ("src/vision/config/pipelines/phase1-detection-tracking-v1.json", {"B1", "B2", "B3", "B5", "B6", "DISCONNECTED"}),
        # A behavior-bearing path the table does not map invalidates everything.
        ("src/vision/mavi_vision/embeddings/__init__.py", set(UNITS)),
        ("tools/phase1/promote_phase1_release.py", set(UNITS)),
        (".github/workflows/task10-runtime-qualification.yml", set(UNITS)),
        ("tests/fixtures/scene-analytics/scripted-corpus-v1.json", {"B1"}),
    ],
)
def test_the_invalidation_map_follows_the_plan(path: str, expected: set[str]) -> None:
    assert invalidated_units([path], {}) == {path: expected}


@pytest.mark.parametrize("path", ["docs/qualification/stage2-s1/summary.md", "README.md", "src/vision/tests/test_unrelated.py", ".github/workflows/other.yml"])
def test_documentation_and_uncited_tests_invalidate_nothing(path: str) -> None:
    assert invalidated_units([path], {}) == {}


def test_a_cited_test_invalidates_the_units_that_cite_it() -> None:
    cited = {"B1": {"src/vision/tests/test_evidence_encoder.py"}, "B3": {"src/vision/tests/test_evidence_encoder.py"}}
    assert invalidated_units(["src/vision/tests/test_evidence_encoder.py"], cited) == {
        "src/vision/tests/test_evidence_encoder.py": {"B1", "B3"},
    }
    tree = {"B2": {"tools/qualification/tests"}}
    assert invalidated_units(["tools/qualification/tests/test_s1_memory.py"], tree)["tools/qualification/tests/test_s1_memory.py"] >= {"B2"}


def test_a_closure_diff_on_the_surface_requires_the_affected_units_rerun() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": ["src/platform/Mavi.Api/Program.cs"]}
    found = codes(record)
    for unit in ("B3", "B4", "B5", "DISCONNECTED"):
        assert (unit, "closure_rerun_required") in found
    for unit in ("B1", "B2", "B6"):
        assert (unit, "closure_rerun_required") not in found


def test_a_closure_diff_touching_nothing_behavior_bearing_is_clean() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": ["docs/qualification/stage2-s1/s1-qualification-summary.md"]}
    assert structural(record) == []


def test_units_rerun_on_the_merge_sha_satisfy_the_closure_rule() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": ["src/web/mavi-web/src/App.tsx"]}
    record["runs"]["rerun"] = {"kind": "workflow", "workflow": "quality-gate.yml", "runId": 9, "headSha": MERGE, "conclusion": "success"}
    record["runs"]["rerun-host"] = {**record["runs"]["host"], "headSha": MERGE}
    for name in ("B5", "DISCONNECTED"):
        record["units"][name]["measuredSha"] = MERGE
    for suite_id in record["units"]["B5"]["suites"]:
        record["suites"][suite_id]["run"] = "rerun"
        record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]["run"] = "rerun"
    for artifact in record["units"]["B5"]["artifacts"] + record["units"]["DISCONNECTED"]["artifacts"]:
        record["retainedArtifacts"][artifact]["run"] = "rerun-host"
    for measurement_id in record["units"]["B5"]["measurements"]:
        record["measurements"][measurement_id]["run"] = "rerun-host"
    record["disconnected"]["runtimeBundleSourceCommit"] = MERGE
    assert structural(record) == []


def test_s1_closed_needs_every_unit_pass_and_a_closure() -> None:
    record = complete_record()
    record["s1Closed"] = True
    assert ("record", "closure_missing") in codes(record)
    record["closure"] = {"mergeSha": MERGE, "changedPaths": []}
    assert structural(record) == []
    record["units"]["B6"]["verdict"] = "OPEN"
    assert ("record", "closure_units_open") in codes(record)


def test_the_recorded_closure_diff_must_be_the_real_git_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *args: subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (repo / "a.txt").write_text("a")
    git("add", ".")
    git("commit", "-qm", "measured")
    measured = git("rev-parse", "HEAD")
    (repo / "src" / "platform").mkdir(parents=True)
    (repo / "src" / "platform" / "x.cs").write_text("x")
    git("add", ".")
    git("commit", "-qm", "merge")
    merge = git("rev-parse", "HEAD")

    record = complete_record()
    record["measuredSha"] = measured
    for run in record["runs"].values():
        run["headSha"] = measured
    record["disconnected"]["runtimeBundleSourceCommit"] = measured
    record["closure"] = {"mergeSha": merge, "changedPaths": []}
    # Hiding the platform change from the recorded diff is caught...
    checker_findings = {(f.unit, f.code) for f in _check_with_git(record, repo)}
    assert ("record", "closure_diff_mismatch") in checker_findings
    # ... and the honest diff then demands the platform-affected reruns.
    record["closure"]["changedPaths"] = ["src/platform/x.cs"]
    honest = {(f.unit, f.code) for f in _check_with_git(record, repo)}
    assert ("record", "closure_diff_mismatch") not in honest
    assert ("B4", "closure_rerun_required") in honest


def _check_with_git(record: dict, repo: Path):
    checker = s1_evidence._Checker(record, repo)
    assert checker.schema()
    for name in UNITS:
        checker.unit(name)
    checker.closure()
    checker.verify_git_diff()
    # Artifact file verification is not under test here.
    return [f for f in checker.findings if not f.code.startswith("artifact_file")]


# --------------------------------------------------------------------------- JUnit


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="5">
<testcase classname="tests.test_evidence_encoder" name="test_a" file="tests/test_evidence_encoder.py"/>
<testcase classname="tests.test_evidence_encoder" name="test_b"><skipped message="x"/></testcase>
<testcase classname="tests.test_evidence_selector" name="test_c"><failure message="boom"/></testcase>
<testcase classname="tests.test_evidence_selector" name="test_d"><error message="boom"/></testcase>
<testcase classname="tests.test_evidence_selector" name="test_e"/>
</testsuite></testsuites>
"""


def test_junit_counts_come_from_the_test_cases(tmp_path: Path) -> None:
    path = tmp_path / "j.xml"
    path.write_text(JUNIT)
    everything = suite_counts_from_junit(path)
    assert {k: everything[k] for k in ("passed", "skipped", "failed", "errors")} == {"passed": 2, "skipped": 1, "failed": 1, "errors": 1}
    encoder = suite_counts_from_junit(path, "src/vision/tests/test_evidence_encoder.py")
    assert encoder["passedTests"] == ["tests.test_evidence_encoder::test_a"]
    assert encoder["skippedTests"] == ["tests.test_evidence_encoder::test_b"]
    with pytest.raises(ValueError, match="junit_no_matching_testcases"):
        suite_counts_from_junit(path, "src/vision/tests/test_nothing.py")


def test_the_cli_exits_nonzero_on_a_finding(tmp_path: Path, capsys) -> None:
    # A closure-free record needs no git history, only the retained files.
    root = tmp_path / "repo"
    good = tmp_path / "good.json"
    good.write_text(json.dumps(materialize(complete_record(), root)))
    assert s1_evidence.main(["check", str(good), "--repo-root", str(root)]) == 0
    # Without --repo-root the default is this repository, where the files do not
    # exist: it is verified (and refused), not skipped.
    capsys.readouterr()
    assert s1_evidence.main(["check", str(good)]) == 1
    output = capsys.readouterr().out
    assert "artifact_file_missing" in output and "repository_not_verified" not in output
    bad_record = materialize(complete_record(), root)
    bad_record["runs"]["task10"]["headSha"] = OTHER
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(bad_record))
    assert s1_evidence.main(["check", str(bad), "--repo-root", str(root)]) == 1
    assert "head_sha_mismatch" in capsys.readouterr().out


def test_the_schema_file_is_the_one_the_checker_loads() -> None:
    schema = json.loads(s1_evidence.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schemaVersion"]["const"] == "s1-qualification-evidence-v1"
    assert set(schema["properties"]["units"]["required"]) == set(UNITS)
    assert copy.deepcopy(UNITS) == ("B1", "B2", "B3", "B4", "B5", "B6", "DISCONNECTED")


def test_platform_suites_are_required_once_and_worker_suites_on_every_variant() -> None:
    b3 = UNIT_REQUIREMENTS["B3"]
    assert required_variants(b3, "tests/Mavi.IntegrationTests/S1BoundAgreementTests") == (None,)
    assert required_variants(b3, "src/vision/tests/test_s1_bound_agreement.py") == s1_evidence.QUALIFIED_CPU_VARIANTS
    assert required_variants(UNIT_REQUIREMENTS["B4"], "src/vision/tests/test_worker_completion_v3.py") == (None,)


def test_a_worker_suite_missing_on_one_variant_blocks_its_unit() -> None:
    record = complete_record()
    suite_id = "B3:src/vision/tests/test_s1_bound_agreement.py:windows-x86_64-cpu"
    del record["suites"][suite_id]
    record["units"]["B3"]["suites"].remove(suite_id)
    failures = structural(record)
    assert ("B3", "variant_result_missing") in {(f.unit, f.code) for f in failures}


# --------------------------------------------------------------------------- review round 1


def test_a_pass_is_refused_without_repository_verification() -> None:
    assert ("record", "repository_not_verified") in {(f.unit, f.code) for f in check_record(complete_record())}
    record = complete_record()
    for unit in record["units"].values():
        unit["verdict"] = "OPEN"
    assert check_record(record) == []  # nothing claimed, nothing to verify


def test_a_fully_verified_record_passes(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    assert check_record(record, repo_root=tmp_path, verify_git=False) == []


def test_suite_counts_must_be_the_retained_junit_counts(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    entry = record["suites"][suite_id]
    entry.update(passed=2, passedTests=[*entry["passedTests"], "invented::test_never_run"])
    assert ("B1", "junit_count_mismatch") in codes(record, repo_root=tmp_path, verify_git=False)


def test_a_tampered_or_missing_junit_file_is_refused(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    junit = record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]
    (tmp_path / junit["path"]).write_text("<testsuites/>", encoding="utf-8")
    assert ("B1", "artifact_hash_mismatch") in codes(record, repo_root=tmp_path, verify_git=False)
    (tmp_path / junit["path"]).unlink()
    assert ("B1", "artifact_file_missing") in codes(record, repo_root=tmp_path, verify_git=False)


def test_junit_must_come_from_the_run_the_result_cites() -> None:
    record = complete_record()
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]["run"] = "quality"
    assert ("B1", "junit_run_mismatch") in codes(record)


def test_a_paired_counterpart_must_be_cited_by_the_same_unit() -> None:
    record = _paired_record(counterpart_passed=True)
    linux = next(sid for sid in record["units"]["B2"]["suites"] if "test_track_lifecycle.py:linux" in sid)
    record["units"]["B2"]["suites"].remove(linux)
    record["suites"]["stale-counterpart"] = dict(record["suites"][linux])
    assert ("B2", "skip_not_permitted") in codes(record)


def test_a_paired_counterpart_from_a_stale_run_does_not_excuse_a_skip() -> None:
    record = _paired_record(counterpart_passed=True)
    linux = next(sid for sid in record["units"]["B2"]["suites"] if "test_track_lifecycle.py:linux" in sid)
    record["runs"]["stale"] = {**record["runs"]["task10"], "headSha": OTHER, "runId": 99}
    record["suites"][linux]["run"] = "stale"
    assert ("B2", "skip_not_permitted") in codes(record)


def test_the_worker_timeout_is_bound_to_the_worker_default() -> None:
    default_ms, maximum_ms = s1_evidence.worker_request_timeout_bounds_ms()
    assert (default_ms, maximum_ms) == (30_000.0, 120_000.0)
    record = complete_record()
    timeout = next(m for m in record["measurements"].values() if m["metric"] == "b3.worker-request-timeout-ms")
    timeout["value"] = 90_000.0
    # Citing the sealing output (or any artifact but the install configuration) is not a binding.
    assert timeout["artifact"] == "b3.sealing-scale-output"
    assert ("B3", "worker_timeout_unbound") in codes(record)
    timeout["value"] = 600_000.0
    assert ("B3", "worker_timeout_out_of_range") in codes(record)


def test_a_non_default_timeout_is_accepted_only_with_a_retained_install_configuration(tmp_path: Path) -> None:
    record = complete_record()
    timeout = next(m for m in record["measurements"].values() if m["metric"] == "b3.worker-request-timeout-ms")
    timeout.update(value=60_000.0, artifact="b3.worker-configuration")
    record["retainedArtifacts"]["b3.worker-configuration"] = {"path": "records/worker.env", "sha256": "e" * 64, "run": "host"}
    record["units"]["B3"]["artifacts"].append("b3.worker-configuration")
    record = materialize(record, tmp_path)
    assert check_record(record, repo_root=tmp_path, verify_git=False) == []


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (lambda o: o.update(status="smoke"), "status"),
        (lambda o: o.update(authoritative=False), "authoritative"),
        (lambda o: o["shape"].update(tracks=200), "tracks"),
        (lambda o: o["shape"].update(sealedObjects=1_000), "sealed objects"),
        (lambda o: o.update(workerRequestTimeoutMs=120_000), "worker timeout"),
        (lambda o: o["completion"].update(max=1.0), "max"),
        (lambda o: o["completion"].update(min=1.0), "min"),
        (lambda o: o["completion"].update(p50=1.0), "p50 differs"),
        (lambda o: o["completion"].update(p95=1.0), "p95"),
        (lambda o: o.update(repeats=1), "repeat count"),
        (lambda o: o.update(p50RunSpreadMs=0.0), "p50 spread"),
        (lambda o: o.update(warmupExcluded=0), "warm-up"),
        (lambda o: o["completion"].update(n=1), "sample count"),
    ],
)
def test_the_b3_wall_time_must_be_the_authoritative_sealing_output(tmp_path: Path, mutate, detail: str) -> None:
    record = materialize(complete_record(), tmp_path)
    entry = record["retainedArtifacts"]["b3.sealing-scale-output"]
    output = json.loads((tmp_path / entry["path"]).read_text(encoding="utf-8"))
    mutate(output)
    content = json.dumps(output)
    (tmp_path / entry["path"]).write_text(content, encoding="utf-8")
    entry["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    findings = [f for f in check_record(record, repo_root=tmp_path, verify_git=False) if f.code == "sealing_output_mismatch"]
    assert findings and any(detail in f.detail for f in findings)


def test_the_b3_wall_time_must_cite_the_sealing_output() -> None:
    record = complete_record()
    wall = next(m for m in record["measurements"].values() if m["metric"] == "b3.real-store-completion-wall-ms")
    del wall["artifact"]
    assert ("B3", "sealing_output_unbound") in codes(record)


def _rewrite_junit(record: dict, root: Path, suite_id: str, xml: str) -> None:
    artifact = record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]
    (root / artifact["path"]).write_text(xml, encoding="utf-8")
    artifact["sha256"] = hashlib.sha256(xml.encode("utf-8")).hexdigest()


def test_junit_counts_are_compared_even_when_the_named_tests_agree(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    classname = record["suites"][suite_id]["passedTests"][0].split("::")[0]
    xml = _junit_for(record["suites"][suite_id]).replace("</testsuite>", f'<testcase classname="{classname}" name="y"><error/></testcase></testsuite>')
    _rewrite_junit(record, tmp_path, suite_id, xml)
    findings = [f for f in check_record(record, repo_root=tmp_path, verify_git=False) if f.code == "junit_count_mismatch"]
    assert findings and all("errors" in f.detail for f in findings)


def test_junit_test_names_are_compared_even_when_the_counts_agree(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    suite_id = next(iter(record["units"]["B1"]["suites"]))
    xml = _junit_for(record["suites"][suite_id]).replace('name="test_ok"', 'name="test_other"')
    _rewrite_junit(record, tmp_path, suite_id, xml)
    findings = [f for f in check_record(record, repo_root=tmp_path, verify_git=False) if f.code == "junit_count_mismatch"]
    assert findings and all("passedTests" in f.detail for f in findings)


# --------------------------------------------------------------------------- review round 2


def _rewrite_json(record: dict, root: Path, artifact_id: str, mutate) -> None:
    entry = record["retainedArtifacts"][artifact_id]
    data = json.loads((root / entry["path"]).read_text(encoding="utf-8"))
    mutate(data)
    content = json.dumps(data)
    (root / entry["path"]).write_text(content, encoding="utf-8")
    entry["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()


def _verified_codes(record: dict, root: Path) -> set[tuple[str, str]]:
    return codes(record, repo_root=root, verify_git=False)


def test_b2_values_must_be_the_retained_harness_output(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    slope = next(m for m in record["measurements"].values() if m["metric"] == "b2.per-retired-traced-bytes-slope")
    # The harness measured an over-limit slope; the record shows a low one.
    _rewrite_json(record, tmp_path, "b2.memory-harness-output",
                  lambda d: d["measurements"]["b2.per-retired-traced-bytes-slope"].update(value=40_000.0))
    assert slope["value"] <= 16 * 1024
    assert ("B2", "b2_output_mismatch") in _verified_codes(record, tmp_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="other"),
        lambda d: d["identity"].update(sourceSha="c" * 40),
        lambda d: d["identity"].update(cleanTree=False),
        lambda d: d["measurements"].pop("b2.staging-peak-bytes"),
        lambda d: d["measurements"]["b2.completion-peak-bytes"].update(unit="ms"),
    ],
)
def test_the_b2_harness_output_must_be_complete_and_from_the_measured_clean_source(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "b2.memory-harness-output", mutate)
    assert ("B2", "b2_output_mismatch") in _verified_codes(record, tmp_path)


def _variant_suite(record: dict, variant: str) -> str:
    return next(sid for sid in record["units"]["B2"]["suites"] if sid.endswith(":" + variant) and "test_track_lifecycle" in sid)


def test_a_linux_junit_relabelled_as_windows_is_refused(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    linux, windows = _variant_suite(record, "linux-x86_64-cpu"), _variant_suite(record, "windows-x86_64-cpu")
    # Cite the Linux XML for the Windows result as well.
    record["suites"][windows]["junitArtifact"] = record["suites"][linux]["junitArtifact"]
    found = _verified_codes(record, tmp_path)
    assert {("B2", "junit_variant_unbound"), ("B2", "junit_variant_reused"), ("B2", "junit_variant_mismatch")} <= found


def test_a_copied_junit_file_is_refused_even_under_its_own_artifact_id(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    linux, windows = _variant_suite(record, "linux-x86_64-cpu"), _variant_suite(record, "windows-x86_64-cpu")
    source = record["retainedArtifacts"][record["suites"][linux]["junitArtifact"]]
    target = record["retainedArtifacts"][record["suites"][windows]["junitArtifact"]]
    (tmp_path / target["path"]).write_bytes((tmp_path / source["path"]).read_bytes())
    target["sha256"] = source["sha256"]
    found = _verified_codes(record, tmp_path)
    assert ("B2", "junit_variant_reused") in found and ("B2", "junit_variant_mismatch") in found


def test_a_variant_junit_must_name_its_variant_in_the_xml(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    windows = _variant_suite(record, "windows-x86_64-cpu")
    xml = _junit_for(record["suites"][windows]).replace('name="windows-x86_64-cpu"', 'name="pytest"')
    _rewrite_junit(record, tmp_path, windows, xml)
    assert ("B2", "junit_variant_mismatch") in _verified_codes(record, tmp_path)


def test_a_variant_junit_artifact_must_declare_its_variant() -> None:
    record = complete_record()
    windows = _variant_suite(record, "windows-x86_64-cpu")
    del record["retainedArtifacts"][record["suites"][windows]["junitArtifact"]]["variant"]
    assert ("B2", "junit_variant_unbound") in codes(record)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="other"),
        lambda d: d.update(sourceCommit="c" * 40),
        lambda d: d.update(variant="linux-x86_64-cpu"),
        lambda d: d.update(installProfile="production"),
        lambda d: d.update(outboundConnectionAttempts=["10.0.0.5:443"]),
        lambda d: d["outcomes"].pop("completionV3"),
        lambda d: d["outcomes"]["reviewInvestigationEvidenceSet"].update(passed=False),
        lambda d: d["outcomes"]["sealedTrackEvidence"].update(evidence=""),
        lambda d: d["outcomes"]["sealedTrackEvidence"].update(evidence="records/not-retained.log"),
        lambda d: d.pop("outcomes"),
    ],
)
def test_disconnected_pass_needs_every_evidenced_outcome_on_the_measured_code(tmp_path: Path, mutate) -> None:
    record = materialize(complete_record(), tmp_path)
    _rewrite_json(record, tmp_path, "disconnected.run-record", mutate)
    assert ("DISCONNECTED", "disconnected_run_incomplete") in _verified_codes(record, tmp_path)


def test_a_changed_dotnet_evidence_test_invalidates_its_unit() -> None:
    cited = {"B3": {"tests/Mavi.IntegrationTests/S1BoundAgreementTests"}, "B4": {"tests/Mavi.Application.Tests/CompletionDigestGoldenTests"}}
    assert invalidated_units(["tests/Mavi.IntegrationTests/S1BoundAgreementTests.cs"], cited) == {
        "tests/Mavi.IntegrationTests/S1BoundAgreementTests.cs": {"B3"}
    }
    assert invalidated_units(["tests/Mavi.Application.Tests/CompletionDigestGoldenTests.Vectors.cs"], cited) == {
        "tests/Mavi.Application.Tests/CompletionDigestGoldenTests.Vectors.cs": {"B4"}
    }
    # A different class sharing the prefix is not the cited suite.
    assert invalidated_units(["tests/Mavi.IntegrationTests/S1BoundAgreementTestsExtra.cs"], cited) == {}
    assert invalidated_units(["tests/Mavi.IntegrationTests/S1BoundAgreementTests.json"], cited) == {}


def test_a_closure_diff_touching_a_cited_dotnet_suite_requires_a_rerun() -> None:
    record = complete_record()
    record["closure"] = {"mergeSha": MERGE, "changedPaths": ["tests/Mavi.IntegrationTests/S1BoundAgreementTests.cs"]}
    assert ("B3", "closure_rerun_required") in codes(record)


# --------------------------------------------------------------------------- cold review before push


def test_junit_membership_is_by_component_not_substring(tmp_path: Path) -> None:
    path = tmp_path / "j.xml"
    path.write_text(JUNIT)
    selector = suite_counts_from_junit(path, "src/vision/tests/test_evidence_selector.py")
    assert (selector["passed"], selector["failed"], selector["errors"]) == (1, 1, 1)
    # A prefix of a module name is not that module.
    with pytest.raises(ValueError, match="junit_no_matching_testcases"):
        suite_counts_from_junit(path, "src/vision/tests/test_evidence.py")
    assert s1_evidence.suite_key("tests/Mavi.IntegrationTests/S1BoundAgreementTests") == ("IntegrationTests", "S1BoundAgreementTests")
    assert s1_evidence.suite_key("tools/qualification/tests") == ("qualification", "tests")
    assert s1_evidence.suite_key("src/web/mavi-web") is None
    assert s1_evidence.case_belongs("tools.qualification.tests.test_s1_memory", ("qualification", "tests"))
    assert s1_evidence.case_belongs("Mavi.IntegrationTests.S1BoundAgreementTests", ("IntegrationTests", "S1BoundAgreementTests"))
    assert not s1_evidence.case_belongs("Mavi.IntegrationTests.S1BoundAgreementTestsExtra", ("IntegrationTests", "S1BoundAgreementTests"))
    # The classnames pytest actually writes in Task 10: the boundary step runs
    # from src/vision, the harness step from the repository root.
    assert s1_evidence.case_belongs("tests.test_s1_bound_agreement", s1_evidence.suite_key("src/vision/tests/test_s1_bound_agreement.py"))
    assert s1_evidence.case_belongs("tools.qualification.tests.test_s1_memory", s1_evidence.suite_key("tools/qualification/tests"))


def test_a_suite_result_cannot_be_backed_by_another_suites_xml(tmp_path: Path) -> None:
    record = materialize(complete_record(), tmp_path)
    b2 = record["units"]["B2"]["suites"]
    lifecycle = next(sid for sid in b2 if "test_track_lifecycle.py:linux" in sid)
    spool = next(sid for sid in b2 if "test_trajectory_spool.py:linux" in sid)
    # The spool result points at the lifecycle suite's XML, with the lifecycle
    # suite's counts and names copied in.
    record["suites"][spool]["junitArtifact"] = record["suites"][lifecycle]["junitArtifact"]
    record["suites"][spool]["passedTests"] = list(record["suites"][lifecycle]["passedTests"])
    assert ("B2", "junit_unreadable") in _verified_codes(record, tmp_path)


def test_every_measurement_cites_a_retained_artifact_of_its_unit() -> None:
    record = complete_record()
    slope = next(m for m in record["measurements"].values() if m["metric"] == "b2.per-retired-traced-bytes-slope")
    del slope["artifact"]
    assert ("B2", "measurement_unbound") in codes(record)
    slope["artifact"] = "b1.real-clip-measurement"  # retained, but another unit's
    assert ("B2", "measurement_unbound") in codes(record)
    slope["artifact"] = "not-retained"
    assert ("B2", "measurement_unbound") in codes(record)


def test_a_unit_measured_off_the_diffed_shas_is_refused() -> None:
    record = complete_record()
    record["runs"]["older"] = {**record["runs"]["task10"], "headSha": OTHER, "runId": 7}
    record["units"]["B6"]["measuredSha"] = OTHER
    for suite_id in record["units"]["B6"]["suites"]:
        record["suites"][suite_id]["run"] = "older"
        record["retainedArtifacts"][record["suites"][suite_id]["junitArtifact"]]["run"] = "older"
    assert ("B6", "unit_sha_unbound") in codes(record)
    # Re-measured on the closure merge SHA is the one other permitted SHA.
    record["closure"] = {"mergeSha": OTHER, "changedPaths": []}
    assert ("B6", "unit_sha_unbound") not in codes(record)
