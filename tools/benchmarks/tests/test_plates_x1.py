"""X1 experiment wrapper: the bottom-border exemption changes exactly one scalar, for Vehicles only."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.evidence.quality import CandidateQuality

_PATH = Path(__file__).resolve().parents[1] / "plates" / "x1_run.py"
_SPEC = importlib.util.spec_from_file_location("x1_run", _PATH)
x1_run = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(x1_run)


class _Inner:
    def score(self, context, candidate):
        box = candidate.bounding_box
        margin = min(box.x, box.y, 1.0 - box.x - box.width, 1.0 - box.y - box.height)
        return CandidateQuality(sharpness=0.07, edge_margin=margin, area=box.width * box.height, occlusion_iou=0.0,
                                quality_micro=123, selection_micro=456)


def _candidate(object_class, x, y, w, h):
    return SimpleNamespace(object_class=object_class, bounding_box=NormalizedBoundingBox(x, y, w, h))


def test_vehicle_touching_only_bottom_gets_side_and_top_margin():
    scorer = x1_run.BottomEdgeExemptScorer(_Inner())
    quality = scorer.score(None, _candidate(ObjectClass.VEHICLE, 0.2, 0.5, 0.3, 0.5))
    assert quality.edge_margin == 0.2  # min(left 0.2, top 0.5, right 0.5); bottom (0.0) exempt
    assert (quality.sharpness, quality.area, quality.quality_micro, quality.selection_micro) == (0.07, 0.15, 123, 456)
    assert scorer.changed == 1


def test_side_or_top_contact_is_not_exempt():
    scorer = x1_run.BottomEdgeExemptScorer(_Inner())
    assert scorer.score(None, _candidate(ObjectClass.VEHICLE, 0.6, 0.5, 0.4, 0.5)).edge_margin == 0.0  # right+bottom
    assert scorer.score(None, _candidate(ObjectClass.VEHICLE, 0.0, 0.2, 0.3, 0.3)).edge_margin == 0.0  # left
    assert scorer.changed == 0


def test_person_unchanged():
    scorer = x1_run.BottomEdgeExemptScorer(_Inner())
    assert scorer.score(None, _candidate(ObjectClass.PERSON, 0.2, 0.5, 0.3, 0.5)).edge_margin == 0.0
    assert scorer.changed == 0


def test_processing_run_identity_is_per_arm_and_sequence():
    assert x1_run._job_id("baseline", "s") != x1_run._job_id("candidate", "s")
    assert x1_run._job_id("candidate", "s") == x1_run._job_id("candidate", "s")
