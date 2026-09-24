"""Fail-closed checker for the Stage-2 S1 qualification evidence record.

S1.4 plan §4: "The machine-readable record must make PASS impossible unless
every required field for that B-item is present." The JSON schema
(``s1-qualification-evidence.schema.json``) fixes the record's shape. This
module holds the rules a schema cannot express. It refuses a PASS verdict when:

- a suite, measurement, artifact, run or host the unit relies on is missing;
- a required suite failed, errored or skipped outside a declared paired-variant
  skip (§3, §3.1), or a qualified variant has no result for it;
- a run's ``head_sha`` differs from the SHA the unit claims to have measured;
- a measurement lacks host identity, violates its own declared limit, or (for
  timings) lacks n ≥ 30, min/p50/p95/max, warm-up exclusion or three repeats (§12);
- a retained artifact has no SHA-256, or its file on disk does not match it;
- a unit-specific requirement of §5–§11 is absent (``UNIT_REQUIREMENTS``);
- the §2.3 measured→closure diff touches the behavior-bearing surface (§2.1)
  and a unit §2.2 maps it to was not re-measured on the closure SHA.

An OPEN unit may be incomplete: the checker reports what it still lacks, but an
OPEN or FAIL verdict is never an error. ``s1Closed: true`` requires every unit
PASS and a closure block (§15).

Deliberately dependency-light: ``jsonschema`` (already required by
``tools/verify_repo.py``) and the standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = Path(__file__).resolve().with_name("s1-qualification-evidence.schema.json")
UNITS = ("B1", "B2", "B3", "B4", "B5", "B6", "DISCONNECTED")
QUALIFIED_CPU_VARIANTS = ("linux-x86_64-cpu", "windows-x86_64-cpu")
TIMING_UNITS = frozenset({"ms"})
MINIMUM_TIMING_SAMPLES = 30
MINIMUM_TIMING_REPEATS = 3

# --------------------------------------------------------------------------- §2.1
# The behavior-bearing surface, as path globs. ``*`` in fnmatch also crosses
# ``/``, so ``src/vision/**`` covers every depth.
BEHAVIOR_BEARING_SURFACE: tuple[str, ...] = (
    "src/vision/*",
    "src/platform/*",
    "src/web/mavi-web/src/*",
    "src/web/mavi-web/package*.json",
    "contracts/*",
    "models/*",
    "config/dependencies/*",
    "tools/vision/*",
    "tools/phase1/*",
    "tools/setup/*",
    "tools/native/*",
    "tools/qualification/*",
    "infrastructure/*",
    "config/setup/*",
    "config/acceptance/*",
    "Setup-MAVI-*",
    "*.cmd",
    "*.ps1",
    "tests/*",
    ".github/workflows/task10-runtime-qualification.yml",
    ".github/workflows/quality-gate.yml",
    ".github/workflows/task12-offline-bundle.yml",
    ".github/workflows/task17-acceptance.yml",
)

# Test trees are behavior-bearing only "when used as evidence" (§2.1): a test a
# unit cites invalidates that unit; an uncited test invalidates nothing. The
# scripted corpus is named explicitly because the B1 expectation depends on it.
EVIDENCE_TEST_TREES: tuple[str, ...] = ("src/vision/tests/*", "tests/*")
ALWAYS_EVIDENCE: dict[str, tuple[str, ...]] = {
    "tests/fixtures/scene-analytics/scripted-corpus-v1.json": ("B1",),
}

# --------------------------------------------------------------------------- §2.2
_VISION = "src/vision/mavi_vision/"
_PIPELINE_SET = ("B1", "B2", "B3", "B5", "B6", "DISCONNECTED")
_CONTRACT_SET = ("B3", "B4", "B5", "B6", "DISCONNECTED")
INVALIDATION_MAP: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    ((_VISION + "evidence/*", _VISION + "quality/*", "src/vision/config/pipelines/*"), _PIPELINE_SET),
    (
        tuple(_VISION + package + "/*" for package in ("tracking", "pipeline", "video", "storage", "detection")),
        _PIPELINE_SET,
    ),
    ((_VISION + "common/*", _VISION + "worker/*", "contracts/*"), _CONTRACT_SET),
    (("src/platform/*",), ("B3", "B4", "B5", "DISCONNECTED")),
    (("src/web/mavi-web/*",), ("B5", "DISCONNECTED")),
    (
        (
            "src/vision/runtime/*",
            "models/*",
            "config/dependencies/*",
            "infrastructure/*",
            "src/vision/pyproject.toml",
        ),
        ("B1", "B6", "DISCONNECTED"),
    ),
)

# --------------------------------------------------------------------------- §5–§11
@dataclass(frozen=True)
class MeasurementRequirement:
    metric: str
    unit: str
    # A limit the plan fixes. ``None`` means the plan records the value without
    # thresholding it (for example the B2 completion peak, §6.2 bound 4).
    limit_op: str | None = None
    limit_value: float | None = None
    timing: bool = False


@dataclass(frozen=True)
class UnitRequirement:
    suites: tuple[str, ...]
    variants: tuple[str, ...]
    measurements: tuple[MeasurementRequirement, ...]
    artifacts: tuple[str, ...]


KIB = 1024
MIB = 1024 * 1024

UNIT_REQUIREMENTS: dict[str, UnitRequirement] = {
    # §5: deterministic suites on both variants; repeat, cross-variant and
    # real-clip comparisons are exact (zero untraced differences).
    "B1": UnitRequirement(
        suites=(
            "src/vision/tests/test_evidence_profile.py",
            "src/vision/tests/test_evidence_quality.py",
            "src/vision/tests/test_evidence_encoder.py",
            "src/vision/tests/test_evidence_selector.py",
            "src/vision/tests/test_evidence_admission.py",
            "src/vision/tests/test_evidence_pipeline.py",
            "src/vision/tests/test_evidence_scripted_corpus.py",
            "src/vision/tests/test_measure_evidence_real_clips.py",
        ),
        variants=QUALIFIED_CPU_VARIANTS,
        measurements=(
            MeasurementRequirement("b1.within-variant-repeat-mismatches", "count", "==", 0),
            MeasurementRequirement("b1.cross-variant-untraced-divergences", "count", "==", 0),
            MeasurementRequirement("b1.real-clip-parameter-note-mismatches", "count", "==", 0),
            MeasurementRequirement("b1.detector-independent-replay-mismatches", "count", "==", 0),
        ),
        artifacts=("b1.real-clip-measurement", "b1.cross-variant-comparison"),
    ),
    # §6: lifecycle suites on both variants on the native adapter and the
    # fixture tracker; bounds 1–3 thresholded, bound 4 recorded.
    "B2": UnitRequirement(
        suites=(
            "src/vision/tests/test_track_lifecycle.py",
            "src/vision/tests/test_trajectory_spool.py",
            "src/vision/tests/test_evidence_pipeline.py",
            "src/vision/tests/test_bytetrack_adapter.py",
            "src/vision/tests/test_bytetrack_runtime.py",
            "src/vision/tests/test_tracker_update.py",
            "src/vision/tests/test_track_finalization.py",
            "src/vision/tests/test_artifact_store.py",
            "src/vision/tests/test_artifact_store_windows.py",
            "tools/qualification/tests",
        ),
        variants=QUALIFIED_CPU_VARIANTS,
        measurements=(
            MeasurementRequirement("b2.per-live-held-evidence-bytes-max", "bytes", "<=", 544 * KIB),
            MeasurementRequirement("b2.per-retired-traced-bytes-slope", "bytes/track", "<=", 16 * KIB),
            MeasurementRequirement("b2.retired-slope-duration-variation", "ratio", "<=", 0.10),
            MeasurementRequirement("b2.retired-slope-crop-variation", "ratio", "<=", 0.10),
            MeasurementRequirement("b2.process-memory-retired-slope", "bytes/track", "<=", 16 * KIB),
            MeasurementRequirement("b2.completion-peak-bytes", "bytes"),
            MeasurementRequirement("b2.staging-peak-bytes", "bytes"),
        ),
        artifacts=("b2.memory-harness-output",),
    ),
    # §7: exact edges, existing body budgets, real-store completion time with
    # ≥ 2× headroom against the worker request timeout.
    "B3": UnitRequirement(
        suites=(
            "src/vision/tests/test_evidence_encoder.py",
            "src/vision/tests/test_evidence_admission.py",
            "src/vision/tests/test_evidence_pipeline.py",
            "src/vision/tests/test_worker_completion_v3.py",
            "src/vision/tests/test_completion_contract_bounds.py",
            "tests/Mavi.IntegrationTests/WorkerContractV3Tests",
            "tests/Mavi.IntegrationTests/S1BoundAgreementTests",
        ),
        variants=QUALIFIED_CPU_VARIANTS,
        measurements=(
            MeasurementRequirement("b3.python-worst-shape-body-bytes", "bytes", "<=", 40 * MIB),
            MeasurementRequirement("b3.dotnet-worst-shape-body-bytes", "bytes", "<=", 32 * MIB),
            MeasurementRequirement("b3.worker-request-timeout-ms", "ms"),
            MeasurementRequirement("b3.real-store-completion-wall-ms", "ms", timing=True),
        ),
        artifacts=("b3.sealing-scale-output",),
    ),
    # §8: Python/.NET agreement, replay and both non-compensable windows.
    "B4": UnitRequirement(
        suites=(
            "src/vision/tests/test_worker_completion_v3.py",
            "tests/Mavi.Application.Tests/CompletionDigestGoldenTests",
            "tests/Mavi.IntegrationTests/VisionResultCompletionV3ApiTests",
            "tests/Mavi.IntegrationTests/VisionResultCompletionApiTests",
            "tests/Mavi.IntegrationTests/VisionResultCompletionCommitFailureTests",
        ),
        variants=(),
        measurements=(),
        artifacts=("b4.completion-v3-golden",),
    ),
    # §9: automated suites plus at least two real clips.
    "B5": UnitRequirement(
        suites=(
            "tests/Mavi.IntegrationTests/TrackEvidenceSetReadApiTests",
            "src/web/mavi-web",
        ),
        variants=(),
        measurements=(MeasurementRequirement("b5.real-video-clips", "count", ">=", 2),),
        artifacts=("b5.real-video-record", "b5.visual-qa-record"),
    ),
    # §10: the Task-10 matrix on the measured SHA, records retained.
    "B6": UnitRequirement(
        suites=("task10:cpu-candidate",),
        variants=QUALIFIED_CPU_VARIANTS,
        measurements=(),
        artifacts=("b6.task10-records",),
    ),
    # §11: executed with the measured code, isolation evidenced before/after.
    "DISCONNECTED": UnitRequirement(
        suites=(),
        variants=(),
        measurements=(),
        artifacts=("disconnected.run-record", "disconnected.runtime-bundle-manifest"),
    ),
}


@dataclass(frozen=True, order=True)
class Finding:
    unit: str
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.unit}: {self.code}: {self.detail}"


# --------------------------------------------------------------------------- helpers
def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def is_behavior_bearing(path: str) -> bool:
    return _matches(path, BEHAVIOR_BEARING_SURFACE)


def invalidated_units(changed_paths: Iterable[str], cited: dict[str, set[str]]) -> dict[str, set[str]]:
    """Map each changed path to the units §2.2 says it invalidates.

    ``cited`` maps a unit to the suite paths it relies on. Behavior-bearing
    paths the table does not name invalidate every unit: an unmapped change is
    treated as the widest one rather than as a free pass.
    """
    result: dict[str, set[str]] = {}
    for path in changed_paths:
        units: set[str] = set(ALWAYS_EVIDENCE.get(path, ()))
        for unit, suites in cited.items():
            if any(path == suite or path.startswith(suite.rstrip("/") + "/") for suite in suites):
                units.add(unit)
        if _matches(path, EVIDENCE_TEST_TREES):
            if units:
                result[path] = units
            continue
        if not is_behavior_bearing(path):
            continue
        for patterns, mapped in INVALIDATION_MAP:
            if _matches(path, patterns):
                units.update(mapped)
        if not units:
            units.update(UNITS)
        result[path] = units
    return result


def _limit_holds(value: float, op: str, bound: float) -> bool:
    return {
        "<=": value <= bound,
        "<": value < bound,
        ">=": value >= bound,
        ">": value > bound,
        "==": value == bound,
    }[op]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------- JUnit
def suite_counts_from_junit(xml_path: Path, suite_filter: str | None = None) -> dict[str, Any]:
    """Pass/skip/fail/error counts from a pytest/xUnit JUnit XML.

    ``suite_filter`` restricts to test cases whose ``file`` or ``classname``
    contains it, so one XML covering several suites can yield per-suite counts.
    Counts come from the test cases themselves, never from summary attributes.
    """
    root = ElementTree.parse(xml_path).getroot()
    cases = root.iter("testcase")
    counts = {"passed": 0, "skipped": 0, "failed": 0, "errors": 0, "passedTests": [], "skippedTests": []}
    seen = 0
    for case in cases:
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        origin = f"{case.get('file', '')} {case.get('classname', '')}"
        if suite_filter is not None and suite_filter not in origin:
            continue
        seen += 1
        if case.find("failure") is not None:
            counts["failed"] += 1
        elif case.find("error") is not None:
            counts["errors"] += 1
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
            counts["skippedTests"].append(name)
        else:
            counts["passed"] += 1
            counts["passedTests"].append(name)
    if seen == 0:
        raise ValueError(f"junit_no_matching_testcases:{xml_path}:{suite_filter}")
    return counts


# --------------------------------------------------------------------------- checks
class _Checker:
    def __init__(self, record: dict[str, Any], repo_root: Path | None) -> None:
        self.record = record
        self.repo_root = repo_root
        self.findings: list[Finding] = []

    def fail(self, unit: str, code: str, detail: str) -> None:
        self.findings.append(Finding(unit, code, detail))

    # -- structure ----------------------------------------------------------------
    def schema(self) -> bool:
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - environment guard
            self.fail("record", "jsonschema_unavailable", "install jsonschema to validate the record")
            return False
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(self.record), key=lambda error: list(error.absolute_path))
        for error in errors:
            where = "/".join(str(part) for part in error.absolute_path) or "(root)"
            self.fail("record", "schema_invalid", f"{where}: {error.message}")
        return not errors

    # -- per unit -----------------------------------------------------------------
    def unit(self, name: str) -> None:
        unit = self.record["units"][name]
        if unit["verdict"] != "PASS":
            return
        required = UNIT_REQUIREMENTS[name]
        measured_sha = self._unit_sha(name)
        self._suites(name, unit, required, measured_sha)
        self._measurements(name, unit, required, measured_sha)
        self._artifacts(name, unit, required, measured_sha)
        if name == "DISCONNECTED":
            self._disconnected(measured_sha)

    def _unit_sha(self, name: str) -> str:
        return self.record["units"][name].get("measuredSha", self.record["measuredSha"])

    def _run(self, unit: str, run_id: str, measured_sha: str, what: str) -> dict[str, Any] | None:
        run = self.record["runs"].get(run_id)
        if run is None:
            self.fail(unit, "run_missing", f"{what} cites run {run_id!r}, which is not recorded")
            return None
        if run["headSha"] != measured_sha:
            self.fail(unit, "head_sha_mismatch", f"{what}: run {run_id} head_sha {run['headSha']} != measured {measured_sha}")
        if run["conclusion"] != "success":
            self.fail(unit, "run_not_successful", f"{what}: run {run_id} concluded {run['conclusion']}")
        if run["kind"] == "workflow" and ("workflow" not in run or "runId" not in run):
            self.fail(unit, "run_identity_incomplete", f"workflow run {run_id} lacks workflow/runId")
        if run["kind"] == "local":
            if not run.get("host") or not run.get("command"):
                self.fail(unit, "run_identity_incomplete", f"local run {run_id} lacks host/command")
            elif run["host"] not in self.record["hosts"]:
                self.fail(unit, "host_missing", f"local run {run_id} names unknown host {run['host']!r}")
            if run.get("cleanTree") is not True:
                self.fail(unit, "run_tree_not_clean", f"local run {run_id} does not attest a clean tree")
        return run

    def _suites(self, name: str, unit: dict[str, Any], required: UnitRequirement, measured_sha: str) -> None:
        suites = self.record["suites"]
        cited = []
        for suite_id in unit["suites"]:
            entry = suites.get(suite_id)
            if entry is None:
                self.fail(name, "suite_missing", f"cites suite result {suite_id!r}, which is not recorded")
                continue
            cited.append(entry)
            self._run(name, entry["run"], measured_sha, f"suite {suite_id}")
            if entry["junitArtifact"] not in self.record["retainedArtifacts"]:
                self.fail(name, "junit_not_retained", f"suite {suite_id} JUnit {entry['junitArtifact']!r} is not a retained artifact")
            if entry["failed"] or entry["errors"]:
                self.fail(name, "suite_failed", f"suite {suite_id}: {entry['failed']} failed, {entry['errors']} errors")
            if entry["passed"] == 0:
                self.fail(name, "suite_empty", f"suite {suite_id} passed no test")
            if entry["skipped"] != len(entry["skippedTests"]) or entry["passed"] != len(entry["passedTests"]):
                self.fail(name, "count_inconsistent", f"suite {suite_id}: counts do not match the named passed/skipped tests")
            for test in entry["skippedTests"]:
                if not self._skip_is_paired(test, entry["variant"]):
                    self.fail(name, "skip_not_permitted", f"suite {suite_id} skipped {test} on {entry['variant']} without a paired-variant counterpart")
        for suite in required.suites:
            variants = required.variants or (None,)
            for variant in variants:
                if not any(
                    entry["suite"] == suite and (variant is None or entry["variant"] == variant)
                    for entry in cited
                ):
                    where = f" on {variant}" if variant else ""
                    self.fail(name, "variant_result_missing", f"required suite {suite}{where} has no cited result")

    def _skip_is_paired(self, test: str, variant: str) -> bool:
        """A skip is permitted only with *positive* evidence: the named
        counterpart test is among the passed tests of a clean result for the
        counterpart suite on the other variant."""
        for pair in self.record["pairedVariantSkips"]:
            if pair["test"] != test or pair["skipsOn"] != variant or pair["counterpartVariant"] == variant:
                continue
            for entry in self.record["suites"].values():
                if (
                    entry["suite"] == pair["counterpartSuite"]
                    and entry["variant"] == pair["counterpartVariant"]
                    and not entry["failed"]
                    and not entry["errors"]
                    and pair["counterpartTest"] in entry["passedTests"]
                ):
                    return True
        return False

    def _measurements(self, name: str, unit: dict[str, Any], required: UnitRequirement, measured_sha: str) -> None:
        measurements = self.record["measurements"]
        by_metric: dict[str, dict[str, Any]] = {}
        for measurement_id in unit["measurements"]:
            entry = measurements.get(measurement_id)
            if entry is None:
                self.fail(name, "measurement_missing", f"cites measurement {measurement_id!r}, which is not recorded")
                continue
            by_metric[entry["metric"]] = entry
            self._run(name, entry["run"], measured_sha, f"measurement {measurement_id}")
            if entry["host"] not in self.record["hosts"]:
                self.fail(name, "host_missing", f"measurement {measurement_id} names unknown host {entry['host']!r}")
            limit = entry.get("limit")
            if limit is not None and not _limit_holds(entry["value"], limit["op"], limit["value"]):
                self.fail(name, "limit_violated", f"{entry['metric']} = {entry['value']} violates {limit['op']} {limit['value']}")
            if entry["unit"] in TIMING_UNITS and entry.get("stats") is not None:
                self._timing(name, measurement_id, entry)
            if entry.get("artifact") is not None and entry["artifact"] not in self.record["retainedArtifacts"]:
                self.fail(name, "artifact_missing", f"measurement {measurement_id} cites unretained artifact {entry['artifact']!r}")
        for requirement in required.measurements:
            entry = by_metric.get(requirement.metric)
            if entry is None:
                self.fail(name, "measurement_missing", f"required metric {requirement.metric} is not cited")
                continue
            if entry["unit"] != requirement.unit:
                self.fail(name, "measurement_unit_mismatch", f"{requirement.metric} in {entry['unit']}, expected {requirement.unit}")
            if requirement.limit_op is not None:
                # The plan's limit is binding whatever the record declares.
                if not _limit_holds(entry["value"], requirement.limit_op, requirement.limit_value):
                    self.fail(name, "limit_violated", f"{requirement.metric} = {entry['value']} violates plan limit {requirement.limit_op} {requirement.limit_value}")
            if requirement.timing:
                if entry.get("stats") is None:
                    self.fail(name, "timing_incomplete", f"{requirement.metric} has no min/p50/p95/max")
                else:
                    self._timing(name, requirement.metric, entry)
        if name == "B3":
            self._b3_headroom(by_metric)

    def _timing(self, name: str, label: str, entry: dict[str, Any]) -> None:
        if entry.get("samples", 0) < MINIMUM_TIMING_SAMPLES:
            self.fail(name, "timing_incomplete", f"{label}: n = {entry.get('samples', 0)} < {MINIMUM_TIMING_SAMPLES}")
        if entry.get("repeats", 0) < MINIMUM_TIMING_REPEATS:
            self.fail(name, "timing_incomplete", f"{label}: {entry.get('repeats', 0)} repeats < {MINIMUM_TIMING_REPEATS}")
        if entry.get("warmupExcluded") is not True:
            self.fail(name, "timing_incomplete", f"{label}: warm-up exclusion not attested")
        stats = entry.get("stats") or {}
        if stats and not stats["min"] <= stats["p50"] <= stats["p95"] <= stats["max"]:
            self.fail(name, "timing_inconsistent", f"{label}: stats are not ordered min <= p50 <= p95 <= max")
        if "p50RunSpread" not in stats:
            self.fail(name, "timing_incomplete", f"{label}: run-to-run p50 spread not recorded")

    def _b3_headroom(self, by_metric: dict[str, dict[str, Any]]) -> None:
        timeout = by_metric.get("b3.worker-request-timeout-ms")
        wall = by_metric.get("b3.real-store-completion-wall-ms")
        if timeout is None or wall is None or wall.get("stats") is None:
            return
        # §7.4: headroom below 2× against the worker request timeout is blocking.
        if wall["stats"]["max"] * 2 > timeout["value"]:
            self.fail("B3", "completion_headroom_insufficient", f"max completion {wall['stats']['max']} ms × 2 > worker timeout {timeout['value']} ms")

    def _artifacts(self, name: str, unit: dict[str, Any], required: UnitRequirement, measured_sha: str) -> None:
        artifacts = self.record["retainedArtifacts"]
        for artifact_id in unit["artifacts"]:
            entry = artifacts.get(artifact_id)
            if entry is None:
                self.fail(name, "artifact_missing", f"cites artifact {artifact_id!r}, which is not retained")
                continue
            self._run(name, entry["run"], measured_sha, f"artifact {artifact_id}")
            self._verify_file(name, artifact_id, entry)
        for required_id in required.artifacts:
            if required_id not in unit["artifacts"]:
                self.fail(name, "artifact_missing", f"required artifact {required_id} is not cited")

    def _verify_file(self, name: str, artifact_id: str, entry: dict[str, Any]) -> None:
        if self.repo_root is None:
            return
        path = (self.repo_root / entry["path"]).resolve()
        if not path.is_relative_to(self.repo_root.resolve()) or not path.is_file():
            self.fail(name, "artifact_file_missing", f"{artifact_id}: {entry['path']} is not a retained file")
            return
        if sha256_file(path) != entry["sha256"]:
            self.fail(name, "artifact_hash_mismatch", f"{artifact_id}: {entry['path']} does not match its sha256")

    def _disconnected(self, measured_sha: str) -> None:
        record = self.record.get("disconnected")
        if record is None:
            self.fail("DISCONNECTED", "disconnected_record_missing", "no disconnected block")
            return
        if record["runtimeBundleSourceCommit"] != measured_sha:
            self.fail("DISCONNECTED", "runtime_bundle_not_measured_code", f"bundle sourceCommit {record['runtimeBundleSourceCommit']} != measured {measured_sha}")
        for phase in ("isolationBefore", "isolationAfter"):
            probe = record[phase]
            if not probe["passed"] or not probe["proxyEnvironmentAbsent"] or any(item["reachable"] for item in probe["probes"]):
                self.fail("DISCONNECTED", "isolation_not_evidenced", f"{phase} does not show an isolated host")

    # -- closure (§2.3) -------------------------------------------------------------
    def closure(self) -> None:
        closure = self.record["closure"]
        claims_closed = self.record.get("s1Closed") is True
        if claims_closed:
            if closure is None:
                self.fail("record", "closure_missing", "s1Closed requires a §2.3 closure block")
            for name in UNITS:
                if self.record["units"][name]["verdict"] != "PASS":
                    self.fail("record", "closure_units_open", f"s1Closed with {name} {self.record['units'][name]['verdict']}")
        if closure is None:
            return
        cited = {
            name: {self.record["suites"][suite]["suite"] for suite in unit["suites"] if suite in self.record["suites"]}
            for name, unit in self.record["units"].items()
        }
        for path, units in sorted(invalidated_units(closure["changedPaths"], cited).items()):
            for name in sorted(units):
                if self.record["units"][name]["verdict"] == "PASS" and self._unit_sha(name) != closure["mergeSha"]:
                    self.fail(name, "closure_rerun_required", f"{path} changed between measured and merge SHA; {name} was not re-measured on {closure['mergeSha']}")

    def verify_git_diff(self) -> None:
        """The recorded changedPaths must be the real diff, not a hand-written list."""
        closure = self.record["closure"]
        if closure is None or self.repo_root is None:
            return
        try:
            actual = subprocess.run(
                ["git", "diff", "--name-only", self.record["measuredSha"], closure["mergeSha"]],
                cwd=self.repo_root, check=True, capture_output=True, text=True,
            ).stdout.split()
        except (OSError, subprocess.CalledProcessError) as exc:
            self.fail("record", "closure_diff_unverifiable", f"git diff failed: {exc}")
            return
        if sorted(actual) != sorted(closure["changedPaths"]):
            self.fail("record", "closure_diff_mismatch", "recorded changedPaths differ from git diff --name-only measured..merge")


def check_record(record: dict[str, Any], *, repo_root: Path | None = None, verify_git: bool = False) -> list[Finding]:
    checker = _Checker(record, repo_root)
    if not checker.schema():
        return sorted(checker.findings)
    for name in UNITS:
        checker.unit(name)
    checker.closure()
    if verify_git:
        checker.verify_git_diff()
    return sorted(set(checker.findings))


def open_requirements(record: dict[str, Any]) -> dict[str, list[str]]:
    """For an OPEN unit: what a PASS would still need. Informational only."""
    result: dict[str, list[str]] = {}
    for name in UNITS:
        if record["units"][name]["verdict"] != "OPEN":
            continue
        trial = json.loads(json.dumps(record))
        trial["units"][name]["verdict"] = "PASS"
        trial["s1Closed"] = False
        missing = [f.code + ": " + f.detail for f in check_record(trial) if f.unit == name]
        result[name] = missing
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate an evidence record; exit 1 on any finding")
    check.add_argument("record", type=Path)
    check.add_argument("--repo-root", type=Path, default=None, help="verify retained files and the §2.3 git diff against this checkout")
    junit = sub.add_parser("junit", help="derive a suite entry's counts from JUnit XML")
    junit.add_argument("xml", type=Path)
    junit.add_argument("--suite", default=None)
    args = parser.parse_args(argv)

    if args.command == "junit":
        print(json.dumps(suite_counts_from_junit(args.xml, args.suite), indent=2, sort_keys=True))
        return 0

    record = json.loads(args.record.read_text(encoding="utf-8"))
    findings = check_record(record, repo_root=args.repo_root, verify_git=args.repo_root is not None)
    for finding in findings:
        print(finding)
    if not findings:
        verdicts = {name: record["units"][name]["verdict"] for name in UNITS}
        print("s1-evidence-record-valid", json.dumps(verdicts, sort_keys=True))
        for name, missing in open_requirements(record).items():
            print(f"{name} OPEN; a PASS still needs {len(missing)} item(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
