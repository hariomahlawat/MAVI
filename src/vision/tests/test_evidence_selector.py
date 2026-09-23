"""Evidence selector: per-role online rules, resolution and bounded state (S1–S15)."""

from __future__ import annotations

import dataclasses
import gc
import random
from fractions import Fraction

import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.evidence.encoder import EncodedImage, JpegLadderEncoder
from mavi_vision.evidence.policy import SCORE_SCALE
from mavi_vision.evidence.quality import CandidateQuality, FrameContext, QualityV1Scorer
from mavi_vision.evidence.roles import EvidenceRole, role_cap_bytes
from mavi_vision.evidence.selector import EvidenceSelector
from mavi_vision.tracking.interfaces import TrackCandidate
from mavi_vision.video.reader import DecodedFrame
from tests.profile_fixtures import PRODUCTION_EVIDENCE_POLICY as POLICY

REP = EvidenceRole.REPRESENTATIVE
NEAR = EvidenceRole.NEAR_VIEW
EARLY = EvidenceRole.EARLY_DIVERSE
LATE = EvidenceRole.LATE_DIVERSE
BOX = NormalizedBoundingBox(0.2, 0.2, 0.3, 0.4)


def micro(score: float) -> int:
    return round(score * SCORE_SCALE)


@dataclasses.dataclass
class Spec:
    """What the stub scorer reports for one frame."""

    score: float = 0.5
    area: float = 0.1
    sharpness: float = 0.5
    edge_margin: float = 0.1
    occlusion: float = 0.0
    admissible: dict = dataclasses.field(default_factory=dict)  # role cap -> bool


class StubScorer:
    version = "stub"

    def __init__(self, specs: dict[int, Spec]) -> None:
        self.specs = specs

    def score(self, context: FrameContext, candidate: TrackCandidate) -> CandidateQuality:
        spec = self.specs[context.frame.source_frame_number]
        return CandidateQuality(
            sharpness=spec.sharpness,
            edge_margin=spec.edge_margin,
            area=spec.area,
            occlusion_iou=spec.occlusion,
            quality_micro=micro(spec.score),
            selection_micro=micro(spec.score),
        )


class StubEncoder:
    """Admits unless the frame (read from the crop's pixel value) is refused for that cap."""

    version = "stub"

    def __init__(self, refuse: set[tuple[int, int]] | None = None, size: int = 1000) -> None:
        self.refuse = refuse or set()
        self.size = size
        self.calls: list[tuple[int, int]] = []

    def encode(self, crop: np.ndarray, cap_bytes: int) -> EncodedImage | None:
        frame_number = int(crop[0, 0, 0])
        self.calls.append((frame_number, cap_bytes))
        if (frame_number, cap_bytes) in self.refuse or (frame_number, 0) in self.refuse:
            return None
        return EncodedImage(b"\xff" * self.size, crop.shape[1], crop.shape[0], 85, 0)


def _frame(number: int, offset_ms: int) -> DecodedFrame:
    image = np.full((40, 40, 3), number % 256, dtype=np.uint8)
    return DecodedFrame(source_frame_number=number, offset_ms=offset_ms, image=image)


def _selector(specs, encoder=None, *, track_start_ms: int = 0, policy=POLICY) -> EvidenceSelector:
    return EvidenceSelector(
        policy=policy,
        scorer=StubScorer(specs),
        encoder=encoder or StubEncoder(),
        track_start_ms=track_start_ms,
    )


def _observe(selector: EvidenceSelector, number: int, offset_ms: int, *, box=BOX, confidence=0.9) -> None:
    candidate = TrackCandidate("person-a", ObjectClass.PERSON, confidence, box)
    detection = DetectionCandidate(ObjectClass.PERSON, confidence, box)
    selector.observe(FrameContext(_frame(number, offset_ms), (detection,)), candidate)


def _holder_frame(selector: EvidenceSelector, role: EvidenceRole) -> int | None:
    holder = selector.holder(role)
    return None if holder is None else holder.source_frame_number


def _run(specs: dict[int, Spec], offsets: dict[int, int], **kwargs) -> EvidenceSelector:
    selector = _selector(specs, **kwargs)
    for number in sorted(offsets):
        _observe(selector, number, offsets[number])
    return selector


# Representative -----------------------------------------------------------------


