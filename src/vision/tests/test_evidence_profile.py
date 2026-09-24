"""Pipeline profile 1.1: the evidence section is validated, versioned and bound."""

from __future__ import annotations

import copy
import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest

from mavi_vision.evidence.policy import (
    ENCODER_VERSION,
    PRODUCTION_ENCODER_POLICY,
    SCORER_VERSION,
    SELECTOR_VERSION,
)
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.profile import load_pipeline_profile
from tests.profile_fixtures import PIPELINE_PROFILE_PATH

REPO = Path(__file__).resolve().parents[3]


def _shipped() -> dict:
    return json.loads(PIPELINE_PROFILE_PATH.read_text(encoding="utf-8"))


def _load(tmp_path: Path, payload: dict):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return load_pipeline_profile(path)


def test_shipped_profile_carries_the_versioned_evidence_policy() -> None:
    profile = load_pipeline_profile(PIPELINE_PROFILE_PATH)
    policy = profile.evidence

    assert profile.schema_version == "1.1"
    assert profile.profile_version == "1.2.0-candidate"
    assert (policy.selector_version, policy.scorer_version) == (SELECTOR_VERSION, SCORER_VERSION)
    # The two-tier Representative (ADR-013 §4, amended 2026-09-24) has its own
    # identity: strict and two-tier outcomes never share a selector version.
    assert policy.selector_version == "evidence-selector-v1-two-tier"
    assert policy.encoder == PRODUCTION_ENCODER_POLICY
    assert policy.encoder.encoder_version == ENCODER_VERSION
    assert policy.replace_epsilon_micro == 20_000
    assert policy.near_view_growth == Fraction(1, 4)
    assert (policy.early_window_ms, policy.late_refresh_interval_ms) == (3000, 5000)
    assert (policy.min_separation_ms, policy.duplicate_window_ms) == (1000, 500)
    assert policy.run_evidence_crop_quota_bytes == 1 << 30
    assert policy.confidence_floor <= profile.tracker.track_activation_threshold


def test_qualification_record_binds_the_changed_profile_and_stays_pending() -> None:
    record = json.loads(
        (REPO / "models/qualifications/rtmdet-m-coco-phase1-v1.json").read_text(encoding="utf-8")
    )

    assert record["pipelineProfileSha256"] == hashlib.sha256(PIPELINE_PROFILE_PATH.read_bytes()).hexdigest()
    assert record["overallResult"] == "pending"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("encoder", "maxLongEdgePx"), 2048),
        (("encoder", "initialQuality"), 90),
        (("encoder", "representativeCapBytes"), 65537),
        (("encoder", "supplementalCapBytes"), 200000),
        (("encoder", "floorLongEdgePx"), 64),
        (("encoder", "floorQuality"), 40),
        (("encoder", "ladderScale"), 0.9),
        (("encoder", "ladderQualities"), [85, 70]),
        (("encoder", "floorQualities"), [65, 55]),
        (("encoder", "encoderVersion"), "evidence-jpeg-ladder-v2"),
        (("runEvidenceCropQuotaBytes",), 2 * 1073741824),
        (("selectorVersion",), "evidence-selector-v2"),
        (("selectorVersion",), "evidence-selector-v1"),  # the strict rule's name
        (("scorerVersion",), "quality-v1"),  # the superseded proxy (parameter note F1)
        (("scorerVersion",), "quality-v3"),
        (("replaceEpsilon",), 0.0),
        (("replaceEpsilon",), 0.6),
        (("replaceEpsilon",), 0.0200005),
        (("nearViewGrowth",), 0.0),
        (("nearViewGrowth",), 5.0),
        (("earlyWindowMs",), 0),
        (("lateRefreshIntervalMs",), 3_600_001),
        (("confidenceFloor",), 0.71),
        (("confidenceFloor",), 1.5),
        (("occlusionIouCeiling",), -0.1),
        (("duplicateIouThreshold",), float("nan")),
    ],
)
def test_out_of_bound_or_unversioned_evidence_values_are_refused(
    tmp_path: Path, path: tuple[str, ...], value: object
) -> None:
    payload = _shipped()
    target = payload["evidence"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("mutation", ["missing_section", "extra_field", "schema_1_0", "encoder_extra"])
def test_profile_shape_is_closed(tmp_path: Path, mutation: str) -> None:
    payload = _shipped()
    if mutation == "missing_section":
        del payload["evidence"]
    elif mutation == "extra_field":
        payload["evidence"]["reservoirSize"] = 3
    elif mutation == "schema_1_0":
        payload["schemaVersion"] = "1.0"
    else:
        payload["evidence"]["encoder"]["optimize"] = True

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        _load(tmp_path, payload)


def test_any_parameter_change_changes_the_profile_identity(tmp_path: Path) -> None:
    base = _shipped()
    changed = copy.deepcopy(base)
    changed["evidence"]["lateRefreshIntervalMs"] = 6000

    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8", newline="\n")
    second.write_text(json.dumps(changed, indent=2) + "\n", encoding="utf-8", newline="\n")

    assert load_pipeline_profile(second).evidence.late_refresh_interval_ms == 6000
    assert hashlib.sha256(first.read_bytes()).digest() != hashlib.sha256(second.read_bytes()).digest()
