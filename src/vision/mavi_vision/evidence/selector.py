"""Online, bounded, per-Track evidence role selection (ADR-013 §4, plan §4.2–§4.3).

One ``EvidenceSelector`` belongs to one live Track. It sees every frame in
which the Track has a candidate, holds at most one *encoded* image per role,
and never keeps pixels: a crop is cut from the frame only to encode a
candidate that would replace a holder, and is dropped immediately.

Representative invariant. The Representative is mandatory for every accepted
Track (ADR-013 §4), so its slot has two tiers, and nothing else keeps state:

- once the Track has had an admissible *qualified* candidate, the holder is the
  ε-rule folded over the admissible qualified candidates in frame order (a
  candidate replaces the holder only by beating it by more than ε);
- before that, the holder is the same ε-rule folded over every admissible
  candidate, and the first admissible qualified candidate displaces it
  unconditionally.

A would-be replacement is encoded first and replaces the holder only if
admissible, so an encoding failure never costs the Track a Representative it
already has. Supplemental roles are filled only by qualified candidates.
(S1.2c deviation E8, proposed ADR-013 §4 amendment: the plan's strict
"qualified-only" Representative fails the whole attempt whenever one Track has
no qualified frame at all -- a subject clipped at the frame edge, a pair
walking together, a low-texture subject -- which common footage produces.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.evidence.encoder import EncodedImage, EvidenceEncoder
from mavi_vision.evidence.policy import EvidencePolicy
from mavi_vision.evidence.quality import (
    CandidateQuality,
    FrameContext,
    QualityScorer,
    box_iou,
)
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole, role_cap_bytes
from mavi_vision.quality.scoring import crop_region
from mavi_vision.tracking.interfaces import TrackCandidate


@dataclass(frozen=True, slots=True)
class SelectedEvidence:
    """A role holder: encoded bytes plus the scalars that identify the view.

    ``qualified`` is False only for a fallback Representative (see the module
    invariant); every supplemental holder is qualified.
    """

    role: EvidenceRole
    offset_ms: int
    source_frame_number: int
    confidence: float
    bounding_box: NormalizedBoundingBox
    area: float
    quality_micro: int
    selection_micro: int
    qualified: bool
    image: EncodedImage


@dataclass(frozen=True, slots=True)
class ResolvedEvidence:
    """A kept role at retirement, with its contiguous rank in role order."""

    rank: int
    evidence: SelectedEvidence

    @property
    def role(self) -> EvidenceRole:
        return self.evidence.role


@dataclass(slots=True)
class SelectorStats:
    """Per-Track counters for telemetry and the parameter note; not on the wire."""

    candidates_seen: int = 0
    candidates_qualified: int = 0
    encode_attempts: int = 0
    unadmissible_by_role: dict[EvidenceRole, int] = field(
        default_factory=lambda: {role: 0 for role in ROLE_ORDER}
    )


class EvidenceSelector:
    __slots__ = (
        "_policy",
        "_scorer",
        "_encoder",
        "_track_start_ms",
        "_holders",
        "stats",
    )

    def __init__(
        self,
        *,
        policy: EvidencePolicy,
        scorer: QualityScorer,
        encoder: EvidenceEncoder,
        track_start_ms: int,
    ) -> None:
        self._policy = policy
        self._scorer = scorer
        self._encoder = encoder
        self._track_start_ms = track_start_ms
        self._holders: list[SelectedEvidence | None] = [None] * len(ROLE_ORDER)
        self.stats = SelectorStats()

    def holder(self, role: EvidenceRole) -> SelectedEvidence | None:
        return self._holders[ROLE_ORDER.index(role)]

    def holders(self) -> tuple[SelectedEvidence, ...]:
        return tuple(holder for holder in self._holders if holder is not None)

    # -- per-frame --------------------------------------------------------------

    def observe(self, context: FrameContext, candidate: TrackCandidate) -> None:
        """Evaluate one frame's candidate for every role, in canonical order."""
        self.stats.candidates_seen += 1
        quality = self._scorer.score(context, candidate)
        qualified = self._qualified(candidate, quality)
        policy = self._policy
        frame = context.frame
        view = _View(
            offset_ms=frame.offset_ms,
            source_frame_number=frame.source_frame_number,
            bounding_box=candidate.bounding_box,
        )

        # Representative: a qualified candidate always outranks a fallback
        # holder; within a tier, strict improvement by more than ε. A frame that
        # wins it is the holder the later roles are evaluated against, so one
        # frame can never take two roles.
        representative = self._holders[0]
        if (
            representative is None
            or (qualified and not representative.qualified)
            or (
                qualified == representative.qualified
                and quality.selection_micro
                > representative.selection_micro + policy.replace_epsilon_micro
            )
        ):
            self._try_hold(EvidenceRole.REPRESENTATIVE, context, candidate, quality, qualified)

        if not qualified:
            return
        self.stats.candidates_qualified += 1

        # NearView: a materially larger view, not a near-duplicate of the
        # Representative; growth hysteresis prevents thrashing on small changes.
        representative = self._holders[0]
        near_view = self._holders[1]
        if not self._near_duplicate(view, representative) and (
            near_view is None or self._area_grew(quality.area, near_view.area)
        ):
            self._try_hold(EvidenceRole.NEAR_VIEW, context, candidate, quality, True)

        # EarlyDiverse: best view inside the anchored early window; frozen once
        # the window has closed (it is known online from Track start).
        near_view = self._holders[1]
        if frame.offset_ms - self._track_start_ms <= policy.early_window_ms:
            early = self._holders[2]
            if self._diverse_from(view, (self._holders[0], near_view)) and (
                early is None
                or quality.selection_micro > early.selection_micro + policy.replace_epsilon_micro
            ):
                self._try_hold(EvidenceRole.EARLY_DIVERSE, context, candidate, quality, True)

        # LateDiverse: a trailing view, refreshed at most once per interval.
        late = self._holders[3]
        if (
            late is None or frame.offset_ms - late.offset_ms >= policy.late_refresh_interval_ms
        ) and self._diverse_from(view, (self._holders[0], self._holders[1], self._holders[2])):
            self._try_hold(EvidenceRole.LATE_DIVERSE, context, candidate, quality, True)

    # -- retirement -------------------------------------------------------------

    def resolve(self) -> tuple[ResolvedEvidence, ...]:
        """Kept roles in canonical order with contiguous ranks. Pure; repeatable.

        A supplemental holder is dropped if it is a near-duplicate of, or not
        separated from, a role already kept (NearView is exempt only from the
        separation test against the Representative). An empty result means the
        Track never had an admissible qualified Representative.
        """
        kept: list[SelectedEvidence] = []
        for holder in self._holders:
            if holder is None:
                continue
            if holder.role is not EvidenceRole.REPRESENTATIVE:
                if not kept:
                    # No Representative: nothing is kept (the caller fails).
                    return ()
                view = _View.of(holder)
                if any(
                    self._near_duplicate(view, earlier)
                    or (
                        not self._separated(view, earlier)
                        and not (
                            holder.role is EvidenceRole.NEAR_VIEW
                            and earlier.role is EvidenceRole.REPRESENTATIVE
                        )
                    )
                    for earlier in kept
                ):
                    continue
            kept.append(holder)
        return tuple(ResolvedEvidence(rank, evidence) for rank, evidence in enumerate(kept))

    # -- rules --------------------------------------------------------------------

    def _qualified(self, candidate: TrackCandidate, quality: CandidateQuality) -> bool:
        policy = self._policy
        return (
            candidate.confidence >= policy.confidence_floor
            and quality.sharpness >= policy.sharpness_floor
            and quality.edge_margin >= policy.edge_margin_floor
            and quality.occlusion_iou < policy.occlusion_iou_ceiling
        )

    def _area_grew(self, area: float, holder_area: float) -> bool:
        # Exact rational comparison on the float64 values: the boundary itself
        # (area == holder · (1 + growth)) never replaces, on every variant.
        return Fraction(area) > Fraction(holder_area) * (1 + self._policy.near_view_growth)

    def _near_duplicate(self, view: "_View", holder: SelectedEvidence | None) -> bool:
        if holder is None:
            return False
        if view.source_frame_number == holder.source_frame_number:
            return True
        return (
            abs(view.offset_ms - holder.offset_ms) <= self._policy.duplicate_window_ms
            and box_iou(view.bounding_box, holder.bounding_box) >= self._policy.duplicate_iou_threshold
        )

    def _separated(self, view: "_View", holder: SelectedEvidence) -> bool:
        return abs(view.offset_ms - holder.offset_ms) >= self._policy.min_separation_ms

    def _diverse_from(
        self,
        view: "_View",
        holders: tuple[SelectedEvidence | None, ...],
    ) -> bool:
        return all(
            holder is None
            or (self._separated(view, holder) and not self._near_duplicate(view, holder))
            for holder in holders
        )

    def _try_hold(
        self,
        role: EvidenceRole,
        context: FrameContext,
        candidate: TrackCandidate,
        quality: CandidateQuality,
        qualified: bool,
    ) -> None:
        self.stats.encode_attempts += 1
        # The crop is a view of the decoded frame; the encoder copies what it
        # needs and nothing retains either after this call.
        image = self._encoder.encode(
            crop_region(context.frame, candidate.bounding_box),
            role_cap_bytes(role),
        )
        if image is None:
            self.stats.unadmissible_by_role[role] += 1
            return
        self._holders[ROLE_ORDER.index(role)] = SelectedEvidence(
            role=role,
            offset_ms=context.frame.offset_ms,
            source_frame_number=context.frame.source_frame_number,
            confidence=candidate.confidence,
            bounding_box=candidate.bounding_box,
            area=quality.area,
            quality_micro=quality.quality_micro,
            selection_micro=quality.selection_micro,
            qualified=qualified,
            image=image,
        )


@dataclass(frozen=True, slots=True)
class _View:
    offset_ms: int
    source_frame_number: int
    bounding_box: NormalizedBoundingBox

    @staticmethod
    def of(holder: SelectedEvidence) -> "_View":
        return _View(holder.offset_ms, holder.source_frame_number, holder.bounding_box)
