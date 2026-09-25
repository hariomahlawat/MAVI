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
import re
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = Path(__file__).resolve().with_name("s1-qualification-evidence.schema.json")
REPO_ROOT = Path(__file__).resolve().parents[2]
# The worker default (``WorkerSettings.request_timeout_seconds``) and its bound.
WORKER_SETTINGS_PATH = REPO_ROOT / "src/vision/mavi_vision/common/settings.py"  # WORKER_SETTINGS_RELATIVE
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
    # The harnesses that produce a unit's retained output are evidence whether
    # or not the record cites them as suites.
    "tests/Mavi.IntegrationTests/Qualification/S1SealingScaleTests.cs": ("B3",),
    "tests/Mavi.IntegrationTests/Qualification/QualificationGate.cs": ("B3",),
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
MAXIMUM_COMPLETION_TRACKS = 10_000
# §7.4 worst case: a trajectory plus four crops per Track.
WORST_CASE_SEALED_OBJECTS = MAXIMUM_COMPLETION_TRACKS * 5


# §3.1: the only skips a PASS admits, each an OS-conditional test that passes
# on the other variant. Keyed by (suite, variant it skips on). The golden-byte
# test is deliberately absent: PR A pins both variants, so B1 admits no golden
# skip. ``test_approved_paired_skips_are_the_os_conditional_tests`` fails if the
# source's OS-conditional tests drift from this list.
_WINDOWS, _LINUX = "windows-x86_64-cpu", "linux-x86_64-cpu"
APPROVED_PAIRED_SKIPS: dict[tuple[str, str], frozenset[str]] = {
    ("src/vision/tests/test_track_lifecycle.py", _WINDOWS): frozenset({
        "test_many_live_tracks_need_no_descriptor_each",
    }),
    ("src/vision/tests/test_artifact_store.py", _WINDOWS): frozenset({
        "test_rejects_symlink_escape",
        "test_rejected_intermediate_symlink_does_not_create_outside_directories",
        "test_rejects_symlinked_job_root_and_cleanup_preserves_target",
        "test_directory_swap_during_write_cannot_redirect_artifact_outside_root",
        "test_cleanup_superseded_attempts_never_follows_a_linked_attempt",
        "test_cleanup_superseded_attempts_does_not_follow_links_inside_an_attempt",
        "test_cleanup_superseded_attempts_rejects_a_linked_job_root",
        "test_append_read_and_remove_never_follow_a_leaf_symlink",
        "test_append_read_and_remove_refuse_a_symlinked_ancestor",
        "test_append_and_read_refuse_a_hard_linked_file",
        "test_append_and_read_refuse_a_fifo_without_blocking",
        "test_evidence_write_and_remove_refuse_a_linked_evidence_directory",
    }),
    ("src/vision/tests/test_artifact_store_windows.py", _LINUX): frozenset({
        "test_windows_rejects_junction_in_attempt_ancestry",
        "test_windows_parent_swap_cannot_redirect_publish",
        "test_windows_cleanup_does_not_follow_reparse_point",
        "test_windows_cleanup_preserves_sibling_attempt",
        "test_windows_publish_rechecks_authority_immediately_before_replace",
        "test_windows_denied_authority_leaves_no_destination_or_temp",
        "test_windows_post_replace_identity_failure_rolls_back_exact_published_handle",
        "test_windows_rejects_component_before_unicode_string_length_wrap",
        "test_windows_superseded_cleanup_removes_only_older_attempts",
        "test_windows_superseded_cleanup_rejects_junction_attempt",
        "test_windows_superseded_cleanup_does_not_follow_nested_junction",
        "test_windows_append_accumulates_through_append_only_handle",
        "test_windows_append_read_and_remove_refuse_junction_ancestor",
        "test_windows_remove_refuses_a_junction_leaf_and_preserves_its_target",
        "test_windows_append_and_read_refuse_a_hard_linked_file",
        "test_windows_remove_deletes_only_the_leaf_and_refuses_directories",
        "test_windows_write_stream_source_failure_leaves_no_destination_or_temp",
        "test_windows_evidence_write_and_remove_refuse_a_junctioned_evidence_directory",
    }),
    # PR A's own process-memory probes (tools/qualification/tests/test_s1_memory.py):
    # each platform's probe is exercised on that platform only.
    ("tools/qualification/tests", _WINDOWS): frozenset({"test_linux_probe_reads_this_process"}),
    ("tools/qualification/tests", _LINUX): frozenset({"test_windows_probe_reads_commit_charge"}),
}


def is_approved_skip(entry_suite: str, variant: str, test_id: str) -> bool:
    """Whether §3.1 approves this skip. A suite result is approved against its
    own list; a Task-10 aggregate result (``task10:<step>``, one XML covering
    many suites) is approved against the list of the source suite each test
    case belongs to, found from its classname."""
    name = test_function_name(test_id)
    if name in APPROVED_PAIRED_SKIPS.get((entry_suite, variant), frozenset()):
        return True
    if not entry_suite.startswith("task10:"):
        return False
    classname = test_id.rsplit("::", 1)[0]
    return any(
        approved_variant == variant and name in names and case_belongs(classname, suite_key(suite) or ())
        for (suite, approved_variant), names in APPROVED_PAIRED_SKIPS.items()
    )


def test_function_name(test_id: str) -> str:
    """``tests.test_x::test_name[param]`` -> ``test_name``."""
    return test_id.rsplit("::", 1)[-1].split("[", 1)[0]


# §10.4: the post-merge workflows a closure needs on the exact merge SHA.
POST_MERGE_WORKFLOWS = (
    "quality-gate.yml",
    "task10-runtime-qualification.yml",
    "task17-acceptance.yml",
)

NON_OUTCOME_ARTIFACTS = frozenset({
    "disconnected.run-record",
    "disconnected.runtime-bundle-manifest",
    "disconnected.isolation-before",
    "disconnected.isolation-after",
})

# §11: the reused probe, ``assert_outbound_internet_unavailable`` in
# ``tools/phase1/qualify_offline_variant.py``: exactly these targets (a test
# holds the two equal), and the fields its output carries.
ISOLATION_PROBE_TARGETS = (
    ("1.1.1.1", 443),
    ("8.8.8.8", 53),
    ("pypi.org", 443),
    ("github.com", 443),
    ("www.microsoft.com", 443),
)
ISOLATION_PROBE_FIELDS = ("passed", "proxyEnvironmentAbsent", "probes")

# §11: every step of the S1 operator path, each passed with named evidence.
DISCONNECTED_OUTCOMES = (
    "setupVerification",
    "workerStartup",
    "realVideoProcessing",
    "completionV3",
    "sealedTrackEvidence",
    "trackDetail",
    "reviewInvestigationEvidenceSet",
)


def other_variant(variant: str) -> str:
    return next(other for other in QUALIFIED_CPU_VARIANTS if other != variant)


WORKER_SETTINGS_RELATIVE = "src/vision/mavi_vision/common/settings.py"


def worker_request_timeout_bounds_ms(text: str | None = None) -> tuple[float, float]:
    """(default, maximum) of ``WorkerSettings.request_timeout_seconds``, in ms,
    from ``text`` (the settings source at the measured SHA) or this checkout."""
    text = WORKER_SETTINGS_PATH.read_text(encoding="utf-8") if text is None else text
    match = re.search(r"request_timeout_seconds: float = Field\(default=([0-9.]+), ge=[0-9.]+, le=([0-9.]+)\)", text)
    if match is None:
        raise RuntimeError("worker_request_timeout_setting_not_found")
    return float(match.group(1)) * 1000.0, float(match.group(2)) * 1000.0

