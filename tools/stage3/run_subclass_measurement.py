#!/usr/bin/env python3
"""Measurement runner and requirement comparison (Stage 3, S3.2 plan T6).

It verifies every input identity, runs the T2 Track-label evaluator, and applies the
pre-registered requirements to the primary aggregate. It encodes no mechanism
decision: each criterion reports only ``meets``, ``does-not-meet``,
``insufficient-support`` or ``no-requirement``.

Usage::

    run_subclass_measurement.py --sample <file>... --labels <file>... [--overlap-labels <file>...
        --adjudication <file>...] --pack <dir>... --export <file>... --pipeline-profile <file>
        --requirements <file> [--repository <git-dir>] --out <new-dir>

Writes ``measurement-result.json``, ``requirement-comparison.json`` and
``measurement-summary.md`` into a new directory, or nothing.
"""

from __future__ import annotations

import argparse
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "phase1"))
import artefacts as a  # noqa: E402
import evaluate_vehicle_subclass as evaluator  # noqa: E402
from build_labeling_pack import verify_pack  # noqa: E402

RESULT = "measurement-result.json"
COMPARISON = "requirement-comparison.json"
SUMMARY = "measurement-summary.md"
COMPARISON_SCHEMA = "vehicle-subclass-requirement-comparison-v1"


def status(minimum: float | None, observed: dict[str, Any], support: int, minimum_support: int) -> str:
    """``no-requirement`` without a bound; ``insufficient-support`` below the minimum support *or* when the
    estimate is undefined (for example precision with no prediction of the class: there is nothing to
    compare); otherwise ``meets`` or ``does-not-meet`` by exact rational comparison."""
    if minimum is None:
        return "no-requirement"
    if support < minimum_support or observed["denominator"] == 0:
        return "insufficient-support"
    return "meets" if Fraction(observed["numerator"], observed["denominator"]) >= Fraction(repr(minimum)) else "does-not-meet"


def compare(requirements: dict[str, Any], requirements_sha: str, measurement: dict[str, Any], measurement_sha: str) -> dict[str, Any]:
    """The pre-registered criteria against the primary aggregate's descriptive point estimates."""
    metrics = measurement["primary"]["metrics"]
    per_class_minimum = requirements["minimumSupport"]["evaluablePerClass"]
    total_minimum = requirements["minimumSupport"]["evaluableTotal"]
    coverage_minimum = requirements["operational"]["coverageOverEvaluable"]["minimum"]
    criteria = [{
        "criterion": "coverageOverEvaluable", "class": None, "minimum": coverage_minimum,
        "observed": metrics["coverageOverEvaluable"], "support": metrics["evaluableTracks"],
        "minimumSupport": total_minimum,
        "status": status(coverage_minimum, metrics["coverageOverEvaluable"], metrics["evaluableTracks"], total_minimum),
    }]
    for name in a.CLASSES:
        row = metrics["perClass"][name]
        for criterion in ("precision", "recall"):
            minimum = requirements["operational"]["perClass"][name][criterion]["minimum"]
            criteria.append({
                "criterion": criterion, "class": name, "minimum": minimum, "observed": row[criterion],
                "support": row["support"], "minimumSupport": per_class_minimum,
                "status": status(minimum, row[criterion], row["support"], per_class_minimum),
            })
    document = {"schemaVersion": COMPARISON_SCHEMA, "measurementSha256": measurement_sha,
                "requirementsSha256": requirements_sha, "criteria": criteria}
    a.validate(document, COMPARISON_SCHEMA, "comparison_invalid")
    return document


def _value(fraction: dict[str, Any]) -> str:
    return "undefined" if fraction["value"] is None else f"{fraction['numerator']}/{fraction['denominator']}"


