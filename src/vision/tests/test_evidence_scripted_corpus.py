"""S14: golden selection on the C1 scripted corpus geometry.

The three scripted-corpus scenarios (``tests/fixtures/scene-analytics/
scripted-corpus-v1.json``) are rendered losslessly here, frame by frame, from
the same position model ``scripted_corpus.py`` gives ffmpeg, and fed through the
real scorer, encoder and selector. Rendering in numpy keeps the pinned outcome
independent of any video codec build.

Two variants per scenario:

* ``flat`` — the corpus as drawn: a uniform white box. No frame is sharp
  enough to qualify, so each Track keeps exactly one fallback Representative
  (E8) and no supplemental role. This is what the real corpus videos measure
  too (``docs/qualification/2026-09-24-evidence-selector-parameter-note.md``).
* ``textured`` — the same trajectory with a fixed checkerboard inside the box,
  so frames qualify and every role rule is exercised on corpus motion.

Any change to the scorer, the selector rules or the policy defaults that moves
a role to another frame fails here and must be deliberate.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.evidence.encoder import JpegLadderEncoder
from mavi_vision.evidence.quality import FrameContext, scorer_for_policy
from mavi_vision.evidence.selector import EvidenceSelector
from mavi_vision.tracking.interfaces import TrackCandidate
from mavi_vision.video.reader import DecodedFrame
from tests.profile_fixtures import PRODUCTION_EVIDENCE_POLICY as POLICY


ROOT = Path(__file__).resolve().parents[3]


def _scripted_corpus():
    spec = importlib.util.spec_from_file_location(
        "scripted_corpus", ROOT / "tools" / "vision" / "dev" / "scripted_corpus.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CORPUS = _scripted_corpus()
SPEC = CORPUS.load_spec()
VIDEO = SPEC["video"]
MATTE = 0x20
CHECKER = 8


def _render(centre: tuple[int, int], textured: bool) -> np.ndarray:
    image = np.full((VIDEO["height"], VIDEO["width"], 3), MATTE, dtype=np.uint8)
    cx, cy = centre
    left, top = cx - VIDEO["boxWidth"] // 2, cy - VIDEO["boxHeight"] // 2
    ys, xs = np.mgrid[0 : VIDEO["boxHeight"], 0 : VIDEO["boxWidth"]]
    box = np.full(ys.shape, 255, dtype=np.uint8)
    if textured:
        box = np.where(((ys // CHECKER) + (xs // CHECKER)) % 2 == 0, 255, 96).astype(np.uint8)
    y0, x0 = max(0, top), max(0, left)
    y1 = min(VIDEO["height"], top + VIDEO["boxHeight"])
    x1 = min(VIDEO["width"], left + VIDEO["boxWidth"])
    image[y0:y1, x0:x1] = box[y0 - top : y1 - top, x0 - left : x1 - left, None]
    return image


def _select(scenario_id: str, textured: bool):
    scene = CORPUS.scenario(SPEC, scenario_id)
    boxes = CORPUS.detection_boxes(SPEC, scene)
    first = VIDEO["firstDetectionFrame"]
    fps = VIDEO["fps"]
    selector = EvidenceSelector(
        policy=POLICY,
        scorer=scorer_for_policy(POLICY),
        encoder=JpegLadderEncoder(POLICY.encoder),
        track_start_ms=first * 1000 // fps,
    )
    for number in range(first, VIDEO["lastDetectionFrame"] + 1):
        box = NormalizedBoundingBox(*boxes[number])
        frame = DecodedFrame(number, number * 1000 // fps, _render(CORPUS.centre_at(scene, number), textured))
        detection = DetectionCandidate(ObjectClass.PERSON, 0.9, box)
        selector.observe(
            FrameContext(frame, (detection,)),
            TrackCandidate("person-000001", ObjectClass.PERSON, 0.9, box),
        )
    return selector


# (role, sourceFrameNumber, qualified) per scenario and variant.
GOLDEN = {
    ("line-crossing", False): [("representative", 40, False)],
    ("zone-dwell-exit", False): [("representative", 29, False)],
    ("stationary-then-depart", False): [("representative", 25, False)],
    # The box reaches the top edge at frame 155 (edge margin 0), so only frames
    # 25..154 qualify and LateDiverse cannot refresh after frame 86.
    ("line-crossing", True): [
        ("representative", 32, True),
        ("near-view", 36, True),
        ("early-diverse", 61, True),
        ("late-diverse", 86, True),
    ],
    ("zone-dwell-exit", True): [
        ("representative", 29, True),
        ("near-view", 26, True),
        ("early-diverse", 54, True),
        ("late-diverse", 204, True),
    ],
    ("stationary-then-depart", True): [
        ("representative", 25, True),
        ("near-view", 38, True),
        ("early-diverse", 63, True),
        ("late-diverse", 213, True),
    ],
}

# Encoder calls per Track: bounded by the ε and hysteresis rules, not by length.
ENCODES = {
    ("line-crossing", False): 5,
    ("zone-dwell-exit", False): 3,
    ("stationary-then-depart", False): 1,
    ("line-crossing", True): 7,
    ("zone-dwell-exit", True): 7,
    ("stationary-then-depart", True): 5,
}


@pytest.mark.parametrize(("scenario_id", "textured"), list(GOLDEN), ids=lambda v: str(v))
def test_golden_selection_on_the_scripted_corpus(scenario_id: str, textured: bool) -> None:
    selector = _select(scenario_id, textured)
    resolved = selector.resolve()
    outcome = [(r.role.value, r.evidence.source_frame_number, r.evidence.qualified) for r in resolved]
    assert outcome == GOLDEN[(scenario_id, textured)]
    assert selector.stats.encode_attempts == ENCODES[(scenario_id, textured)]
    assert [r.rank for r in resolved] == list(range(len(resolved)))