TRAJECTORY_CHUNK_POINTS = 4096  # mavi_vision.video.trajectory_spool.DEFAULT_CHUNK_POINTS
SEALING_WALL_METRIC = "b3.real-store-completion-wall-ms"
SEALING_OUTPUT_ARTIFACT = "b3.sealing-scale-output"
TASK10_WORKFLOW = "task10-runtime-qualification.yml"
QUALITY_GATE_WORKFLOW = "quality-gate.yml"
# §10.1 / §4: every JUnit file and JSON record the Task-10 CPU job writes.
TASK10_JUNIT_STEPS = (
    "runtime-tooling",
    "s1-boundary",
    "runtime-probe-real-torch",
    "bytetrack-runtime",
    "real-clip-harness",
    "s1-qualification-harness",
    "production-processor-runtime",
)
# §2.2: what each Task-10 JUnit step runs, so a change to any of it invalidates
# the units citing the step. A test holds this equal to the workflow's commands.
TASK10_STEP_SOURCES: dict[str, tuple[str, ...]] = {
    "runtime-tooling": (
        "src/vision/tests/test_runtime_probe.py",
        "src/vision/tests/test_resolve_mmdet_config.py",
        "src/vision/tests/test_runtime_metadata.py",
    ),
    "s1-boundary": tuple(
        f"src/vision/tests/test_{name}.py"
        for name in (
            "rtmdet_colour_space", "mmdetection_runtime", "runtime_errors", "bytetrack_profile_semantics",
            "bytetrack_adapter", "production_processor", "process_video", "track_lifecycle", "trajectory_spool",
            "evidence_profile", "evidence_quality", "evidence_encoder", "evidence_selector", "evidence_admission",
            "evidence_pipeline", "evidence_scripted_corpus", "worker_completion_v3", "completion_contract_bounds",
            "tracker_update", "track_finalization", "artifact_store", "artifact_store_windows", "artifact_publisher",
            "analytical_models", "s1_bound_agreement",
        )
    ),
    "runtime-probe-real-torch": ("src/vision/tests/test_runtime_probe.py",),
    "bytetrack-runtime": ("src/vision/tests/test_bytetrack_runtime.py",),
    "real-clip-harness": ("src/vision/tests/test_measure_evidence_real_clips.py",),
    "s1-qualification-harness": ("tools/qualification/tests",),
    "production-processor-runtime": ("src/vision/tests/test_production_processor_runtime.py",),
}
# Records a Task-10 job writes about itself (its head, variant, platform), so
# the two variants' bytes cannot be equal; the others (``runtime.json`` is a
# copy of a committed file) legitimately may be.
TASK10_JOB_RECORDS = frozenset({"bytetrack-qualification.json", "production-composition-qualification.json"})
TASK10_RECORDS = (
    "runtime-probe.json",
    "resolved-config.json",
    "runtime.json",
    "production-runtime-smoke.json",
    "bytetrack-qualification.json",
    "production-composition-qualification.json",
)

# Suites whose result depends on the Python runtime variant. They are required
# on every variant a unit names. Platform (.NET) and web suites run once, in the
# quality gate, and carry no runtime variant.
VARIANT_SUITE_PREFIXES = ("src/vision/", "tools/qualification/", "task10:")


def required_variants(required: UnitRequirement, suite: str) -> tuple[str | None, ...]:
    if required.variants and suite.startswith(VARIANT_SUITE_PREFIXES):
        return required.variants
    return (None,)