def test_representative_replaces_only_beyond_epsilon() -> None:
    """S1: scores .50, .51, .53 (ε = .02) -> the holder moves only at .53."""
    selector = _selector({0: Spec(0.50), 1: Spec(0.51), 2: Spec(0.53)})
    seen = []
    for number, offset in ((0, 0), (1, 5000), (2, 10000)):
        _observe(selector, number, offset)
        seen.append(_holder_frame(selector, REP))

    assert seen == [0, 0, 2]


@pytest.mark.parametrize(
    ("second", "replaced"),
    [(0.52, False), (0.520001, True), (0.519999, False), (0.50, False)],
)
def test_epsilon_boundary_is_strict_and_exact(second: float, replaced: bool) -> None:
    """S2: equal scores and scores within ε keep the earlier frame; ε itself is not enough."""
    selector = _run({0: Spec(0.50), 1: Spec(second)}, {0: 0, 1: 5000})

    assert _holder_frame(selector, REP) == (1 if replaced else 0)


def test_first_admissible_candidate_is_the_representative() -> None:
    selector = _run({0: Spec(0.1)}, {0: 0})

    holder = selector.holder(REP)
    assert holder is not None and holder.source_frame_number == 0
    assert holder.selection_micro == micro(0.1)


def test_better_candidate_that_fails_encoding_keeps_the_valid_holder() -> None:
    """S12: an unadmissible would-be replacement never costs the Track its holder."""
    rep_cap = role_cap_bytes(REP)
    encoder = StubEncoder(refuse={(1, rep_cap)})
    selector = _selector({0: Spec(0.50), 1: Spec(0.90), 2: Spec(0.95)}, encoder)

    _observe(selector, 0, 0)
    _observe(selector, 1, 5000)
    assert _holder_frame(selector, REP) == 0
    assert selector.stats.unadmissible_by_role[REP] == 1

    _observe(selector, 2, 10000)
    assert _holder_frame(selector, REP) == 2


def test_encodes_only_candidates_that_would_replace_a_holder() -> None:
    encoder = StubEncoder()
    # Far-apart frames of a Track whose later frames score no better and no larger.
    specs = {n: Spec(0.5) for n in range(6)}
    _run(specs, {n: n * 100 for n in range(6)}, encoder=encoder)

    # One Representative encode; none of the equal, near-duplicate later frames
    # can replace any holder, so they are never encoded.
    assert [call for call in encoder.calls if call[1] == role_cap_bytes(REP)] == [(0, role_cap_bytes(REP))]


def test_representative_invariant_holds_against_an_independent_oracle() -> None:
    """The online holder equals the ε-rule folded over admissible qualified candidates.

    Consequently it is always within ε of the best admissible score seen, and it
    never changes to an unadmissible candidate.
    """
    rng = random.Random(20260923)
    rep_cap = role_cap_bytes(REP)
    for trial in range(300):
        count = rng.randint(1, 40)
        specs = {}
        refuse = set()
        admissible_scores: list[tuple[int, int]] = []
        for number in range(count):
            score = rng.choice([rng.random(), 0.5, 0.52, 0.54, 0.51])
            qualified = rng.random() > 0.15
            specs[number] = Spec(score, sharpness=0.5 if qualified else 0.0)
            if rng.random() < 0.3:
                refuse.add((number, rep_cap))
            elif qualified:
                admissible_scores.append((number, micro(score)))
        selector = _selector(specs, StubEncoder(refuse))
        oracle: tuple[int, int] | None = None
        admissible_iter = iter(admissible_scores)
        pending = next(admissible_iter, None)
        for number in range(count):
            _observe(selector, number, number * 700)
            while pending is not None and pending[0] <= number:
                if oracle is None or pending[1] > oracle[1] + POLICY.replace_epsilon_micro:
                    oracle = pending
                pending = next(admissible_iter, None)
            assert _holder_frame(selector, REP) == (None if oracle is None else oracle[0]), trial
            if oracle is not None:
                best = max(score for n, score in admissible_scores if n <= number)
                assert oracle[1] >= best - POLICY.replace_epsilon_micro


