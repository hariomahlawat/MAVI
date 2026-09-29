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

EXPECTED_POPULATIONS = {
    "S": "human-scorable",
    "U": "human-unscorable",
    "I": "invalid-subject",
    "A": "all-assigned",
}
EXPECTED_DENOMINATORS = {
    "classification": "S",
    "unsupportedAssertion": ["U", "I"],
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
EXPECTED_DEFERRED = [
    "operational-performance",
    "whole-job-cpu-host-gates",
    "composition-resource-accounting",
    "10k-track-deadline-mechanics",
    "pareto-axes",
    "final-technical-selection",
    "500-camera-projection",
]


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

    if root["deferredToS2c2b2"] != EXPECTED_DEFERRED:
        raise _fail("b2_scope_boundary")


def validate_repository(repo: Path) -> list[str]:
    path = repo / CONTRACT
    validate_contract(read_contract(path))
    return [CONTRACT.as_posix()]
