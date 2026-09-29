"""Discriminating tests for the S2c.2b-1 quality/statistical contract."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from model_selection.quality_statistics import (
    CONTRACT,
    NORMATIVE_DOC,
    REQUIRED_DOC_SNIPPETS,
    EXPECTED_FROZEN_INVARIANTS,
    QualityStatisticsError,
    read_contract,
    validate_contract,
    validate_repository,
)

REPO = Path(__file__).resolve().parents[3]
CHECK = REPO / "tools" / "qualification" / "quality_statistics_check.py"


def base():
    return read_contract(REPO / CONTRACT)


def refused(code, document):
    with pytest.raises(QualityStatisticsError) as caught:
        validate_contract(document)
    assert str(caught.value) == code


def test_repository_contract_is_valid():
    assert validate_repository(REPO) == [CONTRACT.as_posix(), NORMATIVE_DOC.as_posix()]


def test_cli_validates_repository():
    run = subprocess.run(
        [sys.executable, str(CHECK), "repository", "--repo", str(REPO)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_module_imports_no_network_library():
    source = (REPO / "tools/qualification/model_selection/quality_statistics.py").read_text(encoding="utf-8")
    for name in ("urllib", "http", "socket", "requests"):
        assert f"import {name}" not in source
        assert f"from {name}" not in source


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d["populations"].__setitem__("U", "model-abstained"), "population_semantics"),
        (lambda d: d["metricDenominators"].__setitem__("classification", "A"), "metric_denominators"),
        (
            lambda d: d["metricDenominators"]["unsupportedAssertion"].__setitem__(
                "humanUnscorable", "I"
            ),
            "metric_denominators",
        ),
        (
            lambda d: d["metricDenominators"]["unsupportedAssertion"].__setitem__(
                "invalidSubject", "U"
            ),
            "metric_denominators",
        ),
        (lambda d: d["metricDenominators"].__setitem__("deliveryCoverage", "S"), "metric_denominators"),
        (lambda d: d["partitionAuthority"].__setitem__("calibrationCoefficients", "tuning"), "partition_authority"),
        (lambda d: d["partitionAuthority"].__setitem__("confidenceThreshold", "selection"), "partition_authority"),
        (lambda d: d["partitionAuthority"].__setitem__("candidateComparison", "tuning"), "partition_authority"),
        (lambda d: d["calibration"].__setitem__("evaluationLevel", "crop"), "calibration_not_post_aggregation"),
        (lambda d: d["calibration"].__setitem__("fitPartition", "tuning"), "calibration_fit_not_training"),
        (lambda d: d["calibration"].__setitem__("selectionFitForbidden", False), "selection_calibration_fit_allowed"),
        (lambda d: d["statistics"].__setitem__("unseenSiteTopLevelUnit", "camera"), "unseen_site_unit"),
        (lambda d: d["statistics"].__setitem__("pairedCandidateComparison", False), "comparison_not_paired"),
        (lambda d: d["statistics"].__setitem__("trackCropsStayTogether", False), "track_crops_split"),
        (lambda d: d["statistics"].__setitem__("practicalMarginsRequired", False), "practical_margins_missing"),
        (lambda d: d["statistics"].__setitem__("intervalOverlapMeansTie", True), "interval_overlap_tie"),
        (lambda d: d["statistics"]["allowedOutcomes"].remove("insufficient-evidence"), "comparison_outcomes"),
        (lambda d: d["gates"].__setitem__("unsupportedAssertionAbsoluteBoundRequired", False), "quality_gate_form"),
        (lambda d: d["gates"].__setitem__("usefulRecallOrCoverageFloorRequired", False), "quality_gate_form"),
        (lambda d: d["selectionBoundary"].__setitem__("selectionMayTune", True), "selection_boundary"),
        (lambda d: d["selectionBoundary"].__setitem__("frozenTestMaySelect", True), "selection_boundary"),
        (
            lambda d: d["outcomeSemantics"].__setitem__("executionFailurePopulation", "S"),
            "execution_failure_not_all_assigned",
        ),
        (
            lambda d: d["outcomeSemantics"].__setitem__("insufficientSupportOutcome", "inconclusive"),
            "insufficient_support_not_fail_closed",
        ),
        (
            lambda d: d["outcomeSemantics"].__setitem__("unconditionalRecallIncludesAbstention", False),
            "recall_excludes_abstention",
        ),
        (
            lambda d: d["outcomeSemantics"].__setitem__("coverageMultipliedAgainForRecallSupport", True),
            "recall_support_double_counts_coverage",
        ),
        (
            lambda d: d["outcomeSemantics"].__setitem__(
                "frozenQualificationFailureMaySelectAlternative", True
            ),
            "frozen_test_adaptive_selection",
        ),
        (
            lambda d: d["frozenInvariants"].__setitem__(
                "I01-human-unscorable-is-not-model-abstention", False
            ),
            "frozen_invariants",
        ),
        (
            lambda d: d["frozenInvariants"].__setitem__(
                "I04-track-calibration-is-post-aggregation", False
            ),
            "frozen_invariants",
        ),
        (
            lambda d: d["frozenInvariants"].__setitem__(
                "I08-comparison-is-paired-cluster-aware-and-track-crops-stay-together", False
            ),
            "frozen_invariants",
        ),
        (
            lambda d: d["frozenInvariants"].__setitem__(
                "I13-owner-numerical-targets-are-not-invented-by-b1", False
            ),
            "frozen_invariants",
        ),
        (
            lambda d: d["frozenInvariants"].__setitem__(
                "I14-operational-pareto-fleet-final-ordering-remain-b2-scope", False
            ),
            "frozen_invariants",
        ),
        (lambda d: d["deferredToS2c2b2"].remove("whole-job-cpu-host-gates"), "b2_scope_boundary"),
        (lambda d: d["deferredToS2c2b2"].remove("composition-resource-accounting"), "b2_scope_boundary"),
        (lambda d: d["deferredToS2c2b2"].remove("10k-track-deadline-mechanics"), "b2_scope_boundary"),
        (lambda d: d["deferredToS2c2b2"].remove("pareto-axes"), "b2_scope_boundary"),
    ],
)
def test_critical_invariants_are_fail_closed(mutate, code):
    document = copy.deepcopy(base())
    mutate(document)
    refused(code, document)


def test_unknown_fields_are_refused():
    document = base()
    document["weightedScore"] = {"enabled": True}
    refused("contract_fields", document)


def test_exactly_fourteen_frozen_invariants_are_machine_checked():
    document = base()
    assert document["frozenInvariants"] == EXPECTED_FROZEN_INVARIANTS
    assert len(EXPECTED_FROZEN_INVARIANTS) == 14
    for key in EXPECTED_FROZEN_INVARIANTS:
        mutated = copy.deepcopy(document)
        mutated["frozenInvariants"][key] = False
        refused("frozen_invariants", mutated)


def test_unsupported_assertion_populations_are_separate():
    denominators = base()["metricDenominators"]["unsupportedAssertion"]
    assert denominators == {"humanUnscorable": "U", "invalidSubject": "I"}
    assert denominators["humanUnscorable"] != denominators["invalidSubject"]


def write_minimal_repo(tmp_path, contract_document, normative_text):
    contract_path = tmp_path / CONTRACT
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(__import__("json").dumps(contract_document), encoding="utf-8")
    doc_path = tmp_path / NORMATIVE_DOC
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(normative_text, encoding="utf-8")


@pytest.mark.parametrize("code", sorted(REQUIRED_DOC_SNIPPETS))
def test_normative_b1_clauses_are_repository_checked(tmp_path, code):
    text = (REPO / NORMATIVE_DOC).read_text(encoding="utf-8")
    snippet = REQUIRED_DOC_SNIPPETS[code]
    assert snippet in text
    write_minimal_repo(tmp_path, base(), text.replace(snippet, "WEAKENED", 1))
    with pytest.raises(QualityStatisticsError) as caught:
        validate_repository(tmp_path)
    assert str(caught.value) == code
