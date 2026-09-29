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

REQUIRED_DOC_SNIPPETS = {
    "doc_i01": (
        "**I-QS1.** Classification quality is computed on **S** only. U is never converted "
        "to a class, negative, false positive, false negative or successful abstention."
    ),
    "doc_i02": (
        "**I-QS2.** Model abstention is an outcome on an otherwise scorable/applicable "
        "Track; it is not a ground-truth state."
    ),
    "doc_i03": (
        "**I-QS3.** Execution failure/Unavailable remains in **A** and lowers all-assigned "
        "delivery coverage. It cannot disappear by becoming Unknown."
    ),
    "doc_i04": (
        "**I-QS4.** Unsupported assertions are measured separately on **U** and **I**."
    ),
    "doc_i05": (
        "**I-QS5.** Calibration is evaluated at the Track output **after** the complete "
        "aggregation, quality filtering and abstention procedure."
    ),
    "doc_i06": (
        "**I-QS6.** Selection may compare already-frozen executable configurations but "
        "may not fit or tune them."
    ),
    "doc_i07": (
        "**I-QS7.** Frozen-test evidence cannot tune, rank, replace or rescue a candidate. "
        "A failed/inconclusive frozen qualification does not trigger adaptive evaluation "
        "of alternatives on the same exposed test."
    ),
    "doc_i08": (
        "**I-QS8.** Candidate comparisons are paired on identical evaluation units."
    ),
    "doc_i09": (
        "**I-QS9.** Inferential support requires both attribute/value support and sufficient "
        "independent clusters. Total Track count cannot substitute for cluster support."
    ),
    "doc_i10": (
        "**I-QS10.** Overlapping confidence intervals are not proof of equivalence. A "
        "non-significant degradation is not proof of non-inferiority."
    ),
    "doc_i11": (
        "**I-QS11.** “Insufficient evidence” is preserved as an outcome; it is never "
        "converted into a pass, tie or owner-selected statistical winner."
    ),
    "doc_i12": (
        "If recall is defined unconditionally over all true positives, it already includes "
        "abstention. **Coverage is not multiplied into the denominator a second time.**"
    ),
    "doc_i13": (
        "S2c.2b-1 freezes the *form* of the gates, not owner policy numbers."
    ),
    "doc_i14": "This slice deliberately does **not** freeze:",
    "doc_b2_cpu_host": "- whole-job CPU/host gates;",
    "doc_b2_composition": "- composition resource accounting;",
    "doc_b2_10k": "- the 10k-Track deadline mechanics;",
    "doc_b2_pareto": "- the final Pareto axes;",
    "doc_b2_final_selection": "- the deterministic selection from a non-dominated set;",
    "doc_b2_fleet": "- the 500-camera projection;",
    "doc_b2_msr_ordering": "- final technical ranking representation in the MSR.",
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
    if invariants != EXPECTED_FROZEN_INVARIANTS:
        raise _fail("frozen_invariants")

    if root["deferredToS2c2b2"] != EXPECTED_DEFERRED:
        raise _fail("b2_scope_boundary")


def validate_repository(repo: Path) -> list[str]:
    contract_path = repo / CONTRACT
    validate_contract(read_contract(contract_path))

    doc_path = repo / NORMATIVE_DOC
    try:
        document = doc_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise _fail("normative_doc_unreadable") from exc
    for code, snippet in REQUIRED_DOC_SNIPPETS.items():
        if snippet not in document:
            raise _fail(code)

    return [CONTRACT.as_posix(), NORMATIVE_DOC.as_posix()]