# Qualification --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "confidence"),
    [
        (Spec(0.9), 0.49),                      # confidence floor 0.50
        (Spec(0.9, sharpness=0.049), 0.9),      # sharpness floor 0.05
        (Spec(0.9, edge_margin=0.0049), 0.9),   # edge-margin floor 0.005
        (Spec(0.9, occlusion=0.30), 0.9),       # occlusion must be strictly below 0.30
    ],
)
def test_unqualified_frames_never_hold_any_role(spec: Spec, confidence: float) -> None:
    """S3: one axis below its floor is enough to disqualify every role."""
    selector = _selector({0: spec})
    _observe(selector, 0, 0, confidence=confidence)

    assert selector.holders() == ()
    assert selector.resolve() == ()


def test_qualification_thresholds_are_inclusive_floors() -> None:
    selector = _selector({0: Spec(0.9, sharpness=0.05, edge_margin=0.005, occlusion=0.2999)})
    _observe(selector, 0, 0, confidence=0.50)

    assert _holder_frame(selector, REP) == 0


def test_real_scorer_disqualifies_an_occluded_frame() -> None:
    """S4 end to end: an unconfirmed vehicle overlapping the person disqualifies the frame."""
    frame = DecodedFrame(0, 0, np.random.default_rng(2).integers(0, 256, (120, 160, 3), dtype=np.uint8))
    person = NormalizedBoundingBox(0.2, 0.2, 0.3, 0.4)
    vehicle = NormalizedBoundingBox(0.25, 0.2, 0.3, 0.4)
    selector = EvidenceSelector(
        policy=POLICY,
        scorer=QualityV1Scorer(0.0),
        encoder=JpegLadderEncoder(POLICY.encoder),
        track_start_ms=0,
    )
    candidate = TrackCandidate("person-a", ObjectClass.PERSON, 0.9, person)
    selector.observe(
        FrameContext(
            frame,
            (
                DetectionCandidate(ObjectClass.PERSON, 0.9, person, frame_ordinal=0),
                DetectionCandidate(ObjectClass.VEHICLE, 0.3, vehicle, frame_ordinal=1),
            ),
        ),
        candidate,
    )

    assert selector.holders() == ()


# NearView -------------------------------------------------------------------------


def _near_run(areas: list[float]) -> list[int | None]:
    # Frames far apart so no near-duplicate window applies; equal scores keep Rep on 0.
    selector = _selector({n: Spec(0.5, area=a) for n, a in enumerate(areas)})
    seen = []
    for number in range(len(areas)):
        _observe(selector, number, number * 10_000)
        seen.append(_holder_frame(selector, NEAR))
    return seen


def test_near_view_seeds_on_the_first_non_duplicate_and_never_on_the_representative_frame() -> None:
    """S6"""
    assert _near_run([0.25, 0.25]) == [None, 1]


@pytest.mark.parametrize(
    ("second_area", "replaced"),
    [
        (0.3125, False),                                       # exactly holder · 1.25
        (float(Fraction(5, 16) - Fraction(1, 2**56)), False),  # just below
        (0.31250000000000006, True),                           # one ulp above
        (0.5, True),                                           # clearly closer
    ],
)
def test_near_view_grows_by_hysteresis_only(second_area: float, replaced: bool) -> None:
    """S5 at the boundary: areas are compared exactly against holder · (1 + growth)."""
    seen = _near_run([0.9, 0.25, second_area])

    assert seen[-1] == (2 if replaced else 1)


def test_repeated_marginal_improvements_do_not_thrash() -> None:
    seen = _near_run([0.9, 0.100, 0.110, 0.120, 0.124, 0.1251, 0.130, 0.150, 0.157])

    # .1251 beats .100·1.25; afterwards the bar is .1251·1.25 ≈ .156.
    assert seen == [None, 1, 1, 1, 1, 5, 5, 5, 8]


def test_near_view_skips_near_duplicates_of_the_representative() -> None:
    selector = _selector({0: Spec(0.5, area=0.1), 1: Spec(0.5, area=0.5)})
    _observe(selector, 0, 0)
    _observe(selector, 1, 400)  # within the duplicate window and the same box

    assert _holder_frame(selector, NEAR) is None


def test_near_view_ties_keep_the_earlier_frame() -> None:
    assert _near_run([0.9, 0.2, 0.2])[-1] == 1


# EarlyDiverse ------------------------------------------------------------------------


