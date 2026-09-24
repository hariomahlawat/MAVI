"""The B1 comparison derives its four counts exactly, from the runs themselves."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import s1_b1

BASELINE = json.loads(s1_b1.BASELINE_PATH.read_text(encoding="utf-8"))


def _run(variant: str, *, replay: bool = False) -> dict:
    """A summary.json equal to the accepted baseline, as the harness writes it."""
    source = BASELINE["source"]
    summary = {section: copy.deepcopy(BASELINE[section]) for section in s1_b1.COMPARED_SECTIONS}
    for clip in summary["clips"]:
        clip["processingSeconds"] = 12.5 if variant.startswith("linux") else 19.0  # host timing, ignored
    if replay:
        summary["provenance"] = {"replay": True, "pipelineProfileSha256": source["pipelineProfileSha256"], "detectionsSha256": {}}
    else:
        summary["provenance"] = {"runtime_variant": variant, "pipeline_profile_sha256": source["pipelineProfileSha256"], "mavi_commit": "a" * 40}
    return summary


def _runs() -> dict:
    return {
        "linux": _run("linux-x86_64-cpu"),
        "linuxRepeat": _run("linux-x86_64-cpu"),
        "windows": _run("windows-x86_64-cpu"),
        "windowsRepeat": _run("windows-x86_64-cpu"),
        "linuxReplay": _run("linux-x86_64-cpu", replay=True),
    }


def test_the_committed_baseline_is_the_accepted_s12c_measurement() -> None:
    # The parameter note's accepted figures (docs/qualification/2026-09-24-evidence-selector-parameter-note.md).
    assert BASELINE["schema"] == s1_b1.BASELINE_SCHEMA
    assert BASELINE["source"]["pipelineProfileSha256"] == "503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb"
    assert BASELINE["source"]["maviCommit"].startswith("3175cae")
    assert [clip["clip"] for clip in BASELINE["source"]["clips"]] == ["MOT17-02-FRCNN", "MOT17-13-FRCNN"]
    assert BASELINE["combined"]["tracks"] == 63 and BASELINE["combined"]["candidateFrames"] == 8284
    assert BASELINE["combined"]["fallbackRepresentatives"] == 9
    assert [(p["tracks"], p["candidateFrames"]) for p in BASELINE["perClip"]] == [(21, 3875), (42, 4409)]
    assert "rows" not in BASELINE and all("processingSeconds" not in clip for clip in BASELINE["clips"])


def test_identical_runs_give_zero_counts_and_no_identity_problem() -> None:
    result = s1_b1.compare(BASELINE, _runs(), [])
    assert result["identityProblems"] == []
    assert result["counts"] == {
        "withinVariantRepeatMismatches": 0,
        "untracedCrossVariantDivergences": 0,
        "parameterNoteMismatches": 0,
        "replayMismatches": 0,
    }


@pytest.mark.parametrize(
    ("run", "count"),
    [
        ("linuxRepeat", "withinVariantRepeatMismatches"),
        ("windowsRepeat", "withinVariantRepeatMismatches"),
        ("linuxReplay", "replayMismatches"),
    ],
)
def test_one_changed_track_is_counted(run: str, count: str) -> None:
    runs = _runs()
    runs[run]["clips"][0]["tracks"][0]["resolved"] = ["representative"]
    assert s1_b1.compare(BASELINE, runs, [])["counts"][count] >= 1


def test_a_linux_change_is_a_parameter_note_mismatch_and_a_cross_variant_divergence() -> None:
    runs = _runs()
    runs["linux"]["combined"]["fallbackRepresentatives"] = 10
    runs["linuxRepeat"]["combined"]["fallbackRepresentatives"] = 10
    runs["linuxReplay"]["combined"]["fallbackRepresentatives"] = 10
    counts = s1_b1.compare(BASELINE, runs, [])["counts"]
    assert counts["parameterNoteMismatches"] == 1 and counts["untracedCrossVariantDivergences"] == 1
    assert counts["withinVariantRepeatMismatches"] == 0 and counts["replayMismatches"] == 0


def test_only_a_complete_trace_explains_a_divergence() -> None:
    runs = _runs()
    runs["windows"]["combined"]["distributions"]["sharpness"]["p50"] += 0.000001
    runs["windowsRepeat"]["combined"]["distributions"]["sharpness"]["p50"] += 0.000001
    path = "/combined/distributions/sharpness/p50"
    assert s1_b1.compare(BASELINE, runs, [])["counts"]["untracedCrossVariantDivergences"] == 1
    assert s1_b1.compare(BASELINE, runs, [{"path": path, "cause": "libm rounding"}])["counts"]["untracedCrossVariantDivergences"] == 1
    traced = [{"path": path, "cause": "libm rounding", "reviewedBy": "owner"}]
    assert s1_b1.compare(BASELINE, runs, traced)["counts"]["untracedCrossVariantDivergences"] == 0


def test_host_timing_is_excluded_and_nothing_else() -> None:
    runs = _runs()
    runs["linuxRepeat"]["clips"][0]["processingSeconds"] = 999.0
    runs["linuxRepeat"]["clips"][0]["peakRssKiB"] = 1
    assert s1_b1.compare(BASELINE, runs, [])["counts"]["withinVariantRepeatMismatches"] == 0
    runs["linuxRepeat"]["clips"][0]["framesProcessed"] += 1
    assert s1_b1.compare(BASELINE, runs, [])["counts"]["withinVariantRepeatMismatches"] == 1


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda r: r["linux"]["provenance"].update(pipeline_profile_sha256="0" * 64), "profile"),
        (lambda r: r["windows"]["provenance"].update(runtime_variant="linux-x86_64-cpu"), "ran on"),
        (lambda r: r["linux"]["clips"][0].update(sha256="0" * 64), "original files"),
        (lambda r: r["linuxReplay"]["provenance"].update(replay=False), "replay"),
    ],
)
def test_a_run_with_the_wrong_identity_is_an_identity_problem(mutate, fragment: str) -> None:
    runs = _runs()
    mutate(runs)
    problems = s1_b1.compare(BASELINE, runs, [])["identityProblems"]
    assert problems and any(fragment in problem for problem in problems)


def test_every_run_is_required() -> None:
    runs = _runs()
    del runs["linuxReplay"]
    with pytest.raises(ValueError, match="b1_runs_missing"):
        s1_b1.compare(BASELINE, runs, [])


def test_diff_is_exact_about_types_and_lengths() -> None:
    assert s1_b1.diff({"a": 1}, {"a": 1.0}) == ["/a"]
    assert s1_b1.diff([1, 2], [1, 2, 3]) == ["[len]"]
    assert s1_b1.diff({"a": 1}, {"b": 1}) == ["/a", "/b"]


def test_the_cli_writes_identified_counts(tmp_path: Path) -> None:
    paths = {}
    for name, summary in _runs().items():
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(summary), encoding="utf-8")
    output = tmp_path / "comparison.json"
    argv = ["compare", "--output", str(output)] + [arg for name, path in paths.items() for arg in (f"--{name}", str(path))]
    assert s1_b1.main(argv) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == s1_b1.COMPARISON_SCHEMA
    assert len(result["identity"]["sourceSha"]) == 40
    assert set(result["inputs"]) == set(s1_b1.RUNS) | {"baseline"}
