"""The deterministic vehicle-subclass benchmark report (S3.2d-1 plan §8, §13)."""

from __future__ import annotations

import copy
import json
import re

import pytest

import eval_fixtures as e
from eval_fixtures import Scenario
from tools.benchmarks.capabilities.vehicle_subclass import report
from tools.benchmarks.core.identity import S32Error, canonical_json

CAR = ("car", "car", "exact", None)
VAN = ("van", None, "unsupported", "vehicle-unresolved")
PED = ("pedestrian", None, "unsupported", "outside-capability")
SEDAN = ("sedan", "car", "subset", None)


@pytest.fixture
def result(tmp_path):
    objects = [{"native": "car", "subclass": "car"}, {"native": "car", "subclass": None},
               {"native": "van", "subclass": "car"}, {"native": "pedestrian", "subclass": "car"},
               {"native": "car", "matched": False}]
    return Scenario(tmp_path, objects, [CAR, VAN, PED]).evaluate()


def test_report_depends_only_on_the_canonical_result(result):
    stored = json.loads(canonical_json(result))  # members re-ordered as the stored JSON orders them
    assert report.render(result) == report.render(stored) == report.render(copy.deepcopy(result))


def test_report_has_every_section_and_names_its_identities(result):
    text = report.render(result).decode("utf-8")
    for heading in ("## Scope A", "## Scope B", "### Exact-class confusion", "### Subset classes",
                    "### Unsupported native classes", "## Limitations"):
        assert heading in text
    assert result["envelope"]["benchmarkRunId"] in text and result["associationSha256"] in text
    assert "Development/reference evidence" in text and "none-known" in text
    assert "not-available" in text  # car predicted on a van
    assert "| car | 2 (insufficient-support)" in text  # support counts assigned exact pairs only
    assert "van (vehicle-unresolved): assigned 1" in text
    assert "Vehicle Tracks assigned to them: 1" in text


def test_report_is_lf_utf8_without_clock_or_unbacked_verdicts(result):
    data = report.render(result)
    assert b"\r" not in data and data.endswith(b"\n")
    text = data.decode("utf-8")
    assert not re.search(r"\d{4}-\d{2}-\d{2}T|\d{2}:\d{2}:\d{2}", text)
    for word in ("excellent", "poor", "passed", "PASS", "FAIL"):
        assert word not in text


@pytest.mark.parametrize("unverified, warned", [(1, False), (2, True)])
def test_coverage_limited_warning_follows_the_result(tmp_path, unverified, warned):
    objects = [{"native": "car", "subclass": "car", **({"observation": (0.0, 0.0, 0.01, 0.01)}
                                                      if index < unverified else {})} for index in range(10)]
    text = report.render(Scenario(tmp_path, objects, [CAR]).evaluate()).decode("utf-8")
    assert ("**Coverage-limited.**" in text) is warned


def test_subset_block_is_reported(tmp_path):
    text = report.render(Scenario(tmp_path, [{"native": "sedan", "subclass": "truck"}], [SEDAN]).evaluate()).decode()
    assert "sedan → car: assigned 1" in text and "(no exact native class)" in text


def test_unsupported_wording_distinguishes_the_two_kinds(result):
    text = report.render(result).decode("utf-8")
    assert "excluded from scoring" not in text
    assert "vehicle-unresolved predictions are unjudgeable" in text
    assert "outside-capability assignments remain judgeable precision negatives" in text
    assert "Neither kind enters exact-class recall or exact confusion" in text


def test_an_invalid_result_is_refused(result):
    broken = copy.deepcopy(result)
    broken["requirements"]["sha256"] = "0" * 64
    with pytest.raises(S32Error, match="^result_invalid:requirements_mismatch$"):
        report.render(broken)