def _early_selector() -> tuple[EvidenceSelector, dict[int, int]]:
    # Rep on frame 0 (score .9, never beaten); NearView seeds on frame 1; the rest
    # have equal areas so NearView never moves.
    specs = {
        0: Spec(0.90, area=0.1), 1: Spec(0.30, area=0.1), 2: Spec(0.40, area=0.1),
        3: Spec(0.60, area=0.1), 4: Spec(0.80, area=0.1),
    }
    offsets = {0: 0, 1: 1100, 2: 2200, 3: 3000, 4: 3001}
    return _selector(specs), offsets


def test_early_diverse_takes_the_best_view_inside_the_window_and_freezes_after_it() -> None:
    """S7"""
    selector, offsets = _early_selector()
    seen = []
    for number in sorted(offsets):
        _observe(selector, number, offsets[number])
        seen.append(_holder_frame(selector, EARLY))

    # 2200 enters, 3000 (on the boundary) replaces it, and 3001 cannot, even though
    # it scores higher.
    assert seen == [None, None, 2, 3, 3]


def test_early_diverse_requires_separation_at_evaluation_time() -> None:
    """S8: a high-scoring frame 500 ms after the Representative is not diverse."""
    selector = _selector({0: Spec(0.9, area=0.1), 1: Spec(0.85, area=0.1)})
    _observe(selector, 0, 0)
    _observe(selector, 1, 500, box=NormalizedBoundingBox(0.5, 0.5, 0.2, 0.2))

    assert _holder_frame(selector, EARLY) is None


def test_early_window_is_anchored_to_track_start_not_frame_zero() -> None:
    selector = _selector(
        {0: Spec(0.9), 1: Spec(0.5), 2: Spec(0.6)}, track_start_ms=60_000
    )
    _observe(selector, 0, 60_000)
    _observe(selector, 1, 61_100)
    _observe(selector, 2, 62_200)

    assert _holder_frame(selector, EARLY) == 2


def test_track_without_an_early_candidate_has_no_early_role() -> None:
    selector = _selector({0: Spec(0.9), 1: Spec(0.5)})
    _observe(selector, 0, 0)
    _observe(selector, 1, 3001)

    assert _holder_frame(selector, EARLY) is None
    assert EARLY not in {r.role for r in selector.resolve()}


# LateDiverse ---------------------------------------------------------------------------


def test_late_diverse_is_a_trailing_view_refreshed_at_the_interval() -> None:
    """S9: candidates every 500 ms; the late holder advances in ≥ 5 s steps."""
    offsets = {n: n * 500 for n in range(41)}  # 0 .. 20000 ms
    selector = _selector({n: Spec(0.5, area=0.1) for n in offsets})
    late_offsets = []
    for number in sorted(offsets):
        _observe(selector, number, offsets[number])
        holder = selector.holder(LATE)
        if holder is not None and (not late_offsets or late_offsets[-1] != holder.offset_ms):
            late_offsets.append(holder.offset_ms)

    # Rep 0, NearView 1000 (first non-duplicate), Early 2000, first Late 3000.
    assert (_holder_frame(selector, REP), _holder_frame(selector, NEAR), _holder_frame(selector, EARLY)) == (0, 2, 4)
    assert late_offsets == [3000, 8000, 13000, 18000]
    assert selector.holder(LATE).offset_ms <= 20000


def test_late_diverse_does_not_refresh_too_soon() -> None:
    specs = {n: Spec(0.5) for n in range(5)}
    selector = _selector(specs)
    _observe(selector, 0, 0)      # Representative
    _observe(selector, 1, 2000)   # NearView (first non-duplicate)
    _observe(selector, 2, 4000)   # first LateDiverse; outside the early window
    assert _holder_frame(selector, LATE) == 2

    _observe(selector, 3, 8999)   # 4999 ms later: too soon
    assert _holder_frame(selector, LATE) == 2
    _observe(selector, 4, 9000)   # exactly one interval later: refreshed
    assert _holder_frame(selector, LATE) == 4


# Cross-role and resolution -------------------------------------------------------------


def test_one_frame_never_takes_two_roles_during_selection() -> None:
    # Every frame is the best for every role at once.
    offsets = {n: n * 1500 for n in range(8)}
    specs = {n: Spec(0.3 + 0.08 * n, area=0.05 * (n + 1)) for n in offsets}
    selector = _run(specs, offsets)

    frames = [holder.source_frame_number for holder in selector.holders()]
    assert len(frames) == len(set(frames))