def summary(measurement: dict[str, Any], measurement_sha: str, comparison: dict[str, Any]) -> bytes:
    """Generated tables only. Predictions appear here first: every label and adjudication is frozen by now."""
    primary = measurement["primary"]
    metrics = primary["metrics"]
    lines = [
        "# Vehicle subclass measurement",
        "",
        f"> {measurement['scope']}",
        "",
        f"- Measurement: `{measurement_sha}`",
        f"- Requirements: `{measurement['inputs']['requirementsSha256']}`",
        f"- Pipeline profile: `{measurement['inputs']['measuredProfileSha256']}`",
        f"- Model: {measurement['producer']['modelId']} {measurement['producer']['modelVersion']}; "
        f"MAVI commit `{measurement['producer']['maviCommit']}`",
        f"- Primary aggregate: {len(primary['sampleSha256s'])} batch(es); supplemental: {len(measurement['supplemental'])} "
        "(reported separately, never pooled).",
        "",
        "Descriptive point estimates as exact fractions; no confidence intervals.",
        "",
        "## Support",
        "",
        f"Labelled Tracks {metrics['labelledTracks']}; evaluable {metrics['evaluableTracks']}; "
        f"resolved {metrics['resolved']}; abstained {metrics['abstained']}; "
        f"coverage {_value(metrics['coverageOverEvaluable'])}.",
        "",
        "| Human unknown reason | Tracks |",
        "|---|---|",
        *(f"| {reason} | {count} |" for reason, count in metrics["humanUnknown"].items()),
        "",
        "## Confusion (rows: human; columns: MAVI)",
        "",
        "| | " + " | ".join(a.OUTCOMES) + " |",
        "|---|" + "---|" * len(a.OUTCOMES),
        *(f"| {truth} | " + " | ".join(str(metrics["confusion"][truth][o]) for o in a.OUTCOMES) + " |" for truth in a.CLASSES),
        "| *unknown* | " + " | ".join(str(metrics["unknownRow"][o]) for o in a.OUTCOMES) + " |",
        "",
        "## Per class",
        "",
        "| Class | Support | Predicted | Correct | Precision | Recall |",
        "|---|---|---|---|---|---|",
        *(f"| {c} | {r['support']} | {r['predicted']} | {r['correct']} | {_value(r['precision'])} | {_value(r['recall'])} |"
          for c, r in metrics["perClass"].items()),
        "",
        f"Accuracy over evaluable {_value(metrics['accuracyOverEvaluable'])}; over resolved "
        f"{_value(metrics['accuracyOverResolved'])}; macro recall over classes with support "
        f"{metrics['macroRecallOverClassesWithSupport']['classes']} "
        f"{'undefined' if metrics['macroRecallOverClassesWithSupport']['value'] is None else repr(metrics['macroRecallOverClassesWithSupport']['value'])}.",
        "",
        "## Requirement comparison (primary aggregate)",
        "",
        "| Criterion | Class | Minimum | Observed | Support / minimum | Status |",
        "|---|---|---|---|---|---|",
        *(f"| {c['criterion']} | {c['class'] or '-'} | {'none' if c['minimum'] is None else c['minimum']} | "
          f"{_value(c['observed'])} | {c['support']} / {c['minimumSupport']} | {c['status']} |" for c in comparison["criteria"]),
        "",
        "## Clusters",
        "",
        "| Camera | Videos | Evaluable | Resolved | Correct |",
        "|---|---|---|---|---|",
        *(f"| {c['cameraCode']} | {c['videoCount']} | {c['evaluableTracks']} | {c['resolved']} | {c['correct']} |"
          for c in primary["clusters"]["perCamera"]),
        "",
        "## Error references (pack item ids)",
        "",
        "| Pack | Item | Human | MAVI |",
        "|---|---|---|---|",
        *(f"| `{e['packSha256'][:12]}` | `{e['itemId']}` | {e['label']} | {e['predicted']} |" for e in primary["errorReferences"]),
        "",
    ]
    for supplemental in measurement["supplemental"]:
        s = supplemental["metrics"]
        lines += [f"## Supplemental batch `{supplemental['sampleSha256'][:12]}` (separate; not pooled)", "",
                  f"Evaluable {s['evaluableTracks']}; accuracy over evaluable {_value(s['accuracyOverEvaluable'])}; "
                  f"coverage {_value(s['coverageOverEvaluable'])}.", ""]
    return "\n".join(lines).encode("utf-8")


