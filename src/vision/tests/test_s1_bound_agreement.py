"""S1.4 B3 (plan §7): worker bounds agree with the platform's enforced bounds.

The worker's caps come from the pipeline profile, its own role constants, and
the completion model's validation constants. The platform's come from
``WorkerContractRules.cs``. Every pair is checked here from the worker side;
``S1BoundAgreementTests`` checks the profile against the platform constants from
the .NET side.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mavi_vision.common import control_plane
from mavi_vision.common.analytical import MAXIMUM_TRACKS_PER_RESULT
from mavi_vision.evidence import roles
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole, role_cap_bytes

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs"
PROFILE = ROOT / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"


def _platform_constants() -> dict[str, int]:
    """Integer constants of ``WorkerContractRules``, evaluated from their products."""
    constants: dict[str, int] = {}
    pattern = re.compile(r"public const (?:int|long) (\w+) = ([0-9_L *]+);")
    for name, expression in pattern.findall(RULES.read_text(encoding="utf-8")):
        value = 1
        for factor in expression.replace("L", "").replace("_", "").split("*"):
            value *= int(factor.strip())
        constants[name] = value
    return constants


PLATFORM = _platform_constants()


def test_the_platform_constants_are_read_not_defaulted() -> None:
    for name in (
        "MaximumCompletionTracks",
        "MaximumTrackObservations",
        "MaximumRepresentativeCropBytes",
        "MaximumSupplementalCropBytes",
        "MaximumCompletionEvidenceCropBytes",
        "MaximumCompletionEvidenceBytes",
        "MaximumCompletionArtifactBytes",
        "MaximumCompletionRequestBodyBytes",
    ):
        assert PLATFORM.get(name, 0) > 0, name


@pytest.mark.parametrize(
    ("worker", "platform"),
    [
        (MAXIMUM_TRACKS_PER_RESULT, "MaximumCompletionTracks"),
        (len(ROLE_ORDER), "MaximumTrackObservations"),
        (roles.REPRESENTATIVE_CAP_BYTES, "MaximumRepresentativeCropBytes"),
        (roles.SUPPLEMENTAL_CAP_BYTES, "MaximumSupplementalCropBytes"),
        (roles.RUN_EVIDENCE_CROP_QUOTA_BYTES, "MaximumCompletionEvidenceCropBytes"),
        (control_plane._REPRESENTATIVE_CROP_MAX_BYTES, "MaximumRepresentativeCropBytes"),
        (control_plane._SUPPLEMENTAL_CROP_MAX_BYTES, "MaximumSupplementalCropBytes"),
        (control_plane._COMPLETION_EVIDENCE_CROP_MAX_BYTES, "MaximumCompletionEvidenceCropBytes"),
        (control_plane._COMPLETION_EVIDENCE_MAX_BYTES, "MaximumCompletionEvidenceBytes"),
        (control_plane._COMPLETION_ARTIFACT_MAX_BYTES, "MaximumCompletionArtifactBytes"),
    ],
)
def test_worker_bound_equals_platform_bound(worker: int, platform: str) -> None:
    assert worker == PLATFORM[platform]


def test_profile_caps_and_quota_equal_the_platform_bounds() -> None:
    evidence = json.loads(PROFILE.read_text(encoding="utf-8"))["evidence"]
    assert evidence["encoder"]["representativeCapBytes"] == PLATFORM["MaximumRepresentativeCropBytes"]
    assert evidence["encoder"]["supplementalCapBytes"] == PLATFORM["MaximumSupplementalCropBytes"]
    assert evidence["runEvidenceCropQuotaBytes"] == PLATFORM["MaximumCompletionEvidenceCropBytes"]


def test_each_role_cap_is_the_platform_cap_for_that_role() -> None:
    for role in ROLE_ORDER:
        expected = (
            PLATFORM["MaximumRepresentativeCropBytes"]
            if role is EvidenceRole.REPRESENTATIVE
            else PLATFORM["MaximumSupplementalCropBytes"]
        )
        assert role_cap_bytes(role) == expected, role