B2_OUTPUT_ARTIFACT = "b2.memory-harness-output"
B2_LIFECYCLE_ARTIFACT = "b2.staging-lifecycle"
# §6.3: every lifecycle property the staging-lifecycle harness must show.
STAGING_LIFECYCLE_CHECKS = (
    "failedAttemptCleaned",
    "leaseLostStagingRetained",
    "supersededAttemptRemoved",
    "siblingJobUntouched",
    "successfulStagingRetainedForPlatform",
    "peaksWithinDerivedBound",
)
B2_BASE_MEASUREMENTS = (
    MeasurementRequirement("b2.per-live-held-evidence-bytes-max", "bytes", "<=", 544 * KIB),
    # Bound 1, trajectory part: at most one spool chunk buffered per live Track.
    MeasurementRequirement("b2.per-live-buffered-trajectory-points-max", "count", "<=", TRAJECTORY_CHUNK_POINTS),
    MeasurementRequirement("b2.per-retired-traced-bytes-slope", "bytes/track", "<=", 16 * KIB),
    MeasurementRequirement("b2.retired-slope-duration-variation", "ratio", "<=", 0.10),
    MeasurementRequirement("b2.retired-slope-crop-variation", "ratio", "<=", 0.10),
    MeasurementRequirement("b2.process-memory-retired-slope", "bytes/track", "<=", 16 * KIB),
    # Bound 3, live part: mandatory and content-bound, but recorded as the
    # regression baseline and reconciled with bound 1, never thresholded
    # against it (bound 1 is the encoded-holder bound, not a process ceiling).
    MeasurementRequirement("b2.process-memory-per-live-track-slope", "bytes/track"),
    MeasurementRequirement("b2.completion-peak-bytes", "bytes"),
    MeasurementRequirement("b2.staging-peak-bytes", "bytes"),
    # §6.3: the observed staging peak within the run's own ADR-013 derivation.
    MeasurementRequirement("b2.staging-peak-to-derived-bound-ratio", "ratio", "<=", 1.0),
)
# Host fields a harness output must measure and the record's host must equal.
MEASURED_HOST_FIELDS = ("cpuModel", "physicalCores", "logicalCores", "ramBytes", "os", "osBuild", "stagingFilesystem")
LIVE_LEVEL_MINIMUM = 5
# §5.3: each B1 count is derived by tools/qualification/s1_b1.py, never typed in.
B1_BASELINE_RELATIVE = "docs/qualification/stage2-s1/b1-accepted-real-clip-baseline.json"
B1_COUNTS = {
    "b1.within-variant-repeat-mismatches": "withinVariantRepeatMismatches",
    "b1.cross-variant-untraced-divergences": "untracedCrossVariantDivergences",
    "b1.real-clip-parameter-note-mismatches": "parameterNoteMismatches",
    "b1.detector-independent-replay-mismatches": "replayMismatches",
}
# §7: the body sizes are proven by these tests, which assert the budgets; the
# recorded value is informational only once the proving test passed.
B3_PROVING_TESTS = {
    "b3.python-worst-shape-body-bytes": ("src/vision/tests/test_worker_completion_v3.py", "test_worst_shape_body_stays_within_the_budget"),
    "b3.dotnet-worst-shape-body-bytes": ("tests/Mavi.IntegrationTests/WorkerContractV3Tests", "WorstShapeBodyFitsUnderLimit"),
}
B5_CLIP_METRIC = "b5.real-video-clips"
# §9.2: what a real-video clip must have shown to count.
B5_CLIP_CHECKS = ("completionAccepted", "trackDetailVerified", "evidenceSetVerified")
SEALING_HOST_FIELDS = ("cpuModel", "logicalCores")

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
            # §6.3: platform janitor ownership of staging after completion.
            "tests/Mavi.IntegrationTests/StagingJanitorTests",
        ),
        variants=QUALIFIED_CPU_VARIANTS,
        # §6.2: native and process memory differ per OS build, so every B2
        # value is measured on each qualified variant.
        measurements=tuple(
            MeasurementRequirement(f"{base.metric}.{variant}", base.unit, base.limit_op, base.limit_value, base.timing)
            for variant in QUALIFIED_CPU_VARIANTS
            for base in B2_BASE_MEASUREMENTS
        ),
        artifacts=tuple(
            f"{artifact}.{variant}" for artifact in (B2_OUTPUT_ARTIFACT, B2_LIFECYCLE_ARTIFACT) for variant in QUALIFIED_CPU_VARIANTS
        ),
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
            "src/vision/tests/test_s1_bound_agreement.py",
            "tests/Mavi.IntegrationTests/WorkerContractV3Tests",
            "tests/Mavi.IntegrationTests/S1BoundAgreementTests",
        ),
        variants=QUALIFIED_CPU_VARIANTS,
        measurements=(
            MeasurementRequirement("b3.python-worst-shape-body-bytes", "bytes", "<=", 40 * MIB),
            MeasurementRequirement("b3.dotnet-worst-shape-body-bytes", "bytes", "<=", 32 * MIB),
            MeasurementRequirement("b3.worker-request-timeout-ms", "ms"),
            # §7.4: on the real filesystem of each supported Development OS.
            *(MeasurementRequirement(f"{SEALING_WALL_METRIC}.{variant}", "ms", timing=True) for variant in QUALIFIED_CPU_VARIANTS),
        ),
        artifacts=tuple(f"{SEALING_OUTPUT_ARTIFACT}.{variant}" for variant in QUALIFIED_CPU_VARIANTS),
    ),
    # §8: Python/.NET agreement, replay and the commit boundary. Since S1.4 B3 F2 the
    # synchronous v3 suite covers the default (not activated) platform and the completion
    # 3.1 hand-off suite the activated one; F4 re-derives the B4 set with the finalizer's
    # publication and recovery suites.
    "B4": UnitRequirement(
        suites=(
            "src/vision/tests/test_worker_completion_v3.py",
            "tests/Mavi.Application.Tests/CompletionDigestGoldenTests",
            "tests/Mavi.IntegrationTests/VisionResultCompletionV3ApiTests",
            "tests/Mavi.IntegrationTests/VisionFinalizationSubmissionApiTests",
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
        suites=tuple(f"task10:{step}" for step in TASK10_JUNIT_STEPS),
        variants=QUALIFIED_CPU_VARIANTS,
        measurements=(),
        artifacts=tuple(f"b6.{variant}.{record}" for variant in QUALIFIED_CPU_VARIANTS for record in TASK10_RECORDS),
    ),
    # §11: executed with the measured code, isolation evidenced before/after.
    "DISCONNECTED": UnitRequirement(
        suites=(),
        variants=(),
        measurements=(),
        artifacts=(
            "disconnected.run-record",
            "disconnected.runtime-bundle-manifest",
            "disconnected.isolation-before",
            "disconnected.isolation-after",
        ),
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


SUITE_SOURCE_SUFFIXES = (".cs", ".py", ".ts", ".tsx")
SHARED_FIXTURE_ROOT = "tests/fixtures/"


def suite_sources(suite: str) -> tuple[str, ...]:
    """The source paths a cited suite runs: a Task-10 step's test files
    (``TASK10_STEP_SOURCES``), otherwise the suite path itself."""
    if suite.startswith("task10:"):
        return TASK10_STEP_SOURCES.get(suite.split(":", 1)[1], ())
    return (suite,)


def suite_covers(suite: str, path: str) -> bool:
    """Whether a changed path is part of a cited suite's source.

    Python suites are cited by file, the web suite by directory, and .NET
    suites by their extension-less class path (``tests/Proj/ClassTests`` is
    ``tests/Proj/ClassTests.cs``, including partial ``ClassTests.*.cs`` files).
    A Task-10 step covers every file it runs.
    """
    if suite.startswith("task10:"):
        return any(suite_covers(source, path) for source in suite_sources(suite))
    suite = suite.rstrip("/")
    if path == suite or path.startswith(suite + "/"):
        return True
    if path.startswith(suite + "."):
        return path.endswith(SUITE_SOURCE_SUFFIXES)
    return False


def test_project(path: str) -> str | None:
    """The test project a path belongs to (``src/vision/tests``,
    ``tools/qualification/tests``, ``tests/<Project>``), or ``None``."""
    for root in ("src/vision/tests", "tools/qualification/tests"):
        if path == root or path.startswith(root + "/"):
            return root
    match = re.match(r"(tests/[^/]+)(/|$)", path)
    return match.group(1) if match else None


def is_shared_test_support(path: str) -> bool:
    """A file other suites of its project can depend on without citing it:
    every file of a .NET test project (helpers there are test classes too,
    for example ``VisionResultCompletionApiTests.SeedVideoAsync``), and any
    non-``test_*.py`` file of a Python test tree (``conftest.py``, fixtures)."""
    project = test_project(path)
    if project is None:
        return False
    if project.startswith("tests/"):
        return True
    return not path.rsplit("/", 1)[-1].startswith("test_")


def invalidated_units(changed_paths: Iterable[str], cited: dict[str, set[str]]) -> dict[str, set[str]]:
    """Map each changed path to the units §2.2 says it invalidates.

    ``cited`` maps a unit to the suite paths it relies on. A cited suite's own
    source invalidates its unit; so does shared test support (conftest,
    fixtures, .NET helpers) in the same test project, which cited suites use
    without citing. Behavior-bearing paths the table does not name invalidate
    every unit: an unmapped change is treated as the widest one rather than as
    a free pass.
    """
    result: dict[str, set[str]] = {}
    for path in changed_paths:
        units: set[str] = set(ALWAYS_EVIDENCE.get(path, ()))
        shared = is_shared_test_support(path)
        for unit, suites in cited.items():
            if any(
                suite_covers(suite, path)
                or (shared and any(test_project(source) == test_project(path) for source in suite_sources(suite)))
                for suite in suites
            ):
                units.add(unit)
            if path.startswith(SHARED_FIXTURE_ROOT) and suites:
                # Repository fixtures are read by Python, .NET and web suites
                # alike: every unit resting on any suite may depend on them.
                units.add(unit)
        if _matches(path, EVIDENCE_TEST_TREES) or not is_behavior_bearing(path):
            # Test trees and non-surface paths invalidate only through the
            # suites that cite them, never by themselves.
            if units:
                result[path] = units
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
# Suites whose JUnit XML is a dedicated file (the web suite's own report, the
# Task-10 job record): every test case in it belongs to the suite.
WHOLE_FILE_SUITE_PREFIXES = ("src/web/", "task10:")


def quality_gate_result_path(suite: str) -> str | None:
    """The file the Quality Gate writes a .NET or web suite's results to: one
    TRX per test project (``trx/<Project>.trx``), one Vitest JUnit for the web
    client (``junit/mavi-web.xml``). ``None`` for any other suite."""
    if suite.startswith("tests/"):
        return f"trx/{suite.split('/')[1]}.trx"
    if suite.startswith("src/web/"):
        return "junit/mavi-web.xml"
    return None


def suite_key(suite: str) -> tuple[str, ...] | None:
    """The components a test case's ``classname`` must contain to belong to
    ``suite``: its last two path components, extension dropped
    (``src/vision/tests/test_x.py`` -> ``tests, test_x``;
    ``tests/Mavi.IntegrationTests/ClassTests`` -> ``IntegrationTests, ClassTests``).
    ``None`` for whole-file suites."""
    if suite.startswith(WHOLE_FILE_SUITE_PREFIXES):
        return None
    stem = suite.rstrip("/")
    stem = stem[:-3] if stem.endswith(".py") else stem
    parts = tuple(part for part in re.split(r"[/.]", stem) if part)
    return parts[-2:]


def case_belongs(classname: str, key: tuple[str, ...]) -> bool:
    """Component-boundary containment: ``test_evidence`` never matches
    ``test_evidence_encoder``."""
    components = [part for part in re.split(r"[/.]", classname) if part]
    width = len(key)
    return any(tuple(components[index:index + width]) == key for index in range(len(components) - width + 1))


TRX_NAMESPACE = "{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}"
# TRX outcomes a result may count; anything else (Timeout, Aborted, ...) is a failure.
TRX_PASSED = frozenset({"Passed"})
TRX_SKIPPED = frozenset({"NotExecuted"})  # an xUnit ``Skip``
TRX_ERROR = frozenset({"Error"})


def _junit_cases(root: ElementTree.Element) -> Iterable[tuple[str, str, str]]:
    for case in root.iter("testcase"):
        if case.find("failure") is not None:
            status = "failed"
        elif case.find("error") is not None:
            status = "errors"
        elif case.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"
        yield case.get("classname", ""), case.get("name", ""), status


def _trx_cases(root: ElementTree.Element) -> Iterable[tuple[str, str, str]]:
    """``dotnet test --logger trx`` results: each ``UnitTestResult`` joined to its
    ``UnitTest`` definition for the class name. The test name is the result's
    ``testName`` without its class prefix, so theory arguments stay distinct."""
    classes = {
        test.get("id"): method.get("className", "")
        for test in root.iter(f"{TRX_NAMESPACE}UnitTest")
        for method in test.iter(f"{TRX_NAMESPACE}TestMethod")
    }
    for result in root.iter(f"{TRX_NAMESPACE}UnitTestResult"):
        classname = classes.get(result.get("testId"))
        if classname is None:
            raise ValueError(f"trx_result_without_definition:{result.get('testName')}")
        name = result.get("testName", "")
        name = name[len(classname) + 1:] if name.startswith(classname + ".") else name
        outcome = result.get("outcome")
        if outcome in TRX_PASSED:
            status = "passed"
        elif outcome in TRX_SKIPPED:
            status = "skipped"
        elif outcome in TRX_ERROR:
            status = "errors"
        else:
            status = "failed"
        yield classname, name, status


def is_trx(root: ElementTree.Element) -> bool:
    return root.tag == f"{TRX_NAMESPACE}TestRun"


def suite_counts_from_junit(xml_path: Path, suite: str | None = None) -> dict[str, Any]:
    """Pass/skip/fail/error counts of ``suite``'s test cases in a JUnit XML, or
    in a .NET TRX (the Quality Gate's built-in ``trx`` logger).

    One XML may cover several suites (Task 10's boundary step), so a case is
    counted only when its ``classname`` belongs to the suite (``suite_key``).
    ``None`` counts every case. Counts come from the test cases themselves,
    never from summary attributes.
    """
    key = None if suite is None else suite_key(suite)
    root = ElementTree.parse(xml_path).getroot()
    counts = {"passed": 0, "skipped": 0, "failed": 0, "errors": 0, "passedTests": [], "skippedTests": []}
    seen = 0
    for classname, name, status in (_trx_cases(root) if is_trx(root) else _junit_cases(root)):
        if key is not None and not case_belongs(classname, key):
            continue
        seen += 1
        counts[status] += 1
        if status in ("passed", "skipped"):
            counts[f"{status}Tests"].append(f"{classname}::{name}")
    if seen == 0:
        raise ValueError(f"junit_no_matching_testcases:{xml_path}:{suite}")
    return counts


# --------------------------------------------------------------------------- checks
class _Checker:
    def __init__(self, record: dict[str, Any], repo_root: Path | None, verify_git: bool = False) -> None:
        self.record = record
        self.repo_root = repo_root
        self.verify_git = verify_git
        self.findings: list[Finding] = []

    def source_at(self, measured_sha: str, relative: str) -> bytes | None:
        """A committed file as it is at the measured SHA (``git show``), so a
        later checkout cannot change what the measured code said. Without git
        verification, the repository's (or this checkout's) working tree."""
        if self.verify_git and self.repo_root is not None:
            result = subprocess.run(["git", "show", f"{measured_sha}:{relative}"], cwd=self.repo_root, capture_output=True)
            return result.stdout if result.returncode == 0 else None
        path = (self.repo_root or REPO_ROOT) / relative
        return path.read_bytes() if path.is_file() else None

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
        # §2.3 diffs record.measuredSha..closure.mergeSha. A unit measured on any
        # other SHA would have changes that no verified diff covers.
        closure = self.record["closure"]
        allowed = {self.record["measuredSha"]} | ({closure["mergeSha"]} if closure else set())
        if measured_sha not in allowed:
            self.fail(name, "unit_sha_unbound", f"{name} was measured on {measured_sha}, neither the record's measured SHA nor the closure merge SHA")
        self._suites(name, unit, required, measured_sha)
        self._measurements(name, unit, required, measured_sha)
        self._artifacts(name, unit, required, measured_sha)
        if name == "DISCONNECTED":
            self._disconnected(measured_sha)
        if name == "B2":
            self._b2_output(measured_sha)
        if name == "B6":
            self._task10_records(measured_sha)
        if name == "B1":
            self._b1_comparison(measured_sha)
        if name == "B3":
            self._b3_proving_tests(unit)
        if name == "B5":
            self._b5_records(measured_sha)

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
        for suite_id, entry in ((suite_id, suites[suite_id]) for suite_id in unit["suites"] if suite_id in suites):
            run = self._run(name, entry["run"], measured_sha, f"suite {suite_id}")
            self._suite_provenance(name, suite_id, entry, run, required)
            self._junit(name, suite_id, entry, measured_sha)
            if entry["failed"] or entry["errors"]:
                self.fail(name, "suite_failed", f"suite {suite_id}: {entry['failed']} failed, {entry['errors']} errors")
            only_approved_skips = entry["skipped"] > 0 and all(
                is_approved_skip(entry["suite"], entry["variant"], t) for t in entry["skippedTests"]
            )
            # A suite whose every test is an approved OS-conditional skip (the
            # Windows store suite on Linux) is legitimately empty; any other
            # empty suite ran nothing.
            if entry["passed"] == 0 and not only_approved_skips:
                self.fail(name, "suite_empty", f"suite {suite_id} passed no test")
            if entry["skipped"] != len(entry["skippedTests"]) or entry["passed"] != len(entry["passedTests"]):
                self.fail(name, "count_inconsistent", f"suite {suite_id}: counts do not match the named passed/skipped tests")
            for test in entry["skippedTests"]:
                if not is_approved_skip(entry["suite"], entry["variant"], test):
                    self.fail(name, "skip_not_approved", f"suite {suite_id} skipped {test} on {entry['variant']}; §3.1 approves no such skip")
                    continue
                if not self._skip_is_paired(test, entry["variant"], cited, measured_sha):
                    self.fail(name, "skip_not_permitted", f"suite {suite_id} skipped {test} on {entry['variant']} without a paired-variant counterpart")
        for suite in required.suites:
            for variant in required_variants(required, suite):
                if not any(
                    entry["suite"] == suite and (variant is None or entry["variant"] == variant)
                    for entry in cited
                ):
                    where = f" on {variant}" if variant else ""
                    self.fail(name, "variant_result_missing", f"required suite {suite}{where} has no cited result")

    def _suite_provenance(self, name: str, suite_id: str, entry: dict[str, Any], run: dict[str, Any] | None, required: UnitRequirement) -> None:
        """Plan §3: every suite result comes from a workflow run, never a local
        one. A variant-bound or Task-10 result comes from the Task-10 matrix,
        whose committed invocation at the measured SHA fixes what ran; a .NET or
        web result from the Quality Gate."""
        if run is None:
            return
        suite = entry["suite"]
        if suite.startswith("task10:") or (required.variants and suite.startswith(VARIANT_SUITE_PREFIXES)):
            allowed = {TASK10_WORKFLOW}
        elif suite.startswith(("tests/", "src/web/")):
            allowed = {QUALITY_GATE_WORKFLOW}
        else:
            allowed = {TASK10_WORKFLOW, QUALITY_GATE_WORKFLOW}
        if run["kind"] != "workflow" or run.get("workflow") not in allowed:
            self.fail(name, "suite_provenance_invalid", f"suite {suite_id} cites run {entry['run']!r} ({run['kind']} {run.get('workflow')}), not {sorted(allowed)}")
        expected = quality_gate_result_path(suite)
        artifact = self.record["retainedArtifacts"].get(entry["junitArtifact"])
        if expected is not None and artifact is not None and not artifact["path"].endswith(expected):
            self.fail(name, "suite_provenance_invalid", f"suite {suite_id} is backed by {artifact['path']}, not the Quality Gate's {expected}")
        if suite.startswith("task10:"):
            step = suite.split(":", 1)[1]
            artifact = self.record["retainedArtifacts"].get(entry["junitArtifact"])
            if artifact is not None and not artifact["path"].endswith(f"junit/{step}.xml"):
                self.fail(name, "suite_provenance_invalid", f"suite {suite_id} is backed by {artifact['path']}, not Task 10's junit/{step}.xml")

    def _junit(self, name: str, suite_id: str, entry: dict[str, Any], measured_sha: str) -> None:
        """The suite's counts must be the retained XML's, not hand-written ones."""
        artifact = self.record["retainedArtifacts"].get(entry["junitArtifact"])
        if artifact is None:
            self.fail(name, "junit_not_retained", f"suite {suite_id} JUnit {entry['junitArtifact']!r} is not a retained artifact")
            return
        if artifact["run"] != entry["run"]:
            self.fail(name, "junit_run_mismatch", f"suite {suite_id}: JUnit was retained from run {artifact['run']}, the result cites {entry['run']}")
        variant_bound = entry["suite"].startswith(VARIANT_SUITE_PREFIXES) and entry["variant"] in QUALIFIED_CPU_VARIANTS
        if variant_bound:
            if artifact.get("variant") != entry["variant"]:
                self.fail(name, "junit_variant_unbound", f"suite {suite_id}: JUnit {entry['junitArtifact']!r} is not retained as {entry['variant']} output")
            reused = {
                other["variant"]
                for other in self.record["suites"].values()
                if other["variant"] != entry["variant"]
                and other["junitArtifact"] in self.record["retainedArtifacts"]
                and self.record["retainedArtifacts"][other["junitArtifact"]]["sha256"] == artifact["sha256"]
            }
            if reused:
                self.fail(name, "junit_variant_reused", f"suite {suite_id}: the same JUnit bytes also back {sorted(reused)}")
        path = self._verify_file(name, entry["junitArtifact"], artifact)
        if path is None:
            return
        if variant_bound:
            # Task 10 names every JUnit test suite after its matrix variant
            # (``-o junit_suite_name``), so the bytes carry the variant too.
            try:
                names = {suite.get("name") for suite in ElementTree.parse(path).getroot().iter("testsuite")}
            except ElementTree.ParseError as exc:
                self.fail(name, "junit_unreadable", f"suite {suite_id}: {exc}")
                return
            if names != {entry["variant"]}:
                self.fail(name, "junit_variant_mismatch", f"suite {suite_id}: JUnit test suites are named {sorted(n or '' for n in names)}, not {entry['variant']}")
        try:
            counts = suite_counts_from_junit(path, entry["suite"])
        except (ValueError, ElementTree.ParseError) as exc:
            self.fail(name, "junit_unreadable", f"suite {suite_id}: {exc}")
            return
        for key in ("passed", "skipped", "failed", "errors"):
            if counts[key] != entry[key]:
                self.fail(name, "junit_count_mismatch", f"suite {suite_id}: {key} {entry[key]} != {counts[key]} in the retained XML")
        for key in ("passedTests", "skippedTests"):
            if sorted(counts[key]) != sorted(entry[key]):
                self.fail(name, "junit_count_mismatch", f"suite {suite_id}: {key} differ from the retained XML")

    def _skip_is_paired(self, test: str, variant: str, cited: list[dict[str, Any]], measured_sha: str) -> bool:
        """An approved skip still needs *positive* evidence: the same test of the
        same suite passed on the other qualified variant, in a clean result the
        same unit cites, from a successful run on the unit's measured SHA."""
        suites_of_test = {entry["suite"] for entry in cited if test in entry["skippedTests"] and entry["variant"] == variant}
        for pair in self.record["pairedVariantSkips"]:
            if (
                pair["test"] != test
                or pair["skipsOn"] != variant
                or pair["counterpartVariant"] == variant
                or pair["counterpartVariant"] not in QUALIFIED_CPU_VARIANTS
                or pair["counterpartSuite"] not in suites_of_test
                or test_function_name(pair["counterpartTest"]) != test_function_name(test)
            ):
                continue
            for entry in cited:
                run = self.record["runs"].get(entry["run"])
                if (
                    entry["suite"] == pair["counterpartSuite"]
                    and entry["variant"] == pair["counterpartVariant"]
                    and not entry["failed"]
                    and not entry["errors"]
                    and pair["counterpartTest"] in entry["passedTests"]
                    and run is not None
                    and run["headSha"] == measured_sha
                    and run["conclusion"] == "success"
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
            if entry["metric"] in by_metric:
                # One value per metric: a second, failing value must not hide behind a passing one.
                self.fail(name, "measurement_duplicate", f"{entry['metric']} is cited more than once")
            by_metric[entry["metric"]] = entry
            self._run(name, entry["run"], measured_sha, f"measurement {measurement_id}")
            if entry["host"] not in self.record["hosts"]:
                self.fail(name, "host_missing", f"measurement {measurement_id} names unknown host {entry['host']!r}")
            limit = entry.get("limit")
            if limit is not None and not _limit_holds(entry["value"], limit["op"], limit["value"]):
                self.fail(name, "limit_violated", f"{entry['metric']} = {entry['value']} violates {limit['op']} {limit['value']}")
            if entry["unit"] in TIMING_UNITS and entry.get("stats") is not None:
                self._timing(name, measurement_id, entry)
            # Every value comes from a retained output the unit cites; B2 and the
            # B3 wall time are further compared with that output's content.
            source = entry.get("artifact")
            if source is None or source not in self.record["retainedArtifacts"] or source not in unit["artifacts"]:
                self.fail(name, "measurement_unbound", f"measurement {measurement_id} does not cite a retained artifact of {name} ({source!r})")
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
            self._b3_headroom(by_metric, measured_sha)

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

    def _b3_headroom(self, by_metric: dict[str, dict[str, Any]], measured_sha: str) -> None:
        timeout = by_metric.get("b3.worker-request-timeout-ms")
        if timeout is None:
            return
        settings = self.source_at(measured_sha, WORKER_SETTINGS_RELATIVE)
        if settings is None:
            self.fail("B3", "worker_timeout_unbound", f"{WORKER_SETTINGS_RELATIVE} is not readable at the measured {measured_sha}")
            return
        default_ms, maximum_ms = worker_request_timeout_bounds_ms(settings.decode("utf-8"))
        if not 0 < timeout["value"] <= maximum_ms:
            self.fail("B3", "worker_timeout_out_of_range", f"worker timeout {timeout['value']} ms is outside (0, {maximum_ms}] ms")
        # No supported install path configures the worker timeout (installs set
        # none of MAVI_REQUEST_TIMEOUT_SECONDS), so the qualified value is the
        # WorkerSettings default. A non-default value needs a checker change
        # that parses a real install configuration, not a cited file.
        if timeout["value"] != default_ms:
            self.fail("B3", "worker_timeout_unbound", f"worker timeout {timeout['value']} ms is not the {default_ms} ms WorkerSettings default the qualified install uses")
        for variant in QUALIFIED_CPU_VARIANTS:
            wall = by_metric.get(f"{SEALING_WALL_METRIC}.{variant}")
            if wall is None or wall.get("stats") is None:
                continue
            # §7.4: headroom below 2× against the worker request timeout is blocking.
            if wall["stats"]["max"] * 2 > timeout["value"]:
                self.fail("B3", "completion_headroom_insufficient", f"{variant}: max completion {wall['stats']['max']} ms × 2 > worker timeout {timeout['value']} ms")
            self._sealing_output(wall, timeout, measured_sha, variant)

    def _sealing_output(self, wall: dict[str, Any], timeout: dict[str, Any], measured_sha: str, variant: str) -> None:
        """The wall time must be the sealing harness's authoritative output, on
        that variant's OS and on the host's declared evidence filesystem."""
        expected_id = f"{SEALING_OUTPUT_ARTIFACT}.{variant}"
        artifact_id = wall.get("artifact")
        if artifact_id != expected_id:
            self.fail("B3", "sealing_output_unbound", f"{SEALING_WALL_METRIC}.{variant} must cite the {expected_id} artifact")
            return
        host = self.record["hosts"].get(wall["host"], {})
        artifact = self.record["retainedArtifacts"].get(artifact_id)
        path = None if artifact is None else self._verify_file("B3", artifact_id, artifact)
        if path is None:
            return
        try:
            output = json.loads(path.read_text(encoding="utf-8"))
            shape = output["shape"]
            # The .NET harness measures what it can portably read: CPU model and
            # logical cores. The rest of the host is bound through B2's harness.
            self._bind_host("B3", wall, output["host"], artifact_id, SEALING_HOST_FIELDS)
            problems = [
                label
                for label, holds in (
                    ("schema is not s1-b3-sealing-scale-v1", output["schema"] == "s1-b3-sealing-scale-v1"),
                    ("status is not complete", output["status"] == "complete"),
                    ("the run was not authoritative", output["authoritative"] is True),
                    (f"tracks {shape['tracks']} != {MAXIMUM_COMPLETION_TRACKS}", shape["tracks"] == MAXIMUM_COMPLETION_TRACKS),
                    (f"sealed objects {shape['sealedObjects']} != {WORST_CASE_SEALED_OBJECTS}", shape["sealedObjects"] == WORST_CASE_SEALED_OBJECTS),
                    ("its worker timeout differs from the recorded one", output["workerRequestTimeoutMs"] == timeout["value"]),
                    (f"it measured {output['environment']['gitSha']}, not {measured_sha}", output["environment"]["gitSha"] == measured_sha),
                    ("its tree was not clean", output["environment"]["gitWorkingTreeClean"] == "true"),
                    (f"it ran on {output['variant']}, not {variant}", output["variant"] == variant),
                    (
                        f"its evidence filesystem {output['evidenceFilesystem']!r} is not the host's {host.get('acceptedEvidenceFilesystem')!r}",
                        str(output["evidenceFilesystem"]).split(" ", 1)[0].lower() == str(host.get("acceptedEvidenceFilesystem")).lower(),
                    ),
                    *(
                        (f"its {stat} differs from the recorded one", output["completion"][stat] == wall["stats"][stat])
                        for stat in ("min", "p50", "p95", "max")
                    ),
                    ("its sample count differs from the recorded one", output["completion"]["n"] == wall.get("samples")),
                    ("its repeat count differs from the recorded one", output["repeats"] == wall.get("repeats")),
                    ("its p50 spread differs from the recorded one", output["p50RunSpreadMs"] == wall["stats"].get("p50RunSpread")),
                    ("it excluded no warm-up", output["warmupExcluded"] >= 1 and wall.get("warmupExcluded") is True),
                )
                if not holds
            ]
        except (KeyError, TypeError, ValueError) as exc:
            problems = [f"unreadable ({exc})"]
        for problem in problems:
            self.fail("B3", "sealing_output_mismatch", f"sealing output: {problem}")

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

    def _verify_file(self, name: str, artifact_id: str, entry: dict[str, Any]) -> Path | None:
        """The retained file, hash-verified; ``None`` when it cannot be trusted.

        Without a repository root nothing can be verified. Unless the caller
        asked for a structural-only check, that is itself a finding, recorded
        once in ``check_record``.
        """
        if self.repo_root is None:
            return None
        path = (self.repo_root / entry["path"]).resolve()
        if not path.is_relative_to(self.repo_root.resolve()) or not path.is_file():
            self.fail(name, "artifact_file_missing", f"{artifact_id}: {entry['path']} is not a retained file")
            return None
        if sha256_file(path) != entry["sha256"]:
            self.fail(name, "artifact_hash_mismatch", f"{artifact_id}: {entry['path']} does not match its sha256")
            return None
        return path

    def _retained_json(self, unit: str, artifact_id: str, code: str) -> dict[str, Any] | None:
        artifact = self.record["retainedArtifacts"].get(artifact_id)
        path = None if artifact is None else self._verify_file(unit, artifact_id, artifact)
        if path is None:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.fail(unit, code, f"{artifact_id} is not readable JSON ({exc})")
            return None

    def _b1_comparison(self, measured_sha: str) -> None:
        """Each B1 count equals the retained s1_b1 comparison of the retained runs."""
        comparison = self._retained_json("B1", "b1.cross-variant-comparison", "b1_comparison_invalid")
        if comparison is None:
            return
        problems: list[str] = []
        try:
            identity = comparison["identity"]
            if comparison["schema"] != "s1-b1-comparison-v1":
                problems.append("its schema is not s1-b1-comparison-v1")
            if identity["sourceSha"] != measured_sha or identity["cleanTree"] is not True:
                problems.append(f"it was derived on {identity['sourceSha']} (clean: {identity['cleanTree']}), not a clean {measured_sha}")
            problems.extend(f"identity: {problem}" for problem in comparison["identityProblems"])
            measurement = self.record["retainedArtifacts"].get("b1.real-clip-measurement")
            if measurement is None or comparison["inputs"]["linux"]["sha256"] != measurement["sha256"]:
                problems.append("its Linux run is not the retained b1.real-clip-measurement")
            baseline = self.source_at(measured_sha, B1_BASELINE_RELATIVE) if self.repo_root else None
            if baseline is None or comparison["inputs"]["baseline"]["sha256"] != hashlib.sha256(baseline).hexdigest():
                problems.append(f"its baseline is not {B1_BASELINE_RELATIVE} at the measured SHA")
            for trace in comparison["traces"]:
                if not (trace.get("path") and trace.get("cause") and trace.get("reviewedBy")):
                    problems.append(f"trace {trace} lacks a path, cause or reviewer")
            counts = comparison["counts"]
            for measurement_id in self.record["units"]["B1"]["measurements"]:
                entry = self.record["measurements"].get(measurement_id)
                if entry is not None and entry["metric"] in B1_COUNTS and entry["value"] != counts[B1_COUNTS[entry["metric"]]]:
                    problems.append(f"{entry['metric']} {entry['value']} is not the derived {counts[B1_COUNTS[entry['metric']]]}")
        except (KeyError, TypeError) as exc:
            problems.append(f"incomplete ({exc})")
        for problem in problems:
            self.fail("B1", "b1_comparison_invalid", f"b1.cross-variant-comparison: {problem}")

    def _b3_proving_tests(self, unit: dict[str, Any]) -> None:
        cited = [self.record["suites"][sid] for sid in unit["suites"] if sid in self.record["suites"]]
        for metric, (suite, test) in B3_PROVING_TESTS.items():
            variants = required_variants(UNIT_REQUIREMENTS["B3"], suite)
            for variant in variants:
                if not any(
                    entry["suite"] == suite
                    and (variant is None or entry["variant"] == variant)
                    and any(test_function_name(t) == test for t in entry["passedTests"])
                    for entry in cited
                ):
                    where = f" on {variant}" if variant else ""
                    self.fail("B3", "proving_test_missing", f"{metric} needs {suite}::{test} to have passed{where}")

    def _b5_records(self, measured_sha: str) -> None:
        """The real-video clip count is the retained record's verified clips."""
        video = self._retained_json("B5", "b5.real-video-record", "b5_record_invalid")
        if video is not None:
            problems: list[str] = []
            try:
                if video["schema"] != "s1-b5-real-video-record-v1":
                    problems.append("its schema is not s1-b5-real-video-record-v1")
                if video["sourceCommit"] != measured_sha:
                    problems.append(f"it ran {video['sourceCommit']}, not the measured {measured_sha}")
                verified = [
                    clip for clip in video["clips"]
                    if clip.get("label") == "real-video"
                    and re.fullmatch(r"[0-9a-f]{64}", str(clip.get("sha256", "")))
                    and all(clip.get(key) is True for key in B5_CLIP_CHECKS)
                ]
                if len({clip["sha256"] for clip in verified}) != len(verified):
                    problems.append("a clip is counted twice")
                count = len({clip["sha256"] for clip in verified})
                for measurement_id in self.record["units"]["B5"]["measurements"]:
                    entry = self.record["measurements"].get(measurement_id)
                    if entry is not None and entry["metric"] == B5_CLIP_METRIC and entry["value"] != count:
                        problems.append(f"{B5_CLIP_METRIC} {entry['value']} is not the record's {count} verified real-video clips")
            except (KeyError, TypeError) as exc:
                problems.append(f"incomplete ({exc})")
            for problem in problems:
                self.fail("B5", "b5_record_invalid", f"b5.real-video-record: {problem}")
        qa = self._retained_json("B5", "b5.visual-qa-record", "b5_record_invalid")
        if qa is not None:
            problems = []
            try:
                if qa["schema"] != "s1-b5-visual-qa-v1":
                    problems.append("its schema is not s1-b5-visual-qa-v1")
                if qa["sourceCommit"] != measured_sha:
                    problems.append(f"it reviewed {qa['sourceCommit']}, not the measured {measured_sha}")
                items = qa["items"]
                if not items or any(item.get("passed") is not True or item.get("label") not in ("real-video", "fixture") for item in items):
                    problems.append("an item did not pass or is not labelled real-video/fixture")
                if not any(item.get("label") == "real-video" for item in items):
                    problems.append("no item is real-video acceptance")
            except (KeyError, TypeError) as exc:
                problems.append(f"incomplete ({exc})")
            for problem in problems:
                self.fail("B5", "b5_record_invalid", f"b5.visual-qa-record: {problem}")

    def _task10_records(self, measured_sha: str) -> None:
        """Each variant's Task-10 records come from a successful Task-10 run on
        the measured SHA, from that variant's job, under their own names."""
        for variant in QUALIFIED_CPU_VARIANTS:
            for record_name in TASK10_RECORDS:
                artifact_id = f"b6.{variant}.{record_name}"
                artifact = self.record["retainedArtifacts"].get(artifact_id)
                if artifact is None:
                    continue  # reported by _artifacts
                run = self.record["runs"].get(artifact["run"])
                problems = []
                if run is None or run["kind"] != "workflow" or run.get("workflow") != TASK10_WORKFLOW:
                    problems.append("it is not from a Task-10 workflow run")
                if artifact.get("variant") != variant:
                    problems.append(f"it is not retained as {variant} output")
                expected = f"{variant}/{record_name}"
                if artifact["path"] != expected and not artifact["path"].endswith("/" + expected):
                    problems.append(f"its path {artifact['path']} is not the variant's {expected}")
                twin = self.record["retainedArtifacts"].get(f"b6.{other_variant(variant)}.{record_name}")
                if record_name in TASK10_JOB_RECORDS and twin is not None and twin.get("sha256") == artifact.get("sha256"):
                    problems.append("its bytes are the other variant's; each job writes its own")
                for problem in problems:
                    self.fail("B6", "task10_record_invalid", f"{artifact_id}: {problem}")
        # Task 10's own final step requires the composition record to pass;
        # check the retained bytes say so too.
        for variant in QUALIFIED_CPU_VARIANTS:
            composition = self._retained_json("B6", f"b6.{variant}.production-composition-qualification.json", "task10_record_invalid")
            if composition is not None:
                for key, expected in (("status", "passed"), ("headSha", measured_sha)):
                    if composition.get(key) != expected:
                        self.fail("B6", "task10_record_invalid", f"{variant} production-composition-qualification.json {key} is {composition.get(key)!r}, not {expected!r}")
            # The ByteTrack record names the job's variant and executed source head.
            bytetrack = self._retained_json("B6", f"b6.{variant}.bytetrack-qualification.json", "task10_record_invalid")
            if bytetrack is not None:
                for key, expected in (("status", "passed"), ("runtimeVariant", variant), ("headSha", measured_sha)):
                    if bytetrack.get(key) != expected:
                        self.fail("B6", "task10_record_invalid", f"{variant} bytetrack-qualification.json {key} is {bytetrack.get(key)!r}, not {expected!r}")

    def _b2_output(self, measured_sha: str) -> None:
        """Every B2 value is its variant's retained derived harness output, and
        each variant's §6.3 staging lifecycle passed on the measured code."""
        for variant in QUALIFIED_CPU_VARIANTS:
            self._b2_variant_output(measured_sha, variant)
            self._staging_lifecycle(measured_sha, variant)

    def _staging_lifecycle(self, measured_sha: str, variant: str) -> None:
        artifact_id = f"{B2_LIFECYCLE_ARTIFACT}.{variant}"
        output = self._retained_json("B2", artifact_id, "staging_lifecycle_invalid")
        if output is None:
            return
        try:
            identity = output["identity"]
            problems = [
                label
                for label, holds in (
                    ("its schema is not s1-b2-staging-lifecycle-v1", output["schema"] == "s1-b2-staging-lifecycle-v1"),
                    (f"it measured {identity['sourceSha']}, not a clean {measured_sha}", identity["sourceSha"] == measured_sha and identity["cleanTree"] is True),
                    (f"it ran on {output['runtime']['runtimeVariant']!r}, not {variant}", output["runtime"]["runtimeVariant"] == variant),
                    ("it did not use the native ByteTrack adapter", output["workload"]["tracker"] == "bytetrack"),
                    *((f"lifecycle check {check} did not hold", output["checks"].get(check) is True) for check in STAGING_LIFECYCLE_CHECKS),
                )
                if not holds
            ]
        except (KeyError, TypeError) as exc:
            problems = [f"incomplete ({exc})"]
        for problem in problems:
            self.fail("B2", "staging_lifecycle_invalid", f"{artifact_id}: {problem}")

    def _b2_variant_output(self, measured_sha: str, variant: str) -> None:
        artifact_id = f"{B2_OUTPUT_ARTIFACT}.{variant}"
        derived = self._retained_json("B2", artifact_id, "b2_output_mismatch")
        if derived is None:
            return
        try:
            if derived["schema"] != "s1-b2-memory-derived-v1":
                self.fail("B2", "b2_output_mismatch", f"{artifact_id} schema {derived['schema']!r} is not s1-b2-memory-derived-v1")
            identity = derived["identity"]
            if identity["sourceSha"] != measured_sha or identity["cleanTree"] is not True:
                self.fail("B2", "b2_output_mismatch", f"{artifact_id} measured {identity['sourceSha']} (clean: {identity['cleanTree']}), not a clean {measured_sha}")
            values = derived["measurements"]
            runtime_variant = derived["runtime"]["runtimeVariant"]
            derived_host = derived["host"]
            live_fit = derived["liveLevelFit"]
            reconciliation = derived["boundOneReconciliation"]
        except (KeyError, TypeError) as exc:
            self.fail("B2", "b2_output_mismatch", f"{artifact_id} is incomplete ({exc})")
            return
        if runtime_variant != variant:
            self.fail("B2", "b2_output_mismatch", f"{artifact_id} ran on {runtime_variant!r}, not {variant}")
        self._live_level_fit(artifact_id, values, live_fit, reconciliation)
        suffix = "." + variant
        for measurement_id in self.record["units"]["B2"]["measurements"]:
            entry = self.record["measurements"].get(measurement_id)
            if entry is None or not entry["metric"].endswith(suffix):
                continue
            base = entry["metric"][: -len(suffix)]
            source = values.get(base)
            if isinstance(source, dict) and source.get("undefined"):
                # §6.2 bound 2 cannot be judged from this measurement: fail closed.
                self.fail("B2", "variation_undefined", f"{entry['metric']}: {source['undefined']}")
                continue
            if source is None or source.get("value") != entry["value"] or source.get("unit") != entry["unit"]:
                self.fail("B2", "b2_output_mismatch", f"{entry['metric']} {entry['value']} {entry['unit']} is not {artifact_id}'s {source}")
            self._bind_host("B2", entry, derived_host, artifact_id)

    def _live_level_fit(self, artifact_id: str, values: dict[str, Any], fit: dict[str, Any], reconciliation: dict[str, Any]) -> None:
        """The per-live slope is recomputed from its retained plateaus, and its
        reconciliation with the bound-1 accounting model must be consistent."""
        try:
            points = [(float(level), float(mean)) for level, mean in fit["points"]]
            levels = {level for level, _ in points}
            xs = [level for level, _ in points]
            ys = [mean for _, mean in points]
            x_mean, y_mean = sum(xs) / len(xs), sum(ys) / len(ys)
            sxx = sum((x - x_mean) ** 2 for x in xs)
            slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / sxx
            recorded = values["b2.process-memory-per-live-track-slope"]["value"]
            problems = [
                label
                for label, holds in (
                    (f"it has {len(levels)} live levels, fewer than {LIVE_LEVEL_MINIMUM}", len(levels) >= LIVE_LEVEL_MINIMUM),
                    (f"its per-live slope {recorded} is not the fit of its plateaus ({slope})", abs(recorded - slope) <= 1e-6 * max(1.0, abs(slope))),
                    ("its fit quality is not recorded", isinstance(fit.get("r2"), (int, float))),
                    ("its reconciliation slope differs from the metric", reconciliation["perLiveProcessSlopeBytes"] == recorded),
                    (
                        "its reconciliation does not account the recorded held evidence",
                        reconciliation["unaccountedPerLiveBytes"] == recorded - reconciliation["accountedEncodedEvidenceBytesMax"],
                    ),
                    ("its reconciliation's accounted evidence exceeds the holder bound", reconciliation["accountedEncodedEvidenceBytesMax"] <= reconciliation["encodedEvidenceBoundBytes"]),
                )
                if not holds
            ]
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            problems = [f"live-level fit is incomplete ({exc})"]
        for problem in problems:
            self.fail("B2", "b2_output_mismatch", f"{artifact_id}: {problem}")

    def _bind_host(self, unit: str, entry: dict[str, Any], measured: dict[str, Any], source: str, fields: tuple[str, ...] = MEASURED_HOST_FIELDS) -> None:
        """§3 host identity is measured by the harness, not typed into the record."""
        host = self.record["hosts"].get(entry["host"], {})
        for key in fields:
            if measured.get(key) is None:
                self.fail(unit, "host_identity_unmeasured", f"{source} did not measure host {key}")
            elif measured.get(key) != host.get(key):
                self.fail(unit, "host_identity_mismatch", f"{entry['metric']}: {source} measured {key} {measured.get(key)!r}, host {entry['host']} says {host.get(key)!r}")

    def _disconnected_run(self, measured_sha: str) -> None:
        """The run record must show every §11 outcome succeeded on the measured code."""
        run = self._retained_json("DISCONNECTED", "disconnected.run-record", "disconnected_run_incomplete")
        if run is None:
            return
        block = self.record["disconnected"]
        try:
            problems = [
                label
                for label, holds in (
                    ("schema is not s1-disconnected-run-v1", run["schema"] == "s1-disconnected-run-v1"),
                    (f"sourceCommit {run['sourceCommit']} is not the measured {measured_sha}", run["sourceCommit"] == measured_sha),
                    ("its variant differs from the record's", run["variant"] == block["variant"]),
                    ("it is not a Development install", run["installProfile"] == "development"),
                    ("it observed outbound connection attempts", run["outboundConnectionAttempts"] == []),
                )
                if not holds
            ]
            used_evidence: set[str] = set()
            for outcome in DISCONNECTED_OUTCOMES:
                result = run["outcomes"].get(outcome)
                if not isinstance(result, dict) or result.get("passed") is not True:
                    problems.append(f"outcome {outcome} did not pass")
                    continue
                evidence = result.get("evidence")
                artifact = self.record["retainedArtifacts"].get(evidence) if isinstance(evidence, str) else None
                if evidence in NON_OUTCOME_ARTIFACTS or evidence in used_evidence:
                    problems.append(f"outcome {outcome} reuses {evidence!r}; every outcome needs its own evidence")
                    continue
                used_evidence.add(evidence)
                if artifact is None or self._verify_file("DISCONNECTED", evidence, artifact) is None:
                    problems.append(f"outcome {outcome} does not cite a retained, verified evidence artifact ({evidence!r})")
                    continue
                self._run("DISCONNECTED", artifact["run"], measured_sha, f"outcome {outcome} evidence {evidence}")
                # §11 is the operator's own run on the disconnected host: its
                # evidence comes from the run that retained the run record, a
                # local run on a declared host, and is no other unit's evidence.
                record_run = self.record["retainedArtifacts"]["disconnected.run-record"]["run"]
                source = self.record["runs"].get(artifact["run"])
                if artifact["run"] != record_run or source is None or source["kind"] != "local":
                    problems.append(f"outcome {outcome} evidence {evidence} is from run {artifact['run']!r}, not the disconnected local run {record_run!r}")
                cited_by = sorted(
                    name for name, unit in self.record["units"].items()
                    if name != "DISCONNECTED"
                    and (evidence in unit.get("artifacts", ())
                         or any(self.record["measurements"].get(mid, {}).get("artifact") == evidence for mid in unit.get("measurements", ())))
                )
                if cited_by:
                    problems.append(f"outcome {outcome} evidence {evidence} is also evidence for {cited_by}")
            record_run = self.record["runs"].get(self.record["retainedArtifacts"]["disconnected.run-record"]["run"]) or {}
            host = self.record["hosts"].get(record_run.get("host"), {})
            if ("windows" in str(host.get("os", "")).lower()) != block["variant"].startswith("windows"):
                problems.append(f"it ran on host {record_run.get('host')!r} ({host.get('os')}), not a {block['variant']} host")
        except (KeyError, TypeError, AttributeError) as exc:
            problems = [f"incomplete ({exc})"]
        for problem in problems:
            self.fail("DISCONNECTED", "disconnected_run_incomplete", f"disconnected.run-record: {problem}")

    def _disconnected(self, measured_sha: str) -> None:
        record = self.record.get("disconnected")
        if record is None:
            self.fail("DISCONNECTED", "disconnected_record_missing", "no disconnected block")
            return
        if record["runtimeBundleSourceCommit"] != measured_sha:
            self.fail("DISCONNECTED", "runtime_bundle_not_measured_code", f"bundle sourceCommit {record['runtimeBundleSourceCommit']} != measured {measured_sha}")
        if record["variant"] not in QUALIFIED_CPU_VARIANTS:
            self.fail("DISCONNECTED", "disconnected_variant_unqualified", f"variant {record['variant']!r} is not a qualified CPU variant {QUALIFIED_CPU_VARIANTS}")
        for phase in ("isolationBefore", "isolationAfter"):
            probe = record[phase]
            if not probe["passed"] or not probe["proxyEnvironmentAbsent"] or any(item["reachable"] for item in probe["probes"]):
                self.fail("DISCONNECTED", "isolation_not_evidenced", f"{phase} does not show an isolated host")
            targets = [(item.get("host"), item.get("port")) for item in probe["probes"]]
            if sorted(targets, key=str) != sorted(ISOLATION_PROBE_TARGETS, key=str):
                self.fail("DISCONNECTED", "isolation_not_evidenced", f"{phase} probed {targets}, not exactly {list(ISOLATION_PROBE_TARGETS)}")
        self._disconnected_run(measured_sha)
        self._bundle_manifest(measured_sha)
        # The probes are retained probe output, not record fields.
        for phase, artifact_id in (("isolationBefore", "disconnected.isolation-before"), ("isolationAfter", "disconnected.isolation-after")):
            probe = self._retained_json("DISCONNECTED", artifact_id, "isolation_not_evidenced")
            # The probe's own fields; the retained output may carry more (timestamps).
            if probe is not None and any(probe.get(key) != record[phase].get(key) for key in ISOLATION_PROBE_FIELDS):
                self.fail("DISCONNECTED", "isolation_not_evidenced", f"{phase} differs from the retained {artifact_id} probe output")

    def _bundle_manifest(self, measured_sha: str) -> None:
        """The retained Runtime Bundle manifest, not the record's copy, must show
        the measured code: its sourceCommit, variant and mavi-vision wheel."""
        manifest = self._retained_json("DISCONNECTED", "disconnected.runtime-bundle-manifest", "bundle_manifest_mismatch")
        if manifest is None:
            return
        block = self.record["disconnected"]
        try:
            wheels = [
                item for item in manifest["artifacts"]
                if re.sub(r"[-_.]+", "-", str(item.get("package") or "")).lower() == "mavi-vision"
            ]
            problems = [
                label
                for label, holds in (
                    (f"sourceCommit {manifest['sourceCommit']} is not the measured {measured_sha}", manifest["sourceCommit"] == measured_sha),
                    (f"platformVariant {manifest['platformVariant']} is not {block['variant']}", manifest["platformVariant"] == block["variant"]),
                    (f"it lists {len(wheels)} mavi-vision artifacts, not one", len(wheels) == 1),
                    ("its mavi-vision wheel hash differs from the record's", bool(wheels) and all(item["sha256"] == block["maviVisionWheelSha256"] for item in wheels)),
                )
                if not holds
            ]
        except (KeyError, TypeError) as exc:
            problems = [f"incomplete ({exc})"]
        for problem in problems:
            self.fail("DISCONNECTED", "bundle_manifest_mismatch", f"disconnected.runtime-bundle-manifest: {problem}")

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
            if closure is not None:
                for workflow in POST_MERGE_WORKFLOWS:
                    if not any(
                        run["kind"] == "workflow"
                        and run.get("workflow") == workflow
                        and run["headSha"] == closure["mergeSha"]
                        and run["conclusion"] == "success"
                        for run in self.record["runs"].values()
                    ):
                        self.fail("record", "post_merge_verification_missing", f"s1Closed needs a successful {workflow} run on the merge SHA {closure['mergeSha']}")
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

    def verify_measured_shas(self) -> None:
        """Plan §2: every PASS was measured on a real commit reachable from
        ``main`` (a merge commit, not an unmerged branch head)."""
        if self.repo_root is None:
            return
        git = lambda *args: subprocess.run(["git", *args], cwd=self.repo_root, capture_output=True, text=True)  # noqa: E731
        main = next((ref for ref in ("refs/heads/main", "refs/remotes/origin/main") if git("rev-parse", "--verify", "-q", ref).returncode == 0), None)
        for name in UNITS:
            if self.record["units"][name]["verdict"] != "PASS":
                continue
            sha = self._unit_sha(name)
            if git("cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
                self.fail(name, "measured_sha_unknown", f"{name} was measured on {sha}, which is not a commit in this repository")
            elif main is None:
                self.fail(name, "measured_sha_not_on_main", "no main or origin/main ref to verify the measured SHA against")
            elif git("merge-base", "--is-ancestor", sha, main).returncode != 0:
                self.fail(name, "measured_sha_not_on_main", f"{name} was measured on {sha}, which is not reachable from {main}")

    def verify_git_diff(self) -> None:
        """The closure must be a real merge of the measured code, and its
        changedPaths the real diff, not a hand-written list."""
        closure = self.record["closure"]
        if closure is None or self.repo_root is None:
            return
        measured, merge = self.record["measuredSha"], closure["mergeSha"]
        if merge == measured:
            self.fail("record", "closure_not_a_merge", "closure mergeSha equals measuredSha; §2.3 closes on the later merge commit")
        git = lambda *args: subprocess.run(["git", *args], cwd=self.repo_root, capture_output=True, text=True)  # noqa: E731
        if git("merge-base", "--is-ancestor", measured, merge).returncode != 0:
            self.fail("record", "closure_not_a_merge", f"measured {measured} is not an ancestor of merge {merge}")
        main = next((ref for ref in ("refs/heads/main", "refs/remotes/origin/main") if git("rev-parse", "--verify", "-q", ref).returncode == 0), None)
        if main is None:
            self.fail("record", "closure_diff_unverifiable", "no main or origin/main ref to verify the merge against")
        elif git("merge-base", "--is-ancestor", merge, main).returncode != 0:
            self.fail("record", "closure_not_on_main", f"merge {merge} is not on {main}")
        # --no-renames: a moved file must show its old path too, or moving a
        # behavior-bearing file out of the surface would hide the change.
        diff = git("diff", "--no-renames", "--name-only", "-z", measured, merge)
        if diff.returncode != 0:
            self.fail("record", "closure_diff_unverifiable", f"git diff failed: {diff.stderr.strip()}")
            return
        actual = [path for path in diff.stdout.split("\0") if path]
        if sorted(actual) != sorted(closure["changedPaths"]):
            self.fail("record", "closure_diff_mismatch", "recorded changedPaths differ from git diff --no-renames --name-only measured..merge")


def check_record(
    record: dict[str, Any],
    *,
    repo_root: Path | None = None,
    verify_git: bool | None = None,
    structural_only: bool = False,
) -> list[Finding]:
    """Findings that refuse the record's PASS verdicts and closure.

    A PASS or a closure is accepted only against a repository: retained files
    and JUnit XML are hash-verified and re-counted, and the §2.3 diff is
    recomputed with git. ``structural_only`` skips that and is for tests of the
    rules themselves; a record checked that way is never evidence.
    """
    verify_git = verify_git if verify_git is not None else repo_root is not None
    checker = _Checker(record, repo_root, verify_git=verify_git)
    if not checker.schema():
        return sorted(checker.findings)
    if repo_root is None and not structural_only:
        claims = [name for name in UNITS if record["units"][name]["verdict"] == "PASS"]
        if claims or record["closure"] is not None or record.get("s1Closed") is True:
            checker.fail("record", "repository_not_verified", "a PASS or closure needs --repo-root to verify retained files, JUnit counts and the git diff")
    for name in UNITS:
        checker.unit(name)
    checker.closure()
    if verify_git:
        checker.verify_measured_shas()
        checker.verify_git_diff()
    return sorted(set(checker.findings))


def open_requirements(record: dict[str, Any], repo_root: Path | None = None) -> dict[str, list[str]]:
    """For an OPEN unit: what a PASS would still need. Informational only."""
    result: dict[str, list[str]] = {}
    for name in UNITS:
        if record["units"][name]["verdict"] != "OPEN":
            continue
        trial = json.loads(json.dumps(record))
        trial["units"][name]["verdict"] = "PASS"
        trial["s1Closed"] = False
        missing = [f.code + ": " + f.detail for f in check_record(trial, repo_root=repo_root, structural_only=repo_root is None) if f.unit == name]
        result[name] = missing
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate an evidence record; exit 1 on any finding")
    check.add_argument("record", type=Path)
    check.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="the checkout that holds the retained files (default: this repository)")
    junit = sub.add_parser("junit", help="derive a suite entry's counts from JUnit XML")
    junit.add_argument("xml", type=Path)
    junit.add_argument("--suite", default=None, help="the suite path whose test cases to count (default: every case)")
    args = parser.parse_args(argv)

    if args.command == "junit":
        print(json.dumps(suite_counts_from_junit(args.xml, args.suite), indent=2, sort_keys=True))
        return 0

    record = json.loads(args.record.read_text(encoding="utf-8"))
    findings = check_record(record, repo_root=args.repo_root, verify_git=True)
    for finding in findings:
        print(finding)
    if not findings:
        verdicts = {name: record["units"][name]["verdict"] for name in UNITS}
        print("s1-evidence-record-valid", json.dumps(verdicts, sort_keys=True))
        for name, missing in open_requirements(record, args.repo_root).items():
            print(f"{name} OPEN; a PASS still needs {len(missing)} item(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
