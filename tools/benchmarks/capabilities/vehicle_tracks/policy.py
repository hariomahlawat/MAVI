"""The association policy (plan §7.4, §7.6): one bound object, never scattered defaults.

``POLICY_V1`` carries the frozen v1 values, chosen from geometry and synthetic fixtures and never from benchmark
subclass outcomes. Association reads every threshold from the policy object it is given; its canonical SHA-256 is
the envelope's ``tooling.associationPolicySha256``, so a changed policy is a changed run. Two rules belong to the
policy *version* rather than to a field (the contract has no field for them): an unassigned MAVI Track is
``ignoredMavi`` when at least half of its evaluable points lie in ignore boxes, and the coverage-limited escalation
threshold is reported by the evaluator (plan §7.7). Changing either is a new policy version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from typing import Any

from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import (
    S32Error, document_sha256, from_rational, rational, require, require_canonical_rationals)

CODE = "association_policy_invalid"
VERSION = "vehicle-tracks-association-v1"
IGNORED_MAVI_SHARE = Fraction(1, 2)

POLICY_V1: dict[str, Any] = {
    "version": VERSION,
    "alignment": "midpoint-windows-v1",
    "minOverlapFrames": 3,
    "minContainment": rational(Fraction(1, 2)),
    "minGtCoverage": rational(Fraction(1, 2)),
    "minMaviCoverage": rational(Fraction(1, 2)),
    "minSpotCheckIoU": rational(Fraction(3, 10)),
    "ambiguityMargin": rational(Fraction(1, 10)),
    "distanceAmbiguityMargin": rational(Fraction(1, 10)),
    "minConsecutiveContainedFrames": 3,
}


@dataclass(frozen=True, slots=True)
class Policy:
    document: dict[str, Any]
    min_overlap_frames: int
    min_containment: Fraction
    min_gt_coverage: Fraction
    min_mavi_coverage: Fraction
    min_spot_check_iou: Fraction
    ambiguity_margin: Fraction
    distance_ambiguity_margin: Fraction
    min_consecutive_contained_frames: int

    @property
    def sha256(self) -> str:
        return document_sha256(self.document)


@cache
def _validator():
    import jsonschema

    schema = json.loads((artefacts.SCHEMAS / "benchmark-association-v1.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator({**schema["properties"]["policy"], "$defs": schema["$defs"]},
                                           format_checker=jsonschema.FormatChecker())


def load(document: Any) -> Policy:
    """The policy object as association uses it; refusals are ``association_policy_invalid:<where>``."""
    error = next(iter(_validator().iter_errors(document)), None)
    if error is not None:
        raise S32Error(f"{CODE}:schema:{'/'.join(str(part) for part in error.absolute_path)}")
    require_canonical_rationals(document, CODE)
    for name in ("minContainment", "minGtCoverage", "minMaviCoverage", "minSpotCheckIoU"):
        require(from_rational(document[name], CODE) <= 1, f"{CODE}:{name}")
    return Policy(
        document=json.loads(json.dumps(document)),
        min_overlap_frames=document["minOverlapFrames"],
        min_containment=from_rational(document["minContainment"], CODE),
        min_gt_coverage=from_rational(document["minGtCoverage"], CODE),
        min_mavi_coverage=from_rational(document["minMaviCoverage"], CODE),
        min_spot_check_iou=from_rational(document["minSpotCheckIoU"], CODE),
        ambiguity_margin=from_rational(document["ambiguityMargin"], CODE),
        distance_ambiguity_margin=from_rational(document["distanceAmbiguityMargin"], CODE),
        min_consecutive_contained_frames=document["minConsecutiveContainedFrames"],
    )


def v1() -> Policy:
    return load(POLICY_V1)
