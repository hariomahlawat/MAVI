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
    PROJECTION_BEGIN,
    PROJECTION_END,
    EXPECTED_FROZEN_INVARIANTS,
    EXPECTED_INVARIANT_STATEMENTS,
    EXPECTED_PARTITIONS,
    EXPECTED_PARTITION_STATEMENTS,
    PARTITION_LABELS,
    QualityStatisticsError,
    read_contract,
    render_contract_projection,
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


def write_minimal_repo(tmp_path, contract_document, normative_text):
    contract_path = tmp_path / CONTRACT
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(__import__("json").dumps(contract_document), encoding="utf-8")
    doc_path = tmp_path / NORMATIVE_DOC
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(normative_text, encoding="utf-8")


def test_repository_contract_and_projection_are_valid():
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
    source = (REPO / "tools/qualification/model_selection/quality_statistics.py").read_text(
        encoding="utf-8"
    )
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
        (
            lambda d: d["partitionStatements"].__setitem__(
                "confidenceThreshold", "selection"
            ),
            "partition_statements",
        ),
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
        (lambda d: d["selectionBoundary"].__setitem__("selectionMayTune", 0), "selection_boundary"),
        (lambda d: d["selectionBoundary"].__setitem__("frozenTestMaySelect", 0), "selection_boundary"),
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
            lambda d: d["invariantStatements"].__setitem__(
                "I05-calibration-fit-is-training-only",
                "Calibration fitting may use tuning data.",
            ),
            "invariant_statements",
        ),
        (lambda d: d["deferredToS2c2b2"].remove("whole-job-cpu-host-gates"), "b2_scope_boundary"),
        (lambda d: d["deferredToS2c2b2"].remove("composition-resource-accounting"), "b2_scope_boundary"),
        (lambda d: d["deferredToS2c2b2"].remove("10k-track-deadline-mechanics"), "b2_scope_boundary"),
        (lambda d: d["deferredToS2c2b2"].remove("pareto-axes"), "b2_scope_boundary"),
    ],
)
def test_critical_contract_rules_are_fail_closed(mutate, code):
    document = copy.deepcopy(base())
    mutate(document)
    refused(code, document)


def test_unknown_contract_fields_are_refused():
    document = base()
    document["weightedScore"] = {"enabled": True}
    refused("contract_fields", document)


def test_all_fourteen_invariants_are_contract_owned_and_boolean_guarded():
    document = base()
    assert document["frozenInvariants"] == EXPECTED_FROZEN_INVARIANTS
    assert document["invariantStatements"] == EXPECTED_INVARIANT_STATEMENTS
    assert len(EXPECTED_FROZEN_INVARIANTS) == 14
    assert len(EXPECTED_INVARIANT_STATEMENTS) == 14
    assert set(EXPECTED_FROZEN_INVARIANTS) == set(EXPECTED_INVARIANT_STATEMENTS)
    for key in EXPECTED_FROZEN_INVARIANTS:
        mutated = copy.deepcopy(document)
        mutated["frozenInvariants"][key] = 1
        refused("frozen_invariants", mutated)


def test_all_thirteen_partition_rows_are_contract_owned():
    document = base()
    assert document["partitionAuthority"] == EXPECTED_PARTITIONS
    assert document["partitionStatements"] == EXPECTED_PARTITION_STATEMENTS
    assert len(EXPECTED_PARTITIONS) == 13
    assert set(EXPECTED_PARTITIONS) == set(EXPECTED_PARTITION_STATEMENTS)


def test_unsupported_assertion_populations_are_separate():
    denominators = base()["metricDenominators"]["unsupportedAssertion"]
    assert denominators == {"humanUnscorable": "U", "invalidSubject": "I"}
    assert denominators["humanUnscorable"] != denominators["invalidSubject"]


def test_projection_is_exactly_rendered_from_contract():
    document = base()
    markdown = (REPO / NORMATIVE_DOC).read_text(encoding="utf-8").replace("\r\n", "\n")
    expected = render_contract_projection(document)
    begin = markdown.index(PROJECTION_BEGIN)
    end = markdown.index(PROJECTION_END, begin) + len(PROJECTION_END)
    assert markdown[begin:end] == expected


