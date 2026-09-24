"""S1.4 B1 real-clip comparison (plan §5.3).

Derives the four B1 counts from retained real-clip runs, so the evidence record
cannot assert them:

- ``withinVariantRepeatMismatches``: a run and its repeat on each variant;
- ``untracedCrossVariantDivergences``: the Linux run against the Windows run,
  minus the divergences a reviewed trace explains;
- ``parameterNoteMismatches``: the Linux run against the accepted S1.2c
  baseline (``docs/qualification/stage2-s1/b1-accepted-real-clip-baseline.json``);
- ``replayMismatches``: the Linux run against its detector-independent replay.

Inputs are ``summary.json`` files written by
``tools/vision/dev/measure_evidence_real_clips.py``. Every comparison is exact.
Only host-dependent timing (``processingSeconds``, ``peakRssKiB``) is excluded.
A run on another profile, other clips or the wrong variant is an identity
problem, recorded in the output and refused by the checker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO / "docs/qualification/stage2-s1/b1-accepted-real-clip-baseline.json"
BASELINE_SCHEMA = "s1-b1-real-clip-baseline-v1"
COMPARISON_SCHEMA = "s1-b1-comparison-v1"
HOST_DEPENDENT_KEYS = frozenset({"processingSeconds", "peakRssKiB"})
COMPARED_SECTIONS = ("clips", "perClip", "combined")
RUNS = {
    "linux": "linux-x86_64-cpu",
    "linuxRepeat": "linux-x86_64-cpu",
    "windows": "windows-x86_64-cpu",
    "windowsRepeat": "windows-x86_64-cpu",
    "linuxReplay": "linux-x86_64-cpu",
}


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items() if key not in HOST_DEPENDENT_KEYS}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def normalized(summary: dict[str, Any]) -> dict[str, Any]:
    """The compared part of a summary: results, never host timing or provenance."""
    return {section: _strip(summary[section]) for section in COMPARED_SECTIONS}


def diff(left: Any, right: Any, path: str = "") -> list[str]:
    """Every JSON path at which two values differ, exactly."""
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right), key=str):
            if key not in left or key not in right:
                paths.append(f"{path}/{key}")
            else:
                paths.extend(diff(left[key], right[key], f"{path}/{key}"))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [f"{path}[len]"]
        return [p for index, (a, b) in enumerate(zip(left, right)) for p in diff(a, b, f"{path}[{index}]")]
    return [] if left == right and type(left) is type(right) else [path or "/"]


def make_baseline(summary: dict[str, Any]) -> dict[str, Any]:
    provenance = summary["provenance"]
    return {
        "schema": BASELINE_SCHEMA,
        "source": {
            "maviCommit": provenance["mavi_commit"],
            "pipelineProfileSha256": provenance["pipeline_profile_sha256"],
            "runtimeVariant": provenance["runtime_variant"],
            "clips": [{"clip": clip["clip"], "sha256": clip["sha256"]} for clip in summary["clips"]],
        },
        **normalized(summary),
    }


def _identity_problems(name: str, summary: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    provenance = summary.get("provenance", {})
    source = baseline["source"]
    problems = []
    profile = provenance.get("pipelineProfileSha256") if provenance.get("replay") else provenance.get("pipeline_profile_sha256")
    if profile != source["pipelineProfileSha256"]:
        problems.append(f"{name}: profile {profile} is not the baseline's {source['pipelineProfileSha256']}")
    clips = [{"clip": clip["clip"], "sha256": clip["sha256"]} for clip in summary.get("clips", [])]
    if clips != source["clips"]:
        problems.append(f"{name}: clips {clips} are not the baseline's original files")
    if name == "linuxReplay":
        if provenance.get("replay") is not True:
            problems.append("linuxReplay: not a detector-independent replay")
    elif provenance.get("runtime_variant") != RUNS[name]:
        problems.append(f"{name}: ran on {provenance.get('runtime_variant')!r}, not {RUNS[name]}")
    return problems


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_identity() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()

    try:
        return {"sourceSha": git("rev-parse", "HEAD"), "cleanTree": git("status", "--porcelain") == ""}
    except (OSError, subprocess.CalledProcessError):
        return {"sourceSha": None, "cleanTree": False}


def compare(baseline: dict[str, Any], runs: dict[str, dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
    """The four B1 counts, derived. ``traces`` explain cross-variant divergences:
    ``{"path", "cause", "reviewedBy"}``; an incomplete trace explains nothing."""
    if baseline.get("schema") != BASELINE_SCHEMA:
        raise ValueError("b1_baseline_schema_invalid")
    missing = sorted(set(RUNS) - runs.keys())
    if missing:
        raise ValueError(f"b1_runs_missing:{missing}")
    problems = [problem for name in RUNS for problem in _identity_problems(name, runs[name], baseline)]
    view = {name: normalized(summary) for name, summary in runs.items()}
    repeat = diff(view["linux"], view["linuxRepeat"]) + diff(view["windows"], view["windowsRepeat"])
    cross = diff(view["linux"], view["windows"])
    traced = {trace["path"] for trace in traces if trace.get("path") and trace.get("cause") and trace.get("reviewedBy")}
    baseline_view = {section: baseline[section] for section in COMPARED_SECTIONS}
    note = diff(baseline_view, view["linux"])
    replay = diff(view["linux"], view["linuxReplay"])
    return {
        "schema": COMPARISON_SCHEMA,
        "identityProblems": problems,
        "counts": {
            "withinVariantRepeatMismatches": len(repeat),
            "untracedCrossVariantDivergences": len([path for path in cross if path not in traced]),
            "parameterNoteMismatches": len(note),
            "replayMismatches": len(replay),
        },
        "diffs": {"repeat": repeat, "crossVariant": cross, "parameterNote": note, "replay": replay},
        "traces": traces,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1.4 B1 real-clip comparison")
    commands = parser.add_subparsers(dest="command", required=True)
    base = commands.add_parser("baseline", help="write the accepted baseline from an accepted summary.json")
    base.add_argument("summary", type=Path)
    base.add_argument("--output", type=Path, default=BASELINE_PATH)
    comp = commands.add_parser("compare", help="derive the four B1 counts")
    for name in RUNS:
        comp.add_argument(f"--{name}", required=True, type=Path)
    comp.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    comp.add_argument("--traces", type=Path, default=None)
    comp.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "baseline":
        baseline = make_baseline(json.loads(args.summary.read_text(encoding="utf-8")))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0

    paths = {name: getattr(args, name) for name in RUNS}
    runs = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}
    traces = json.loads(args.traces.read_text(encoding="utf-8")) if args.traces else []
    result = compare(json.loads(args.baseline.read_text(encoding="utf-8")), runs, traces)
    result["identity"] = _source_identity()
    result["inputs"] = {name: {"sha256": _sha256(path)} for name, path in paths.items()} | {
        "baseline": {"sha256": _sha256(args.baseline)}
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"]), result["identityProblems"] or "")
    return 0 if not result["identityProblems"] else 1


if __name__ == "__main__":
    sys.exit(main())