def run(args: argparse.Namespace, staging: Path) -> str:
    inputs = evaluator.read_track_label_inputs(argparse.Namespace(
        sample=args.sample, track_labels=args.labels, overlap_labels=args.overlap_labels,
        adjudication=args.adjudication, export=args.export, pipeline_profile=args.pipeline_profile))

    # Packs: every label file's pack, verified and regenerated; nothing unused.
    packs: dict[str, dict[str, Any]] = {}
    for directory in args.pack:
        manifest, sha = verify_pack(directory)
        a.require(sha not in packs, "pack_duplicate")
        packs[sha] = manifest
    used = set()
    for labels, _ in [*inputs["primary_labels"], *inputs["overlap_labels"]]:
        manifest = packs.get(labels["packSha256"])
        a.require(manifest is not None, "pack_missing")
        a.require(manifest["viewKind"] == labels["viewKind"] and manifest["sampleSha256"] == labels["sampleSha256"]
                  and manifest["exportSha256s"] == labels["exportSha256s"]
                  and manifest["labelingGuide"]["sha256"] == labels["labelingGuideSha256"]
                  and manifest.get("parentPackSha256") == labels.get("parentPackSha256"), "pack_labels_mismatch")
        items = {item["itemId"]: item for item in manifest["items"]}
        a.require({d["itemId"] for d in labels["decisions"]} == set(items), "pack_labels_mismatch:items")
        for decision in labels["decisions"]:
            item = items[decision["itemId"]]
            a.require((decision["processingRunId"], decision["trackId"], decision["videoSourceSha256"])
                      == (item["processingRunId"], item["trackId"], item["videoSourceSha256"]), "pack_labels_mismatch:item")
        used.add(labels["packSha256"])
    a.require(used == set(packs), "pack_unused")
    a.require(len(inputs["adjudications"]) == len(inputs["overlap_labels"]), "adjudication_missing")

    # Requirements: the file the samples bound, byte-identical at the recorded commit.
    requirements_bytes = a.read_bytes(args.requirements, "requirements_missing")
    requirements = a.parse_json(requirements_bytes, "requirements_invalid")
    a.validate(requirements, "vehicle-subclass-requirements-v1", "requirements_invalid")
    requirements_sha = a.sha256_hex(requirements_bytes)
    for sample, _ in inputs["samples"]:
        bound = sample["requirements"]
        a.require(bound["sha256"] == requirements_sha, "requirements_binding_mismatch")
        try:
            a.git_binding(args.repository, args.requirements, bound["gitCommit"], bound["gitPath"], "requirements_binding_mismatch")
        except a.S32Error as exc:
            raise a.S32Error(f"requirements_binding_mismatch:{exc}") from exc

    try:
        measurement = evaluator.evaluate_track_labels(**inputs)
    except evaluator.SubclassEvaluationError as exc:
        raise a.S32Error(str(exc)) from exc
    measurement_bytes = a.canonical_json(measurement)
    measurement_sha = a.sha256_hex(measurement_bytes)
    comparison = compare(requirements, requirements_sha, measurement, measurement_sha)
    (staging / RESULT).write_bytes(measurement_bytes)
    (staging / COMPARISON).write_bytes(a.canonical_json(comparison))
    (staging / SUMMARY).write_bytes(summary(measurement, measurement_sha, comparison))
    return measurement_sha


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sample", type=Path, action="append", required=True)
    p.add_argument("--labels", type=Path, action="append", required=True)
    p.add_argument("--overlap-labels", type=Path, action="append", default=[])
    p.add_argument("--adjudication", type=Path, action="append", default=[])
    p.add_argument("--pack", type=Path, action="append", required=True)
    p.add_argument("--export", type=Path, action="append", required=True)
    p.add_argument("--pipeline-profile", type=Path, required=True)
    p.add_argument("--requirements", type=Path, required=True)
    p.add_argument("--repository", type=Path, default=a.ROOT,
                   help="the git repository holding the committed requirements (default: this MAVI checkout)")
    p.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        with a.OutputDirectory(args.out) as staging:
            measurement_sha = run(args, staging)
    except a.S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(measurement_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
