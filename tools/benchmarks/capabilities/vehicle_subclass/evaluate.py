"""Vehicle-subclass benchmark evaluation → ``benchmark-vehicle-subclass-result-v1`` (plan §6, §8).

**Bound inputs.** Every input is reconciled with the association's run envelope before anything is scored: the
association itself (envelope, policy binding, sequence set, body hash), the descriptor (``descriptorSha256``), the
mapping (``mappingSha256``, checked against the descriptor's taxonomy), the registered requirements
(``requirementsSha256``, and the registered S3.2 identity), each sequence's canonical GT (``groundTruthSha256``),
and the T1 exports (``exportSha256s``, the single attested producer, each sequence's run). The association's GT and
MAVI Track sets must be exactly the GT documents' tracks and the exports' Vehicle Tracks.

**Scope A** (detection and tracking coverage, not subclass accuracy) partitions non-ignored GT by mapping:
expected-vehicle GT (``exact``, ``subset``, ``unsupported/vehicle-unresolved``) and outside-capability GT (negatives,
never in a vehicle denominator); ignored GT is counted and in no population. The coverage-limited GT rate is
(ambiguous + fragmented + merged + unverified) ÷ expected-vehicle GT; above 1/10 the result is reported
coverage-limited and the owner decides before H3 relies on it (plan §7.7). It never changes the association.

**Scope B** (Track-conditional) scores assigned pairs only, with MAVI's stored Track outcome (``outcome.py``):
- confusion over ``exact`` GT only; recall(C) and support(C) over assigned exact-C pairs (``undetermined`` stays in
  the denominator); a class without an exact native class has ``recall: not-in-dataset``;
- precision(C) over every judgeable prediction (exact and subset truths are their mapped class; outside-capability
  truth is no vehicle class), decided in this order: any C-prediction on a ``vehicle-unresolved`` track →
  ``not-available`` with ``precisionAmongJudgedTracks`` and the unjudgeable count; C predicted on no assigned track
  → ``no-judgeable-predictions``; otherwise computed;
- subset classes have their own block and enter precision only; unsupported classes are listed with their outcomes;
- per-class requirement status uses the T6 ordering (``run_subclass_measurement.status``) after ``not-in-dataset``;
  macro figures run only over classes with exact GT and support at the registered floor; taxonomy coverage is
  derived from the mapping.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.benchmarks.capabilities.vehicle_subclass import outcome as outcomes
from tools.benchmarks.capabilities.vehicle_tracks import association as associations
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as gt_module
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core import envelope as envelopes
from tools.benchmarks.core import mapping as mappings
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import (
    canonical_json, document_sha256, rational, require, require_canonical_rationals, validate, write_once)

import run_subclass_measurement  # noqa: E402  (tools/stage3, on the path via _stage3)

SCHEMA = "benchmark-vehicle-subclass-result-v1"
CODE = "result_invalid"
REQUIREMENTS_SCHEMA = "vehicle-subclass-requirements-v1"
CLASSES = outcomes.CLASSES
OUTCOMES = outcomes.OUTCOMES
UNDETERMINED = outcomes.UNDETERMINED
ESCALATION_THRESHOLD = Fraction(1, 10)
SCOPE_A = ("End-to-end association coverage (detection and tracking); not subclass accuracy. Outside-capability "
           "GT are negatives and never enter a vehicle denominator; ignored GT enter no population. "
           "Development/reference evidence; not independent generalisation evidence.")
SCOPE_B = ("Track-conditional: subclass classification given that MAVI produced the Track and it was associated to "
           "ground truth; detection and tracking misses stay in scope A. Development/reference evidence; not "
           "frozen qualification.")
GT_STATE = {"ambiguousGt": "ambiguous", "mergedGt": "merged", "fragmentedGt": "fragmented",
            "unverifiedGt": "unverified", "unmatchedGt": "unmatched"}
MAVI_STATE = {"fragmentMavi": "fragment", "ignoredMavi": "ignored", "unverifiedMavi": "unverified",
              "unmatchedMavi": "unmatched"}


def fraction(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator,
            "value": None if denominator == 0 else numerator / denominator}


def _mean(values: list[Fraction]) -> dict[str, Any] | None:
    if not values:
        return None
    mean = sum(values, Fraction(0)) / len(values)
    return fraction(mean.numerator, mean.denominator)


def load_requirements(path: Path) -> tuple[dict[str, Any], str]:
    """The registered S3.2 requirements (canonical bytes, schema, the registered identity)."""
    document, _, sha = artefacts.read_artefact(path, REQUIREMENTS_SCHEMA, "requirements_invalid")
    require(sha == artefacts.REGISTERED_REQUIREMENTS_SHA256, "requirements_not_registered")
    return document, sha


# Binding


def _bind(association: dict[str, Any], descriptor: dict[str, Any], mapping: dict[str, Any],
          ground_truth: dict[str, dict[str, Any]], exports: dict[str, artefacts.Export], requirements_sha256: str,
          ) -> tuple[dict[str, dict[str, Any]], dict[str, artefacts.Export], str]:
    associations.check(association)
    envelope = association["envelope"]
    dataset, tooling = envelope["dataset"], envelope["tooling"]
    descriptors.check(descriptor)
    require(document_sha256(descriptor) == dataset["descriptorSha256"], f"{CODE}:descriptor_mismatch")
    rows = mappings.check_against(mapping, descriptor)
    require(document_sha256(mapping) == tooling["mappingSha256"], f"{CODE}:mapping_mismatch")
    require(requirements_sha256 == tooling["requirementsSha256"], f"{CODE}:requirements_mismatch")
    bound = {item["sequenceId"]: item for item in envelope["sequences"]}
    require(sorted(ground_truth) == sorted(bound), f"{CODE}:ground_truth_sequences")
    for sequence_id, document in ground_truth.items():
        require(isinstance(document, dict) and document.get("sequenceId") == sequence_id
                and document_sha256(document) == bound[sequence_id]["groundTruthSha256"],
                f"{CODE}:ground_truth_mismatch:{sequence_id}")
        gt_module.project(document)
    require(sorted(exports) == envelope["mavi"]["exportSha256s"], f"{CODE}:mavi_export_mismatch")
    source = outcomes.subclass_source(exports, envelope["mavi"]["pipelineProfileSha256"])
    by_run = {export.run_id: export for export in exports.values()}
    for entry in association["sequences"]:
        export = by_run.get(entry["processingRunId"])
        require(export is not None and export.video["videoAssetId"] == entry["videoAssetId"]
                and export.video["sourceSha256"] == bound[entry["sequenceId"]]["derivedVideoSha256"],
                f"{CODE}:sequence_run_mismatch:{entry['sequenceId']}")
    return rows, by_run, source


# Scope A


def _gt_states(entry: dict[str, Any]) -> dict[str, str]:
    states = {pair["gtTrackId"]: "assigned" for pair in entry["pairs"]}
    for key, state in GT_STATE.items():
        states.update({item["gtTrackId"]: state for item in entry[key]})
    return states


def _mavi_states(entry: dict[str, Any]) -> dict[str, str]:
    states = {pair["maviTrackId"]: "assigned" for pair in entry["pairs"]}
    for key, state in MAVI_STATE.items():
        states.update({item["maviTrackId"]: state for item in entry[key]})
    return states


def _gt_counts(states: list[str]) -> dict[str, int]:
    counts = Counter(states)
    result = {"total": len(states), "assigned": counts["assigned"]}
    result.update({state: counts[state] for state in GT_STATE.values()})
    require(sum(result[key] for key in result if key != "total") == result["total"], f"{CODE}:accounting")
    return result


def _mavi_counts(states: list[str]) -> dict[str, int]:
    counts = Counter(states)
    result = {"total": len(states), "assigned": counts["assigned"]}
    result.update({state: counts[state] for state in MAVI_STATE.values()})
    require(sum(result[key] for key in result if key != "total") == result["total"], f"{CODE}:accounting")
    return result


def _population(row: dict[str, Any]) -> str:
    if row["kind"] == "unsupported" and row["unsupportedKind"] == "outside-capability":
        return "outside"
    return "expected"


# Evaluation


def evaluate(*, association: dict[str, Any], descriptor: dict[str, Any], mapping: dict[str, Any],
             ground_truth: dict[str, dict[str, Any]], exports: dict[str, artefacts.Export],
             requirements: dict[str, Any], requirements_sha256: str) -> dict[str, Any]:
    rows, by_run, source = _bind(association, descriptor, mapping, ground_truth, exports, requirements_sha256)
    floor = requirements["minimumSupport"]["evaluablePerClass"]
    native_of: dict[tuple[str, str], str] = {}
    gt_rows: list[tuple[str, str, str]] = []            # (sequence, native class, state) over non-ignored GT
    mavi_rows: list[tuple[str, str]] = []                # (sequence, state)
    assigned: list[tuple[str, dict[str, Any], str]] = []  # (native class, mapping row, MAVI outcome)
    ignored_by_sequence: dict[str, int] = {}
    outside_vehicle: dict[str, int] = {}
    for entry in association["sequences"]:
        sequence = entry["sequenceId"]
        document = ground_truth[sequence]
        for track in document["tracks"]:
            require(track["nativeClass"] in rows, f"{CODE}:native_class_unmapped:{track['nativeClass']}")
            native_of[(sequence, track["gtTrackId"])] = track["nativeClass"]
        states = _gt_states(entry)
        ignored = {item["gtTrackId"] for item in entry["ignoredGt"]}
        require(sorted([*states, *ignored]) == sorted(track["gtTrackId"] for track in document["tracks"])
                and not set(states) & ignored, f"{CODE}:association_gt_mismatch:{sequence}")
        export = by_run[entry["processingRunId"]]
        track_outcome = outcomes.track_outcomes(export, source)
        mavi_states = _mavi_states(entry)
        require(sorted(mavi_states) == sorted(track_outcome), f"{CODE}:association_mavi_mismatch:{sequence}")
        ignored_by_sequence[sequence] = len(ignored)
        outside_vehicle[sequence] = 0
        for gt_id, state in states.items():
            gt_rows.append((sequence, native_of[(sequence, gt_id)], state))
        for pair in entry["pairs"]:
            native = native_of[(sequence, pair["gtTrackId"])]
            assigned.append((native, rows[native], track_outcome[pair["maviTrackId"]]))
            if _population(rows[native]) == "outside":
                outside_vehicle[sequence] += 1
        mavi_rows.extend((sequence, state) for state in mavi_states.values())
    sequences = [entry["sequenceId"] for entry in association["sequences"]]
    scope_a = _scope_a(association, rows, sequences, gt_rows, mavi_rows, ignored_by_sequence, outside_vehicle)
    scope_b = _scope_b(rows, assigned, requirements, floor)
    result = {"schemaVersion": SCHEMA, "envelope": association["envelope"],
              "associationSha256": document_sha256(association),
              "mappingSha256": association["envelope"]["tooling"]["mappingSha256"],
              "requirements": {"gitPath": artefacts.REQUIREMENTS_GIT_PATH, "sha256": requirements_sha256,
                               "supportFloor": floor},
              "scopeA": scope_a, "scopeB": scope_b}
    return check(result, association)


def _scope_a(association, rows, sequences, gt_rows, mavi_rows, ignored_by_sequence, outside_vehicle):
    def gt_states(sequence: str | None, population: str) -> list[str]:
        return [state for seq, native, state in gt_rows if (sequence is None or seq == sequence)
                and _population(rows[native]) == population]

    expected = _gt_counts(gt_states(None, "expected"))
    outside = gt_states(None, "outside")
    mavi = _mavi_counts([state for _, state in mavi_rows])
    limited = expected["ambiguous"] + expected["fragmented"] + expected["merged"] + expected["unverified"]
    rate = fraction(limited, expected["total"])
    per_native = []
    for native in sorted(rows):
        row = rows[native]
        item = {"nativeClass": native, "kind": row["kind"],
                "gt": _gt_counts([state for _, cls, state in gt_rows if cls == native])}
        if row["kind"] == "unsupported":
            item["unsupportedKind"] = row["unsupportedKind"]
        per_native.append(item)
    per_sequence = [{
        "sequenceId": sequence,
        "expectedVehicleGt": _gt_counts(gt_states(sequence, "expected")),
        "outsideCapabilityGt": {"total": len(gt_states(sequence, "outside")),
                                "vehicleTracksOnOutsideCapabilityGt": outside_vehicle[sequence]},
        "ignoredGt": ignored_by_sequence[sequence],
        "maviTracks": _mavi_counts([state for seq, state in mavi_rows if seq == sequence]),
    } for sequence in sequences]
    return {
        "scope": SCOPE_A,
        "expectedVehicleGt": expected,
        "associationRate": fraction(expected["assigned"], expected["total"]),
        "coverageLimitedGtRate": rate,
        "escalationThreshold": rational(ESCALATION_THRESHOLD),
        "coverageLimited": expected["total"] > 0 and Fraction(limited, expected["total"]) > ESCALATION_THRESHOLD,
        "outsideCapabilityGt": {"total": len(outside),
                                "vehicleTracksOnOutsideCapabilityGt": sum(outside_vehicle.values())},
        "ignoredGt": sum(ignored_by_sequence.values()),
        "maviTracks": mavi,
        "maviUnverifiedRate": fraction(mavi["unverified"], mavi["total"]),
        "alignment": association["alignment"],
        "perNativeClass": per_native,
        "sequences": per_sequence,
    }


def _outcome_counts(values: list[str]) -> list[dict[str, Any]]:
    counts = Counter(values)
    return [{"outcome": value, "count": counts[value]} for value in OUTCOMES]


def _scope_b(rows, assigned, requirements, floor):
    def kind(row):
        return row["kind"] if row["kind"] != "unsupported" else row["unsupportedKind"]

    judgeable_natives = sorted(native for native, row in rows.items()
                               if kind(row) in ("exact", "subset", "outside-capability"))
    classes, qualifying = [], []
    for cls in CLASSES:
        has_exact = any(row["kind"] == "exact" and row["maviClass"] == cls for row in rows.values())
        exact = [value for _, row, value in assigned if row["kind"] == "exact" and row["maviClass"] == cls]
        support = len(exact)
        correct = sum(1 for value in exact if value == cls)
        undetermined = sum(1 for value in exact if value == UNDETERMINED)
        predictions = [(row, value) for _, row, value in assigned if value == cls]
        unjudgeable = sum(1 for row, _ in predictions if kind(row) == "vehicle-unresolved")
        judged = [row for row, _ in predictions if kind(row) != "vehicle-unresolved"]
        true_positive = sum(1 for row in judged if kind(row) in ("exact", "subset") and row["maviClass"] == cls)
        among = fraction(true_positive, len(judged))
        if unjudgeable:
            precision = {"status": "not-available", "value": None}
        elif not predictions:
            precision = {"status": "no-judgeable-predictions", "value": None}
        else:
            precision = {"status": "computed", "value": among}
        precision.update(precisionAmongJudgedTracks=among if predictions else None,
                         unjudgeablePredictions=unjudgeable, judgeableNativeClasses=judgeable_natives)
        recall = ({"status": "computed", "value": fraction(correct, support)} if has_exact
                  else {"status": "not-in-dataset", "value": None})
        status: dict[str, str] = {}
        for criterion, observed in (("precision", precision["value"]), ("recall", recall["value"])):
            if not has_exact:
                status[criterion] = "not-in-dataset"
                continue
            minimum = requirements["operational"]["perClass"][cls][criterion]["minimum"]
            status[criterion] = run_subclass_measurement.status(
                minimum, observed or {"numerator": 0, "denominator": 0}, support, floor)
        classes.append({
            "maviClass": cls, "support": support,
            "supportStatus": "adequate" if support >= floor else "insufficient-support",
            "recall": recall, "precision": precision, "requirementStatus": status,
            "undeterminedShare": fraction(undetermined, support),
            "accuracyOverResolved": fraction(correct, support - undetermined),
            "accuracyOverEvaluable": fraction(correct, support),
        })
        if has_exact and support >= floor:
            qualifying.append((cls, Fraction(correct, support), support - undetermined, correct))
    confusion = [{"nativeClass": native, "truth": row["maviClass"], "outcome": value,
                  "count": sum(1 for cls, _, outcome in assigned if cls == native and outcome == value)}
                 for native, row in sorted(rows.items()) if row["kind"] == "exact" for value in OUTCOMES]
    subsets = []
    for native, row in sorted(rows.items()):
        if row["kind"] != "subset":
            continue
        values = [value for cls, _, value in assigned if cls == native]
        subsets.append({"nativeClass": native, "maviClass": row["maviClass"], "assigned": len(values),
                        "resolvedToMapped": fraction(sum(1 for v in values if v == row["maviClass"]), len(values)),
                        "undeterminedShare": fraction(sum(1 for v in values if v == UNDETERMINED), len(values)),
                        "outcomes": _outcome_counts(values)})
    excluded = [{"nativeClass": native, "unsupportedKind": row["unsupportedKind"],
                 "assigned": sum(1 for cls, _, _ in assigned if cls == native),
                 "outcomes": _outcome_counts([value for cls, _, value in assigned if cls == native])}
                for native, row in sorted(rows.items()) if row["kind"] == "unsupported"]
    exact_values = [value for _, row, value in assigned if row["kind"] == "exact"]
    exact_truths = [(row["maviClass"], value) for _, row, value in assigned if row["kind"] == "exact"]
    correct_all = sum(1 for truth, value in exact_truths if truth == value)
    undetermined_all = sum(1 for value in exact_values if value == UNDETERMINED)
    covered = sum(1 for cls in CLASSES if any(r["kind"] == "exact" and r["maviClass"] == cls for r in rows.values()))
    resolved_means = ([Fraction(correct, resolved) for _, _, resolved, correct in qualifying]
                      if qualifying and all(resolved for _, _, resolved, _ in qualifying) else [])
    return {
        "scope": SCOPE_B,
        "classes": classes,
        "confusion": confusion,
        "subsetBlocks": subsets,
        "excluded": excluded,
        "macro": {"classes": [cls for cls, *_ in qualifying],
                  "recall": _mean([recall for _, recall, _, _ in qualifying]),
                  "accuracyOverResolved": _mean(resolved_means)},
        "overall": {"assignedExact": len(exact_values), "correct": correct_all,
                    "resolved": len(exact_values) - undetermined_all, "undetermined": undetermined_all,
                    "accuracyOverEvaluable": fraction(correct_all, len(exact_values)),
                    "accuracyOverResolved": fraction(correct_all, len(exact_values) - undetermined_all),
                    "undeterminedShare": fraction(undetermined_all, len(exact_values))},
        "taxonomyCoverage": "full" if covered == len(CLASSES) else "none" if covered == 0 else "partial",
    }


# The artefact


def check(result: dict[str, Any], association: dict[str, Any] | None = None) -> dict[str, Any]:
    """Schema, canonical rationals, envelope and its bindings; with the association, that it is this run's."""
    validate(result, SCHEMA, CODE)
    require_canonical_rationals(result, CODE)
    envelope = envelopes.check(result["envelope"])
    require(result["mappingSha256"] == envelope["tooling"]["mappingSha256"], f"{CODE}:mapping_mismatch")
    require(result["requirements"]["sha256"] == envelope["tooling"]["requirementsSha256"],
            f"{CODE}:requirements_mismatch")
    if association is not None:
        require(association["envelope"] == envelope, f"{CODE}:association_run_mismatch")
        require(result["associationSha256"] == document_sha256(association), f"{CODE}:association_mismatch")
    return result


def write(result: dict[str, Any], path: Path) -> bytes:
    data = canonical_json(check(result))
    write_once(path, data)
    return data
