"""Discriminating tests for the S2c.2b-1 quality/statistical contract."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from model_selection.quality_statistics import (
    CONTRACT,
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
    assert validate_repository(REPO) == [CONTRACT.as_posix()]


def test_cli_validates_repository():
    run = subprocess.run(
        [sys.executable, str(CHECK), "repository", "--repo", str(REPO)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_module_imports_no_network_library():
    source = (REPO / "tools/qualification/model_selection/quality_statistics.py").read_text()
    for name in ("urllib", "http", "socket", "requests"):
        assert f"import {name}" not in source
        assert f"from {name}" not in source


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d["populations"].__setitem__("U", "model-abstained"), "population_semantics"),
        (lambda d: d["metricDenominators"].__setitem__("classification", "A"), "metric_denominators"),
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
