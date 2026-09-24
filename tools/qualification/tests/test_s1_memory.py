"""The S1.4 B2 memory harness measures what it claims, and discriminates.

These run small workloads only. The authoritative presets are opt-in CLI runs
(``s1_memory.py run --preset ...``). The native-ByteTrack cases need the
qualified ``trackers`` backend and run in the Task-10 CPU matrix, where
``MAVI_RUN_QUALIFIED_BYTETRACK_TESTS=1`` makes a missing backend a failure
rather than a skip.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

import process_memory
import s1_memory
from mavi_vision.pipeline.process_video import VideoProcessor, _TrackAccumulator
from mavi_vision.video.trajectory_spool import TrajectorySpool

KIB = 1024
NATIVE = os.environ.get("MAVI_RUN_QUALIFIED_BYTETRACK_TESTS") == "1"

# Small, fast, structural. Crops of about 32 KiB (144 px high-entropy boxes),
# so a retained crop per Track is visible against the 16 KiB ceiling.
SMALL = s1_memory.Workload(
    "test-small", "fixture", "trace", 4, 60, 24, 12, 144, 900, 480, sample_every=6, warmup_fraction=0.1
)


def run(workload: s1_memory.Workload, tmp_path: Path, **kwargs) -> dict:
    return s1_memory.run_workload(workload, tmp_path, **kwargs)["results"]


# --------------------------------------------------------------------------- probes
ROLLUP = """00400000-7ffd1a3e9000 ---p 00000000 00:00 0                          [rollup]
Rss:              123456 kB
Pss:              100000 kB
Pss_Anon:          90000 kB
Shared_Clean:      20000 kB
Private_Clean:      3000 kB
Private_Dirty:     80000 kB
Swap:                  0 kB
"""


def test_smaps_rollup_is_parsed_to_bytes() -> None:
    values = process_memory.parse_smaps_rollup(ROLLUP)
    assert values["Rss"] == 123456 * KIB
    assert values["Pss"] == 100000 * KIB
    assert values["Private_Clean"] + values["Private_Dirty"] == 83000 * KIB


@pytest.mark.parametrize("dropped", ["Rss:", "Pss:", "Private_Clean:", "Private_Dirty:"])
def test_an_incomplete_rollup_fails_rather_than_reading_zero(dropped: str) -> None:
    text = "\n".join(line for line in ROLLUP.splitlines() if not line.startswith(dropped))
    with pytest.raises(RuntimeError, match="smaps_rollup_incomplete"):
        process_memory.parse_smaps_rollup(text)


def test_the_linux_sample_is_uss_from_private_clean_plus_private_dirty(tmp_path: Path) -> None:
    (tmp_path / "smaps_rollup").write_text(ROLLUP, encoding="ascii")
    (tmp_path / "status").write_text("VmHWM:\t  200000 kB\n", encoding="ascii")
    reading = process_memory._linux(tmp_path)
    assert reading.primary_metric == "uss"
    assert reading.primary_bytes == reading.uss_bytes == (3000 + 80000) * KIB
    assert reading.pss_bytes == 100000 * KIB
    assert reading.rss_bytes == 123456 * KIB
    assert reading.peak_bytes == 200000 * KIB


def test_status_peak_is_vmhwm_and_required() -> None:
    assert process_memory.parse_status_peak("VmPeak:\t 999 kB\nVmHWM:\t  4321 kB\n") == 4321 * KIB
    with pytest.raises(RuntimeError, match="status_vmhwm_missing"):
        process_memory.parse_status_peak("VmPeak:\t 999 kB\n")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc probe; the Windows probe is exercised by the next test on win32")
def test_linux_probe_reads_this_process() -> None:
    reading = process_memory.sample()
    assert reading.platform == "linux"
    assert reading.primary_metric == "uss"
    assert reading.primary_bytes == reading.uss_bytes > 0
    assert 0 < reading.pss_bytes <= reading.rss_bytes <= reading.peak_bytes
    grown = bytearray(64 * 1024 * 1024)
    grown[:: 4096] = b"x" * len(grown[:: 4096])  # touch every page
    assert process_memory.sample().primary_bytes - reading.primary_bytes > 48 * 1024 * 1024
    del grown


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ctypes probe; the Linux probe is exercised by the previous test on linux")
def test_windows_probe_reads_commit_charge() -> None:  # pragma: no cover - Windows variant
    reading = process_memory.sample()
    assert reading.platform == "win32"
    assert reading.primary_metric == "commit_charge"
    assert reading.primary_bytes == reading.commit_charge_bytes > 0
    assert reading.uss_bytes is None
    grown = bytearray(64 * 1024 * 1024)
    grown[:: 4096] = b"x" * len(grown[:: 4096])
    assert process_memory.sample().primary_bytes - reading.primary_bytes > 48 * 1024 * 1024
    del grown


def test_an_unsupported_platform_fails_rather_than_reading_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_memory.sys, "platform", "darwin")
    with pytest.raises(RuntimeError, match="process_memory_unsupported_platform"):
        process_memory.sample()


def test_the_harness_takes_no_psutil_dependency() -> None:
    import ast

    for module in (process_memory, s1_memory):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert "psutil" not in imported


# --------------------------------------------------------------------------- fit
def test_fit_line_recovers_a_known_slope() -> None:
    fit = s1_memory.fit_line([(x, 3.5 * x + 100.0) for x in range(10)])
    assert fit["slope"] == pytest.approx(3.5)
    assert fit["intercept"] == pytest.approx(100.0)
    assert fit["r2"] == pytest.approx(1.0)
    assert fit["points"] == 10


@pytest.mark.parametrize("points", [[(1.0, 1.0), (2.0, 2.0)], [(1.0, 1.0), (1.0, 2.0), (1.0, 3.0)]])
def test_fit_line_refuses_an_underdetermined_series(points) -> None:
    with pytest.raises(ValueError):
        s1_memory.fit_line(points)


# --------------------------------------------------------------------------- the private seams
def test_the_observed_hooks_still_exist_with_the_shapes_the_harness_reads() -> None:
    # A refactor that renames these must fail here, not silently measure nothing.
    assert list(inspect.signature(VideoProcessor._accumulate).parameters) == ["self", "live", "context", "candidate"]
    assert "frame_reader" in inspect.signature(VideoProcessor.__init__).parameters
    fields = {field.name for field in dataclasses.fields(_TrackAccumulator)}
    assert {"evidence", "trajectory"} <= fields
    for name in ("point_count", "spilled_points"):
        assert isinstance(inspect.getattr_static(TrajectorySpool, name), property)


def test_presets_are_valid_and_match_the_plan() -> None:
    for preset in s1_memory.PRESETS.values():
        preset.validate()
        assert preset.tracker == "bytetrack", "authoritative presets use the native adapter"
        assert preset.gap_frames * 1000 / preset.fps > 1000 + 1000 / 30, "the gap must outlast ByteTrack retirement"
    presets = s1_memory.PRESETS
    base, long, crops = presets["b2-retained-baseline"], presets["b2-retained-long"], presets["b2-retained-large-crops"]
    assert min(p.retirements for p in (base, long, crops)) >= 1_000
    assert long.track_frames >= 10 * base.track_frames
    assert long.track_frames > s1_memory.DEFAULT_CHUNK_POINTS
    assert crops.box_px > base.box_px
    assert {base.mode, long.mode, crops.mode} == {"trace"}
    assert presets["b2-process-memory"].mode == "process"
    assert presets["b2-process-memory"].retirements >= 5_000
    live = [presets[f"b2-live-{level}"] for level in s1_memory.LIVE_LEVELS]
    assert len(live) >= 5 and {p.mode for p in live} == {"process"}
    peak = presets["b2-completion-peak"]
    assert peak.measure_completion and peak.retirements + peak.live_tracks <= 10_000


# --------------------------------------------------------------------------- structural runs
def test_a_small_fixture_run_accounts_every_term(tmp_path: Path) -> None:
    results = run(SMALL, tmp_path)
    assert results["retirements"] >= SMALL.retirements
    assert results["tracks"] >= results["retirements"]
    assert 0 < results["perLiveHeldEvidenceBytesMax"] <= s1_memory.PER_LIVE_HELD_BOUND_BYTES
    assert 0 < results["perLiveBufferedTrajectoryPointsMax"] <= SMALL.track_frames
    assert 1 <= results["liveMax"] <= SMALL.live_tracks
    assert results["admittedCropsByRole"]["representative"]["count"] == results["tracks"]
    assert results["admittedCropsByRole"]["representative"]["maxBytes"] <= 64 * KIB
    slope = results["retiredSlope"]
    assert slope["series"] == "tracemalloc-traced-bytes"
    assert slope["points"] >= 5
    assert 0 < slope["bytesPerRetiredTrack"] < 16 * KIB
    assert results["stagingPeakBytes"] > 0
    completion = results["completion"]
    assert completion["bodyBytes"] > 0 and completion["tracedPeakBytes"] >= completion["bodyBytes"]


def test_the_harness_detects_a_retained_crop_per_retired_track(tmp_path: Path) -> None:
    """Discrimination: a processor that keeps each Track's held evidence.

    The regression §6.2 exists to catch. It must move the slope past the
    16 KiB ceiling, which a clean run of the same workload stays under.
    """

    class RetainingProcessor(s1_memory.ObservedVideoProcessor):
        kept: list = []

        def _accumulate(self, live, context, candidate):
            super()._accumulate(live, context, candidate)
            self.kept.append(live[candidate.track_id].evidence)

    workload = dataclasses.replace(SMALL, measure_completion=False)
    clean = run(workload, tmp_path / "clean")["retiredSlope"]["bytesPerRetiredTrack"]
    leaking = run(workload, tmp_path / "leak", processor_class=RetainingProcessor)["retiredSlope"]["bytesPerRetiredTrack"]
    RetainingProcessor.kept.clear()
    assert clean < 16 * KIB < leaking


def test_the_harness_detects_a_trajectory_buffer_that_is_not_spilled(tmp_path: Path) -> None:
    workload = dataclasses.replace(SMALL, track_frames=40, measure_completion=False)

    default = run(workload, tmp_path / "a")
    assert default["perLiveBufferedTrajectoryPointsMax"] <= 40

    # With a 16-point chunk the buffered maximum must drop to the chunk; the
    # accounting reads the live spool, not the Track's length.
    class SmallChunkProcessor(s1_memory.ObservedVideoProcessor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, trajectory_chunk_points=16, **kwargs)

    chunked = run(workload, tmp_path / "b", processor_class=SmallChunkProcessor)
    assert chunked["perLiveBufferedTrajectoryPointsMax"] <= 16 < default["perLiveBufferedTrajectoryPointsMax"]


def test_a_tracker_that_never_retires_fails_instead_of_running_forever(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class NeverRetires:
        def update(self, frame, detections):
            return s1_memory.TrackerUpdate(())

    monkeypatch.setattr(s1_memory, "_make_tracker", lambda workload, scene: NeverRetires())
    workload = dataclasses.replace(SMALL, retirements=4, measure_completion=False)
    with pytest.raises(Exception) as raised:
        run(workload, tmp_path)
    chain = [raised.value, raised.value.__cause__]
    assert any("workload_frame_budget_exceeded" in str(error) for error in chain if error is not None)


def test_structural_runs_are_deterministic(tmp_path: Path) -> None:
    workload = dataclasses.replace(SMALL, retirements=20, measure_completion=False)
    first, second = run(workload, tmp_path / "1"), run(workload, tmp_path / "2")
    for key in ("framesProcessed", "retirements", "tracks", "admittedCropsByRole", "perLiveHeldEvidenceBytesMax", "perLiveBufferedTrajectoryPointsMax", "liveMax", "stagingPeakBytes"):
        assert first[key] == second[key], key


@pytest.mark.skipif(not (sys.platform.startswith("linux") or sys.platform == "win32"), reason="process probes exist for the qualified platforms only")
def test_a_process_mode_run_fits_the_platform_metric(tmp_path: Path) -> None:
    workload = dataclasses.replace(SMALL, mode="process", retirements=24, measure_completion=False)
    results = run(workload, tmp_path)
    metric = "uss" if sys.platform.startswith("linux") else "commit_charge"
    assert results["retiredSlope"]["series"] == f"process-{metric}"
    summary = results["process"]
    assert summary["metric"] == metric
    assert summary["baselineBytes"] > 0 and summary["peakRssBytes"] > 0
    samples = s1_memory.run_workload(workload, tmp_path / "again")
    summary = samples["results"]["process"]
    warm = [entry["process"]["primary_bytes"] for entry in samples["samples"] if entry["retired"] >= workload.retirements * workload.warmup_fraction]
    assert samples["samples"][0]["retired"] == 0 and samples["samples"][0]["frame"] == 0
    assert summary["baselineBytes"] == samples["samples"][0]["process"]["primary_bytes"]
    assert summary["afterWarmupBytes"] == warm[0]
    assert summary["plateauMeanBytes"] == pytest.approx(sum(warm) / len(warm))
    assert results["completion"] is None


def test_the_cli_writes_identified_machine_readable_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tiny = dataclasses.replace(SMALL, name="test-tiny", retirements=12, sample_every=2, measure_completion=False)
    monkeypatch.setitem(s1_memory.PRESETS, "test-tiny", tiny)
    output = tmp_path / "out.json"
    assert s1_memory.main(["run", "--preset", "test-tiny", "--output", str(output), "--work-root", str(tmp_path)]) == 0
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["schema"] == s1_memory.OUTPUT_SCHEMA
    assert record["frameSource"] == s1_memory.FRAME_SOURCE
    identity = record["identity"]
    assert len(identity["sourceSha"]) == 40 and isinstance(identity["cleanTree"], bool)
    assert identity["profileId"] == "phase1-detection-tracking-v1"
    assert len(identity["profileSha256"]) == 64
    assert record["runtime"]["versions"]["pillow"] and record["runtime"]["platform"] == sys.platform
    assert record["host"]["logicalCores"] >= 1
    assert record["workload"]["name"] == "test-tiny"
    assert output.read_text(encoding="utf-8").endswith("\n")


# --------------------------------------------------------------------------- derive
def _synthetic_outputs() -> dict[str, dict]:
    identity = {"sourceSha": "a" * 40, "cleanTree": True}
    runtime = {"platform": "linux", "runtimeVariant": "linux-x86_64-cpu", "versions": {"python": "3.12.14"}}
    host = {"cpuModel": "reference", "logicalCores": 8}
    outputs = {}
    for name, preset in s1_memory.PRESETS.items():
        slope = {"b2-retained-long": 2_100.0, "b2-retained-large-crops": 1_900.0, "b2-process-memory": 3_000.0}.get(name, 2_000.0)
        level = preset.live_tracks
        outputs[name] = {
            "schema": s1_memory.OUTPUT_SCHEMA,
            "identity": identity,
            "runtime": runtime,
            "host": host,
            "workload": dataclasses.asdict(preset),
            "results": {
                "retirements": preset.retirements,
                "perLiveHeldEvidenceBytesMax": 100_000 + level,
                "perLiveBufferedTrajectoryPointsMax": 4_000 + level,
                "retiredSlope": {"bytesPerRetiredTrack": slope, "stderr": slope * 0.01},
                "stagingPeakBytes": 1_000 * level,
                "stagingDerivedBoundBytes": 4_000 * level,
                "completion": {"tracedPeakBytes": 90_000_000, "bodyBytes": 30_000_000} if preset.measure_completion else None,
                "process": {"plateauMeanBytes": 50_000_000 + 200_000 * level} if preset.mode == "process" else None,
            },
        }
    return outputs


def test_derive_computes_the_bound_metrics() -> None:
    derived = s1_memory.derive(_synthetic_outputs())
    values = {name: entry["value"] for name, entry in derived["measurements"].items()}
    assert values["b2.per-retired-traced-bytes-slope"] == 2_100.0
    assert values["b2.retired-slope-duration-variation"] == pytest.approx(0.05)
    assert values["b2.retired-slope-crop-variation"] == pytest.approx(0.05)
    assert values["b2.process-memory-retired-slope"] == 3_000.0
    assert values["b2.completion-peak-bytes"] == 90_000_000
    assert values["b2.per-live-held-evidence-bytes-max"] == 100_064
    assert values["b2.staging-peak-bytes"] == 64_000
    assert values["b2.per-live-buffered-trajectory-points-max"] == 4_064
    # The per-live slope is a first-class metric, fitted from the five plateaus
    # it retains, and reconciled with the bound-1 accounting.
    assert values["b2.process-memory-per-live-track-slope"] == pytest.approx(200_000)
    assert values["b2.staging-peak-to-derived-bound-ratio"] == pytest.approx(0.25)
    fit = derived["liveLevelFit"]
    assert [level for level, _ in fit["points"]] == list(s1_memory.LIVE_LEVELS)
    assert fit["slope"] == pytest.approx(200_000) and fit["r2"] == pytest.approx(1.0)
    reconciliation = derived["boundOneReconciliation"]
    assert reconciliation["perLiveProcessSlopeBytes"] == values["b2.process-memory-per-live-track-slope"]
    assert reconciliation["unaccountedPerLiveBytes"] == pytest.approx(200_000 - reconciliation["accountedEncodedEvidenceBytesMax"])
    assert reconciliation["encodedEvidenceBoundBytes"] == s1_memory.PER_LIVE_HELD_BOUND_BYTES
    assert "processMemoryPerLiveTrackSlopeBytes" not in derived.get("recorded", {})


def test_derive_metric_names_are_the_ones_the_checker_binds() -> None:
    from s1_evidence import UNIT_REQUIREMENTS

    from s1_evidence import B2_BASE_MEASUREMENTS, QUALIFIED_CPU_VARIANTS

    # One derived output per variant, carrying every base metric the checker binds.
    bound = {requirement.metric: requirement.unit for requirement in B2_BASE_MEASUREMENTS}
    assert {r.metric for r in UNIT_REQUIREMENTS["B2"].measurements} == {f"{m}.{v}" for m in bound for v in QUALIFIED_CPU_VARIANTS}
    derived = s1_memory.derive(_synthetic_outputs())["measurements"]
    assert {name: entry["unit"] for name, entry in derived.items()} == bound


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda o: o.pop("b2-live-8"), "derive_outputs_missing"),
        (lambda o: o["b2-retained-long"]["workload"].update(tracker="fixture"), "derive_output_not_bytetrack"),
        (lambda o: o["b2-process-memory"]["results"].update(retirements=4_999), "derive_output_short"),
        (lambda o: o["b2-retained-long"].update(identity={"sourceSha": "b" * 40, "cleanTree": True}), "derive_outputs_mixed_identity"),
        (lambda o: [output.update(identity={"sourceSha": "a" * 40, "cleanTree": False}) for output in o.values()], "derive_output_not_clean_source"),
        (lambda o: [output.update(identity={"sourceSha": None, "cleanTree": True}) for output in o.values()], "derive_output_not_clean_source"),
        (lambda o: o["b2-live-4"].update(runtime=dict(o["b2-live-4"]["runtime"], runtimeVariant="windows-x86_64-cpu")), "derive_outputs_mixed_runtime"),
        (lambda o: o["b2-live-4"].update(host={"cpuModel": "other"}), "derive_outputs_mixed_host"),
        (lambda o: o["b2-live-4"].pop("host"), "derive_output_identity_incomplete"),
        (lambda o: [output["runtime"].update(runtimeVariant=None) for output in o.values()], "derive_output_not_qualified_variant"),
        (lambda o: o["b2-retained-long"].update(schema="other"), "derive_output_schema_invalid"),
        (lambda o: o["b2-retained-long"]["workload"].update(name="b2-retained-baseline"), "derive_output_preset_mismatch"),
        (lambda o: o["b2-retained-long"]["workload"].update(track_frames=450), "derive_output_workload_not_declared"),
        (lambda o: o["b2-retained-large-crops"]["workload"].update(box_px=144), "derive_output_workload_not_declared"),
    ],
)
def test_derive_refuses_outputs_that_cannot_be_evidence(mutate, code) -> None:
    outputs = _synthetic_outputs()
    mutate(outputs)
    with pytest.raises(ValueError, match=code):
        s1_memory.derive(outputs)


# --------------------------------------------------------------------------- native ByteTrack
native = pytest.mark.skipif(
    not NATIVE,
    reason="native ByteTrack runs in the Task-10 CPU matrix (MAVI_RUN_QUALIFIED_BYTETRACK_TESTS=1)",
)


@native
def test_a_small_native_bytetrack_run_retires_through_the_real_adapter(tmp_path: Path) -> None:
    workload = dataclasses.replace(SMALL, name="test-native", tracker="bytetrack", gap_frames=45, retirements=24)
    results = run(workload, tmp_path)
    assert results["retirements"] >= 24
    assert 0 < results["retiredSlope"]["bytesPerRetiredTrack"] < 16 * KIB
    assert 0 < results["perLiveHeldEvidenceBytesMax"] <= s1_memory.PER_LIVE_HELD_BOUND_BYTES


@native
def test_native_and_fixture_runs_agree_on_structure(tmp_path: Path) -> None:
    """Parity: the scripted scene gives the native adapter one Track per subject."""
    workload = dataclasses.replace(SMALL, gap_frames=45, retirements=16, measure_completion=False)
    fixture = run(workload, tmp_path / "fixture")
    native_run = run(dataclasses.replace(workload, tracker="bytetrack"), tmp_path / "native")
    assert native_run["retirements"] >= 16
    for results in (fixture, native_run):
        assert results["admittedCropsByRole"]["representative"]["count"] == results["tracks"]
    assert abs(native_run["tracks"] - fixture["tracks"]) <= workload.live_tracks


def test_slope_variation_is_the_plain_relative_change() -> None:
    fit = lambda slope, stderr=1.0: {"bytesPerRetiredTrack": slope, "stderr": stderr}  # noqa: E731
    assert s1_memory._variation(fit(2_000.0), fit(2_100.0))["value"] == pytest.approx(0.05)
    # No floor: a doubling from 100 B/track is a 100 % change, not 9.8 %.
    assert s1_memory._variation(fit(100.0), fit(200.0))["value"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("baseline", "reason"),
    [
        ({"bytesPerRetiredTrack": 0.0, "stderr": 0.0}, "not positive"),
        ({"bytesPerRetiredTrack": -50.0, "stderr": 1.0}, "not positive"),
        ({"bytesPerRetiredTrack": 100.0, "stderr": 10.0}, "cannot resolve"),
        ({"bytesPerRetiredTrack": 100.0}, "cannot resolve"),
    ],
)
def test_an_unresolvable_baseline_makes_variation_undefined(baseline, reason: str) -> None:
    result = s1_memory._variation(baseline, {"bytesPerRetiredTrack": 120.0, "stderr": 1.0})
    assert result["value"] is None and reason in result["undefined"]


def test_fit_line_reports_the_slope_standard_error() -> None:
    exact = s1_memory.fit_line([(x, 2.0 * x) for x in range(10)])
    assert exact["stderr"] == pytest.approx(0.0, abs=1e-9)
    noisy = s1_memory.fit_line([(0, 0.0), (1, 3.0), (2, 1.0), (3, 5.0), (4, 2.0)])
    assert noisy["stderr"] > 0


def test_the_checker_trajectory_bound_is_the_spool_chunk() -> None:
    from s1_evidence import TRAJECTORY_CHUNK_POINTS

    assert TRAJECTORY_CHUNK_POINTS == s1_memory.DEFAULT_CHUNK_POINTS


# --------------------------------------------------------------------------- §6.3 staging lifecycle and bound
LIFECYCLE = dataclasses.replace(
    s1_memory.LIFECYCLE_WORKLOAD, tracker="fixture", gap_frames=12, retirements=12, track_frames=20, sample_every=2
)


def test_the_staging_lifecycle_holds_on_the_real_processor(tmp_path: Path) -> None:
    output = s1_memory.staging_lifecycle(LIFECYCLE, tmp_path)
    assert output["schema"] == "s1-b2-staging-lifecycle-v1"
    assert output["checks"] == {check: True for check in s1_memory_checks()}


def s1_memory_checks():
    from s1_evidence import STAGING_LIFECYCLE_CHECKS

    return STAGING_LIFECYCLE_CHECKS


def test_a_processor_that_leaks_failed_attempt_staging_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s1_memory.VideoProcessor, "_cleanup_best_effort", lambda self, guard: None)
    checks = s1_memory.staging_lifecycle(LIFECYCLE, tmp_path)["checks"]
    assert checks["failedAttemptCleaned"] is False and checks["supersededAttemptRemoved"] is True


def test_a_store_that_never_supersedes_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s1_memory.StagingArtifactStore, "cleanup_superseded_attempts", lambda self: None)
    checks = s1_memory.staging_lifecycle(LIFECYCLE, tmp_path)["checks"]
    assert checks["supersededAttemptRemoved"] is False and checks["failedAttemptCleaned"] is True


def test_staging_beyond_the_derived_bound_is_detected(tmp_path: Path) -> None:
    workload = dataclasses.replace(SMALL, retirements=12, sample_every=2, measure_completion=False)
    clean = run(workload, tmp_path / "clean")
    assert 0 < clean["stagingPeakBytes"] <= clean["stagingDerivedBoundBytes"]
    # The bound is ADR-013's derivation applied to this run's own Tracks: 544
    # KiB each, plus the trajectory artifacts staged and their spool records.
    terms = clean["stagingDerivedBoundTerms"]
    staged = s1_memory.attempt_directory(tmp_path / "clean", s1_memory.JOB_ID, 1)
    assert terms["tracks"] == clean["tracks"] > 0
    assert terms["perTrackEvidenceBoundBytes"] == 64 * 1024 + 3 * 160 * 1024
    assert terms["trajectoryArtifactBytes"] == sum(path.stat().st_size for path in staged.rglob("trajectories/*.msgpack")) > 0
    assert terms["spoolRecordBytes"] > 0 and terms["spoolRecordBytes"] % s1_memory.SPOOL_RECORD_BYTES == 0
    assert clean["stagingDerivedBoundBytes"] == (
        terms["tracks"] * terms["perTrackEvidenceBoundBytes"] + terms["trajectoryArtifactBytes"] + terms["spoolRecordBytes"]
    )

    attempt = s1_memory.attempt_directory(tmp_path / "junk", s1_memory.JOB_ID, 1)
    junk = attempt / "junk.bin"

    def stage_junk(frame: int) -> None:
        # Once the attempt has staged something, add bytes no Track accounts for.
        if attempt.exists() and not junk.exists():
            junk.write_bytes(b"\0" * (clean["stagingDerivedBoundBytes"] * 2))

    leaking = run(workload, tmp_path / "junk", on_frame=stage_junk)
    assert leaking["stagingPeakBytes"] > leaking["stagingDerivedBoundBytes"]


def test_a_lifecycle_phase_beyond_its_derived_bound_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = s1_memory.run_workload

    def superseding_over_its_bound(*args, **kwargs):
        output = real(*args, **kwargs)
        if kwargs.get("attempt_count") == 3:
            output["results"]["stagingPeakBytes"] = output["results"]["stagingDerivedBoundBytes"] + 1
        return output

    monkeypatch.setattr(s1_memory, "run_workload", superseding_over_its_bound)
    checks = s1_memory.staging_lifecycle(LIFECYCLE, tmp_path)["checks"]
    assert checks["peaksWithinDerivedBound"] is False
    assert all(value for name, value in checks.items() if name != "peaksWithinDerivedBound")
