"""Machine checks for the S2c.2b-1 quality/statistical method contract.

The JSON contract is the canonical machine authority. The Markdown protocol contains
one deterministic projection of contract-owned invariant and partition statements.
Repository validation compares that protected projection byte-for-byte; it does not
attempt to interpret arbitrary Markdown semantics.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "mavi-s2c-quality-statistics-v1"
METHOD = "s2c-2b1"
CONTRACT = Path("docs/qualification/model-selection/s2c-quality-statistics-contract.json")
NORMATIVE_DOC = Path("docs/qualification/model-selection/s2c-quality-statistics.md")

PROJECTION_BEGIN = "<!-- BEGIN S2C_B1_CONTRACT_PROJECTION -->"
PROJECTION_END = "<!-- END S2C_B1_CONTRACT_PROJECTION -->"
PROJECTION_BEGIN_BYTES = PROJECTION_BEGIN.encode("utf-8")
PROJECTION_END_BYTES = PROJECTION_END.encode("utf-8")

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
EXPECTED_PARTITION_STATEMENTS = {
    "modelWeights": "training",
    "taskHeads": "training",
    "calibrationCoefficients": (
        "training-derived, group-disjoint held-out predictions or predeclared cross-fitting"
    ),
    "calibrationMethodChoice": "training-internal validation",
    "confidenceThreshold": "tuning",
    "presenceThreshold": "tuning",
    "colourMargin": "tuning",
    "admissibilityThreshold": "tuning",
    "cropEvidenceFloor": "tuning",
    "poolingParameters": "tuning, within the family frozen before candidate execution",
    "aggregationParameters": "tuning, within the family frozen before candidate execution",
    "candidateComparison": "selection",
    "finalQualification": "frozen test",
}
PARTITION_LABELS = {
    "modelWeights": "model weights",
    "taskHeads": "task heads",
    "calibrationCoefficients": "calibration coefficients",
    "calibrationMethodChoice": "choice among predeclared calibration methods",
    "confidenceThreshold": "confidence threshold",
    "presenceThreshold": "presence threshold",
    "colourMargin": "colour margin",
    "admissibilityThreshold": "admissibility threshold",
    "cropEvidenceFloor": "crop evidence floor",
    "poolingParameters": "pooling parameter values",
    "aggregationParameters": "aggregation parameter values",
    "candidateComparison": "candidate comparison",
    "finalQualification": "final qualification",
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
EXPECTED_INVARIANT_STATEMENTS = {
    "I01-human-unscorable-is-not-model-abstention": (
        "Human-unscorable ground truth is not model abstention."
    ),
    "I02-classification-uses-S-and-U-I-unsupported-assertions-are-separate": (
        "Classification quality uses human-scorable truth; unsupported assertions on U "
        "and I are measured separately."
    ),
    "I03-execution-failures-remain-in-A": (
        "All-assigned delivery retains execution failures."
    ),
    "I04-track-calibration-is-post-aggregation": (
        "Track calibration is evaluated after aggregation and abstention."
    ),
    "I05-calibration-fit-is-training-only": (
        "Calibration fitting uses training-derived predictions only; tuning, selection "
        "and frozen-test data cannot fit calibration coefficients."
    ),
    "I06-tuning-selects-operating-parameters-selection-does-not-tune": (
        "Tuning chooses operating parameters; selection compares frozen configurations "
        "and performs no fitting or tuning."
    ),
    "I07-frozen-test-cannot-select-or-rescue-alternative": (
        "Frozen-test evidence cannot tune, rank, replace or rescue a candidate, and a "
        "failed or inconclusive frozen qualification cannot trigger adaptive alternative "
        "selection on the same exposed test."
    ),
    "I08-comparison-is-paired-cluster-aware-and-track-crops-stay-together": (
        "Candidate comparison is paired and cluster-aware, and every Track's crops stay together."
    ),
    "I09-practical-noninferiority-equivalence-margins-are-predeclared": (
        "Practical-difference, non-inferiority and equivalence margins are predeclared before selection."
    ),
    "I10-interval-overlap-is-not-equivalence": (
        "Interval overlap is not equivalence, and non-significance is not non-inferiority."
    ),
    "I11-insufficient-support-remains-insufficient-evidence": (
        "Insufficient attribute/value support or independent-cluster support remains "
        "insufficient evidence and cannot become a pass, tie or statistical winner."
    ),
    "I12-unconditional-recall-includes-abstention-and-coverage-is-not-multiplied-twice": (
        "Unconditional recall already includes abstention, so coverage is not multiplied "
        "into recall-support arithmetic a second time."
    ),
    "I13-owner-numerical-targets-are-not-invented-by-b1": (
        "S2c.2b-1 does not invent owner numerical quality targets; it freezes only the "
        "form and authority of those gates."
    ),
    "I14-operational-pareto-fleet-final-ordering-remain-b2-scope": (
        "Whole-job CPU/host gates, composition resource accounting, 10k-Track deadline "
        "mechanics, 500-camera projection, Pareto axes and deterministic final technical "
        "ordering remain S2c.2b-2 scope."
    ),
}
EXPECTED_FROZEN_INVARIANTS = {key: True for key in EXPECTED_INVARIANT_STATEMENTS}
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


def _reject_duplicate_json_members(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("contract_duplicate_member")
        result[key] = value
    return result


def read_contract(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_members,
        )
    except QualityStatisticsError:
        raise
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
            "partitionStatements",
            "calibration",
            "statistics",
            "gates",
            "selectionBoundary",
            "outcomeSemantics",
            "frozenInvariants",
            "invariantStatements",
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

    partition_statements = _object(
        root["partitionStatements"], set(EXPECTED_PARTITION_STATEMENTS), "partition_statements"
    )
    if partition_statements != EXPECTED_PARTITION_STATEMENTS:
        raise _fail("partition_statements")

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
    if boundary["selectionMayTune"] is not False:
        raise _fail("selection_boundary")
    if boundary["frozenTestMaySelect"] is not False:
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
    for key in EXPECTED_FROZEN_INVARIANTS:
        if invariants[key] is not True:
            raise _fail("frozen_invariants")

    invariant_statements = _object(
        root["invariantStatements"], set(EXPECTED_INVARIANT_STATEMENTS), "invariant_statements"
    )
    if invariant_statements != EXPECTED_INVARIANT_STATEMENTS:
        raise _fail("invariant_statements")

    if root["deferredToS2c2b2"] != EXPECTED_DEFERRED:
        raise _fail("b2_scope_boundary")


def render_contract_projection(document: dict) -> str:
    """Render the only machine-protected Markdown block from the canonical contract."""

    validate_contract(document)
    lines = [
        PROJECTION_BEGIN,
        "_Generated from `s2c-quality-statistics-contract.json`; do not edit this block manually._",
        "",
        "### Partition authority",
        "",
        "| Parameter / decision | Permitted source |",
        "|---|---|",
    ]
    for key in EXPECTED_PARTITIONS:
        lines.append(f"| {PARTITION_LABELS[key]} | {document['partitionStatements'][key]} |")

    lines.extend(["", "### Frozen b-1 invariants", ""])
    for index, key in enumerate(EXPECTED_INVARIANT_STATEMENTS, start=1):
        lines.append(f"{index}. `{key}` — {document['invariantStatements'][key]}")

    lines.extend(["", PROJECTION_END])
    return "\n".join(lines)


def _all_offsets(blob: bytes, needle: bytes) -> list[int]:
    offsets: list[int] = []
    search_from = 0
    while True:
        index = blob.find(needle, search_from)
        if index < 0:
            return offsets
        offsets.append(index)
        search_from = index + len(needle)


def _extract_projection_bytes(document: bytes) -> bytes:
    begin_matches = _all_offsets(document, PROJECTION_BEGIN_BYTES)
    end_matches = _all_offsets(document, PROJECTION_END_BYTES)
    if len(begin_matches) != 1 or len(end_matches) != 1:
        raise _fail("contract_projection_structure")

    begin = begin_matches[0]
    end = end_matches[0]
    if end <= begin:
        raise _fail("contract_projection_structure")
    return document[begin : end + len(PROJECTION_END_BYTES)]


def validate_repository(repo: Path) -> list[str]:
    contract_path = repo / CONTRACT
    contract = read_contract(contract_path)
    validate_contract(contract)

    doc_path = repo / NORMATIVE_DOC
    try:
        document = doc_path.read_bytes()
    except OSError as exc:
        raise _fail("normative_doc_unreadable") from exc

    expected_projection = render_contract_projection(contract).encode("utf-8")
    if _extract_projection_bytes(document) != expected_projection:
        raise _fail("contract_projection")

    return [CONTRACT.as_posix(), NORMATIVE_DOC.as_posix()]