def test_projection_contains_every_partition_and_invariant_once():
    projection = render_contract_projection(base())
    for key, statement in EXPECTED_PARTITION_STATEMENTS.items():
        row = f"| {PARTITION_LABELS[key]} | {statement} |"
        assert projection.count(row) == 1
    for key, statement in EXPECTED_INVARIANT_STATEMENTS.items():
        assert projection.count(f"`{key}`") == 1
        assert projection.count(statement) == 1


@pytest.mark.parametrize(
    "needle",
    [
        "| confidence threshold | tuning |",
        "`I05-calibration-fit-is-training-only`",
        "training-derived, group-disjoint held-out predictions or predeclared cross-fitting",
    ],
)
def test_projection_tampering_fails_repository_validation(tmp_path, needle):
    document = base()
    markdown = (REPO / NORMATIVE_DOC).read_text(encoding="utf-8")
    assert needle in markdown
    weakened = markdown.replace(needle, needle + " CHANGED", 1)
    write_minimal_repo(tmp_path, document, weakened)
    with pytest.raises(QualityStatisticsError) as caught:
        validate_repository(tmp_path)
    assert str(caught.value) == "contract_projection"


@pytest.mark.parametrize("marker", [PROJECTION_BEGIN, PROJECTION_END])
def test_projection_marker_missing_fails_structure(tmp_path, marker):
    document = base()
    markdown = (REPO / NORMATIVE_DOC).read_text(encoding="utf-8")
    weakened = markdown.replace(marker, "", 1)
    write_minimal_repo(tmp_path, document, weakened)
    with pytest.raises(QualityStatisticsError) as caught:
        validate_repository(tmp_path)
    assert str(caught.value) == "contract_projection_structure"


@pytest.mark.parametrize("marker", [PROJECTION_BEGIN, PROJECTION_END])
def test_projection_marker_duplicate_fails_structure(tmp_path, marker):
    document = base()
    markdown = (REPO / NORMATIVE_DOC).read_text(encoding="utf-8")
    weakened = markdown + "\n" + marker + "\n"
    write_minimal_repo(tmp_path, document, weakened)
    with pytest.raises(QualityStatisticsError) as caught:
        validate_repository(tmp_path)
    assert str(caught.value) == "contract_projection_structure"


def test_arbitrary_narrative_outside_projection_is_not_machine_authority(tmp_path):
    document = base()
    markdown = (REPO / NORMATIVE_DOC).read_text(encoding="utf-8")
    changed = (
        "Narrative note outside the protected projection; non-authoritative for machine checks.\n\n"
        + markdown
    )
    write_minimal_repo(tmp_path, document, changed)
    assert validate_repository(tmp_path) == [CONTRACT.as_posix(), NORMATIVE_DOC.as_posix()]


def test_duplicate_json_member_is_refused(tmp_path):
    contract_text = (REPO / CONTRACT).read_text(encoding="utf-8")
    needle = '"confidenceThreshold": "tuning"'
    assert needle in contract_text
    ambiguous = contract_text.replace(
        needle,
        '"confidenceThreshold": "selection",\n    ' + needle,
        1,
    )
    contract_path = tmp_path / CONTRACT
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(ambiguous, encoding="utf-8")
    doc_path = tmp_path / NORMATIVE_DOC
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text((REPO / NORMATIVE_DOC).read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(QualityStatisticsError) as caught:
        validate_repository(tmp_path)
    assert str(caught.value) == "contract_duplicate_member"


def test_projection_rejects_unicode_line_separator(tmp_path):
    document = base()
    markdown = (REPO / NORMATIVE_DOC).read_text(encoding="utf-8")
    target = PROJECTION_BEGIN + "\n"
    assert target in markdown
    weakened = markdown.replace(target, PROJECTION_BEGIN + "\u2028", 1)
    write_minimal_repo(tmp_path, document, weakened)
    with pytest.raises(QualityStatisticsError) as caught:
        validate_repository(tmp_path)
    assert str(caught.value) == "contract_projection"