def test_resolve_omits_duplicates_in_role_order_and_reranks_contiguously() -> None:
    """S10: the Representative moves onto a near-duplicate of NearView."""
    specs = {0: Spec(0.5), 1: Spec(0.5), 2: Spec(0.9), 3: Spec(0.5), 4: Spec(0.5)}
    offsets = {0: 0, 1: 1000, 2: 1300, 3: 2400, 4: 6000}
    selector = _run(specs, offsets)

    assert (_holder_frame(selector, REP), _holder_frame(selector, NEAR)) == (2, 1)
    resolved = selector.resolve()
    assert [(r.rank, r.role, r.evidence.source_frame_number) for r in resolved] == [
        (0, REP, 2),
        (1, EARLY, 3),
        (2, LATE, 4),
    ]


def test_resolve_is_idempotent_and_pure() -> None:
    """S11"""
    specs = {0: Spec(0.5), 1: Spec(0.5), 2: Spec(0.9), 3: Spec(0.5), 4: Spec(0.5)}
    selector = _run(specs, {0: 0, 1: 1000, 2: 1300, 3: 2400, 4: 6000})
    before = selector.holders()

    assert selector.resolve() == selector.resolve()
    assert selector.holders() == before


def test_no_admissible_representative_resolves_to_nothing() -> None:
    """S13: supplementals alone are never an Evidence Set."""
    rep_cap = role_cap_bytes(REP)
    encoder = StubEncoder(refuse={(n, rep_cap) for n in range(4)})
    selector = _run({n: Spec(0.5) for n in range(4)}, {n: n * 2000 for n in range(4)}, encoder=encoder)

    assert selector.holder(REP) is None
    assert selector.holders()  # supplementals were held ...
    assert selector.resolve() == ()  # ... but nothing is kept without a Representative


def test_resolved_order_and_ranks_are_canonical() -> None:
    selector = _run({n: Spec(0.5) for n in range(20)}, {n: n * 600 for n in range(20)})
    resolved = selector.resolve()

    assert [r.rank for r in resolved] == list(range(len(resolved)))
    assert resolved[0].role is REP
    order = [EvidenceRole(r.role) for r in resolved]
    assert order == sorted(order, key=[REP, NEAR, EARLY, LATE].index)
    frames = [r.evidence.source_frame_number for r in resolved]
    assert len(frames) == len(set(frames))


# Bounded state ---------------------------------------------------------------------------


def test_selector_holds_at_most_four_encoded_images_and_no_ndarray() -> None:
    """S15: after every frame, nothing reachable from the selector is a pixel array."""
    encoder = JpegLadderEncoder(POLICY.encoder)
    selector = EvidenceSelector(policy=POLICY, scorer=QualityV1Scorer(0.0), encoder=encoder, track_start_ms=0)
    rng = np.random.default_rng(5)
    for number in range(60):
        frame = DecodedFrame(number, number * 400, rng.integers(0, 256, (96, 128, 3), dtype=np.uint8))
        box = NormalizedBoundingBox(0.1 + (number % 5) * 0.05, 0.2, 0.2 + (number % 7) * 0.02, 0.4)
        candidate = TrackCandidate("person-a", ObjectClass.PERSON, 0.9, box)
        selector.observe(FrameContext(frame, (DetectionCandidate(ObjectClass.PERSON, 0.9, box),)), candidate)
        del frame

        reachable = _reachable(selector)
        assert not any(isinstance(item, np.ndarray) for item in reachable)
        images = [item for item in reachable if isinstance(item, EncodedImage)]
        assert len(images) <= 4
        assert sum(image.size_bytes for image in images) <= 65536 + 3 * 163840


def _reachable(root: object) -> list[object]:
    seen: dict[int, object] = {}
    stack = [root]
    while stack:
        item = stack.pop()
        if id(item) in seen or isinstance(item, (type, int, float, str, bytes)):
            continue
        seen[id(item)] = item
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            stack.extend(getattr(item, f.name) for f in dataclasses.fields(item))
        slots = getattr(type(item), "__slots__", ())
        stack.extend(getattr(item, name) for name in slots if hasattr(item, name))
        stack.extend(gc.get_referents(item))
    return list(seen.values())
