"""Machine checks for the S2c.2b-1 quality/statistical method contract.

Normative text:
    docs/qualification/model-selection/s2c-quality-statistics.md

This module validates only the method contract. It does not score candidates, read
imagery or define the S2c.2b-2 operational/Pareto decision rule.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "mavi-s2c-quality-statistics-v1"
METHOD = "s2c-2b1"
CONTRACT = Path("docs/qualification/model-selection/s2c-quality-statistics-contract.json")
NORMATIVE_DOC = Path("docs/qualification/model-selection/s2c-quality-statistics.md")

EXPECTED_POPULATIONS = {
    "S": "human-scorable",
    "U": "human-unscorable",
    "I": "invalid-subject",
    "A": "all-assigned",
}
EXPECTED_DENOMINATORS = {
    "classification": "S",
    "unsupportedAssertion": {
        "humanUnscorable": "U",
        "invalidSubject": "I",
    },
    "deliveryCoverage": "A",
}
EXPECTED_PARTITIONS = {
    "modelWeights": "training",
    "taskHeads": "training",
    "calibrationCoefficients": "training",
    "calibrationMethodChoice": "training-internal-validation",
    "confidenceThreshold": "tuning",
    "presenceThreshold": "tuning",
    "colourMargin": "tuning",
    "admissibilityThreshold": "tuning",
    "cropEvidenceFloor": "tuning",
    "poolingParameters": "tuning",
    "aggregationParameters": "tuning",
    "candidateComparison": "selection",
    "finalQualification": "frozen-test",
}
EXPECTED_OUTCOMES = [
    "superior",
    "non-inferior",
    "equivalent",
    "inconclusive",
    "insufficient-evidence",
]
EXPECTED_OUTCOME_SEMANTICS = {
    "executionFailurePopulation": "A",
    "insufficientSupportOutcome": "insufficient-evidence",
    "unconditionalRecallIncludesAbstention": True,
    "coverageMultipliedAgainForRecallSupport": False,
    "frozenQualificationFailureMaySelectAlternative": False,
}
EXPECTED_FROZEN_INVARIANTS = {
    "I01-human-unscorable-is-not-model-abstention": True,
    "I02-classification-uses-S-and-U-I-unsupported-assertions-are-separate": True,
    "I03-execution-failures-remain-in-A": True,
    "I04-track-calibration-is-post-aggregation": True,
    "I05-calibration-fit-is-training-only": True,
    "I06-tuning-selects-operating-parameters-selection-does-not-tune": True,
    "I07-frozen-test-cannot-select-or-rescue-alternative": True,
    "I08-comparison-is-paired-cluster-aware-and-track-crops-stay-together": True,
    "I09-practical-noninferiority-equivalence-margins-are-predeclared": True,
    "I10-interval-overlap-is-not-equivalence": True,
    "I11-insufficient-support-remains-insufficient-evidence": True,
    "I12-unconditional-recall-includes-abstention-and-coverage-is-not-multiplied-twice": True,
    "I13-owner-numerical-targets-are-not-invented-by-b1": True,
    "I14-operational-pareto-fleet-final-ordering-remain-b2-scope": True,
}
EXPECTED_DEFERRED = [
    "operational-performance",
    "whole-job-cpu-host-gates",
    "composition-resource-accounting",
    "10k-track-deadline-mechanics",
    "pareto-axes",
    "final-technical-selection",
    "500-camera-projection",
]

EXPECTED_NORMATIVE_INVARIANTS = {
    "INV-B1-01": "Human-unscorable ground truth is not model abstention.",
    "INV-B1-02": (
        "Classification quality uses human-scorable truth; unsupported assertions on U "
        "and I are measured separately."
    ),
    "INV-B1-03": "All-assigned delivery retains execution failures.",
    "INV-B1-04": "Track calibration is evaluated after aggregation and abstention.",
    "INV-B1-05": (
        "Calibration fitting uses training-derived predictions only; tuning, selection "
        "and frozen-test data cannot fit calibration coefficients."
    ),
    "INV-B1-06": (
        "Tuning chooses operating parameters; selection compares frozen configurations "
        "and performs no fitting or tuning."
    ),
    "INV-B1-07": (
        "Frozen-test evidence cannot tune, rank, replace or rescue a candidate, and a "
        "failed or inconclusive frozen qualification cannot trigger adaptive alternative "
        "selection on the same exposed test."
    ),
    "INV-B1-08": (
        "Candidate comparison is paired and cluster-aware, and every Track's crops stay together."
    ),
    "INV-B1-09": (
        "Practical-difference, non-inferiority and equivalence margins are predeclared before selection."
    ),
    "INV-B1-10": (
        "Interval overlap is not equivalence, and non-significance is not non-inferiority."
    ),
    "INV-B1-11": (
        "Insufficient attribute/value support or independent-cluster support remains "
        "insufficient evidence and cannot become a pass, tie or statistical winner."
    ),
    "INV-B1-12": (
        "Unconditional recall already includes abstention, so coverage is not multiplied "
        "into recall-support arithmetic a second time."
    ),
    "INV-B1-13": (
        "S2c.2b-1 does not invent owner numerical quality targets; it freezes only the "
        "form and authority of those gates."
    ),
    "INV-B1-14": (
        "Whole-job CPU/host gates, composition resource accounting, 10k-Track deadline "
        "mechanics, 500-camera projection, Pareto axes and deterministic final technical "
        "ordering remain S2c.2b-2 scope."
    ),
}
EXPECTED_EXACT_DOC_LINES = {
    "calibration_partition_row": (
        "| calibration coefficients | training-derived, group-disjoint held-out predictions "
        "or predeclared cross-fitting |"
    ),
    "calibration_training_clause": (
        "R1 remains literal: calibration **fitting** belongs to training. R2’s "
        "“calibration checks” on tuning do not authorise fitting there."
    ),
}
class QualityStatisticsError(ValueError):
    """Stable refusal code for a quality/statistics contract violation."""


def _fail(code: str) -> QualityStatisticsError:
    return QualityStatisticsError(code)


def _object(value: object, keys: set[str], code: str) -> dict:
    if not isinstance(value, dict):
        raise _fail(f"{code}_not_object")
    if set(value) != keys:
        raise _fail(f"{code}_fields")
    return value


def read_contract(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("contract_unreadable") from exc
    if not isinstance(value, dict):
        raise _fail("contract_not_object")
    return value


def validate_contract(document: dict) -> None:
    root = _object(
        document,
        {
            "schema",
            "method",
            "populations",
            "metricDenominators",
            "partitionAuthority",
            "calibration",
            "statistics",
            "gates",
            "selectionBoundary",
            "outcomeSemantics",
            "frozenInvariants",
            "deferredToS2c2b2",
        },
        "contract",
    )
    if root["schema"] != SCHEMA:
        raise _fail("schema")
    if root["method"] != METHOD:
        raise _fail("method")

    populations = _object(root["populations"], set(EXPECTED_POPULATIONS), "populations")
    if populations != EXPECTED_POPULATIONS:
        raise _fail("population_semantics")

    denominators = _object(
        root["metricDenominators"], set(EXPECTED_DENOMINATORS), "metric_denominators"
    )
    if denominators != EXPECTED_DENOMINATORS:
        raise _fail("metric_denominators")

    authority = _object(root["partitionAuthority"], set(EXPECTED_PARTITIONS), "partition_authority")
    if authority != EXPECTED_PARTITIONS:
        raise _fail("partition_authority")

    calibration = _object(
        root["calibration"],
        {"evaluationLevel", "fitPartition", "selectionFitForbidden", "frozenTestFitForbidden"},
        "calibration",
    )
    if calibration["evaluationLevel"] != "track-after-aggregation":
        raise _fail("calibration_not_post_aggregation")
    if calibration["fitPartition"] != "training":
        raise _fail("calibration_fit_not_training")
    if calibration["selectionFitForbidden"] is not True:
        raise _fail("selection_calibration_fit_allowed")
    if calibration["frozenTestFitForbidden"] is not True:
        raise _fail("frozen_test_calibration_fit_allowed")

    statistics = _object(
        root["statistics"],
        {
            "unseenSiteTopLevelUnit",
            "pairedCandidateComparison",
            "trackCropsStayTogether",
            "practicalMarginsRequired",
            "intervalOverlapMeansTie",
            "allowedOutcomes",
        },
        "statistics",
    )
    if statistics["unseenSiteTopLevelUnit"] != "site":
        raise _fail("unseen_site_unit")
    if statistics["pairedCandidateComparison"] is not True:
        raise _fail("comparison_not_paired")
    if statistics["trackCropsStayTogether"] is not True:
        raise _fail("track_crops_split")
    if statistics["practicalMarginsRequired"] is not True:
        raise _fail("practical_margins_missing")
    if statistics["intervalOverlapMeansTie"] is not False:
        raise _fail("interval_overlap_tie")
    if statistics["allowedOutcomes"] != EXPECTED_OUTCOMES:
        raise _fail("comparison_outcomes")

    gates = _object(
        root["gates"],
        {
            "ownerTargetsFrozenBeforeSelection",
            "confidenceBoundsRequired",
            "unsupportedAssertionAbsoluteBoundRequired",
            "usefulRecallOrCoverageFloorRequired",
        },
        "gates",
    )
    if any(value is not True for value in gates.values()):
        raise _fail("quality_gate_form")

    boundary = _object(
        root["selectionBoundary"], {"selectionMayTune", "frozenTestMaySelect"}, "selection_boundary"
    )
    if boundary != {"selectionMayTune": False, "frozenTestMaySelect": False}:
        raise _fail("selection_boundary")

    outcomes = _object(
        root["outcomeSemantics"], set(EXPECTED_OUTCOME_SEMANTICS), "outcome_semantics"
    )
    if outcomes["executionFailurePopulation"] != "A":
        raise _fail("execution_failure_not_all_assigned")
    if outcomes["insufficientSupportOutcome"] != "insufficient-evidence":
        raise _fail("insufficient_support_not_fail_closed")
    if outcomes["unconditionalRecallIncludesAbstention"] is not True:
        raise _fail("recall_excludes_abstention")
    if outcomes["coverageMultipliedAgainForRecallSupport"] is not False:
        raise _fail("recall_support_double_counts_coverage")
    if outcomes["frozenQualificationFailureMaySelectAlternative"] is not False:
        raise _fail("frozen_test_adaptive_selection")

    invariants = _object(
        root["frozenInvariants"], set(EXPECTED_FROZEN_INVARIANTS), "frozen_invariants"
    )
    if set(invariants) != set(EXPECTED_FROZEN_INVARIANTS):
        raise _fail("frozen_invariants")
    for key in EXPECTED_FROZEN_INVARIANTS:
        if invariants[key] is not True:
            raise _fail("frozen_invariants")

    if root["deferredToS2c2b2"] != EXPECTED_DEFERRED:
        raise _fail("b2_scope_boundary")


def _parse_normative_invariant_registry(document: str) -> dict[str, str]:
    found: dict[str, str] = {}
    prefix = "**INV-B1-"
    for raw_line in document.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        if ":** " not in line:
            raise _fail("normative_invariant_format")
        tag, text = line.split(":** ", 1)
        tag = tag.removeprefix("**")
        text = text.removesuffix("  ").strip()
        if tag in found:
            raise _fail("normative_invariant_duplicate")
        found[tag] = text
    return found


def _require_exact_line(document: str, expected: str, code: str) -> None:
    matches = [line.strip() for line in document.splitlines() if line.strip() == expected]
    if len(matches) != 1:
        raise _fail(code)


def validate_repository(repo: Path) -> list[str]:
    contract_path = repo / CONTRACT
    validate_contract(read_contract(contract_path))

    doc_path = repo / NORMATIVE_DOC
    try:
        document = doc_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise _fail("normative_doc_unreadable") from exc
    registry = _parse_normative_invariant_registry(document)
    if registry != EXPECTED_NORMATIVE_INVARIANTS:
        raise _fail("normative_invariants")
    if len(registry) != 14:
        raise _fail("normative_invariants")

    for code, expected in EXPECTED_EXACT_DOC_LINES.items():
        _require_exact_line(document, expected, code)

    return [CONTRACT.as_posix(), NORMATIVE_DOC.as_posix()]
