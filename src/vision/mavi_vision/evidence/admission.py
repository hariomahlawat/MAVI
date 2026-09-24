"""Run-level EvidenceCrop admission under the 1 GiB quota (ADR-013 §6, plan §6.2).

A pure function over the descriptor-only finalised Tracks. Every Representative
is mandatory and admitted first; supplemental roles are then admitted in rounds
(NearView, EarlyDiverse, LateDiverse), each ordered by selection score
descending, then Track id ascending (ordinal; equal to the platform's
LocalTrackNumber order). A candidate that does not fit the remaining budget is
omitted and the round continues, so a smaller later candidate can still be
admitted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from mavi_vision.common.analytical import (
    EvidenceAccounting,
    ObservationDescriptor,
    ProcessedTrack,
    RoleAccounting,
)
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.roles import ROLE_ORDER, SUPPLEMENTAL_ROLES, EvidenceRole


@dataclass(frozen=True, slots=True)
class OmittedEvidence:
    track_id: str
    observation: ObservationDescriptor


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """Tracks keeping only admitted observations (re-ranked 0..n−1), the omitted
    observations whose staged crops must be removed, and the exact accounting."""

    tracks: tuple[ProcessedTrack, ...]
    omitted: tuple[OmittedEvidence, ...]
    accounting: EvidenceAccounting


def admit(tracks: Sequence[ProcessedTrack], quota_bytes: int) -> AdmissionResult:
    if isinstance(quota_bytes, bool) or not isinstance(quota_bytes, int) or quota_bytes < 0:
        raise EvidenceError("evidence_quota_invalid")
    ordered = tuple(sorted(tracks, key=lambda track: track.track_id))

    total = 0
    for track in ordered:
        representative = track.observations[0]
        if representative.role is not EvidenceRole.REPRESENTATIVE:
            raise EvidenceError("evidence_representative_missing")
        total += representative.crop.size_bytes
    if total > quota_bytes:
        # Representatives are never omitted for an accepted Track; if they alone
        # exceed the quota the run cannot be represented and fails closed.
        raise EvidenceError("evidence_quota_exceeded")

    admitted_roles: dict[str, set[EvidenceRole]] = {
        track.track_id: {EvidenceRole.REPRESENTATIVE} for track in ordered
    }
    omitted: list[OmittedEvidence] = []
    for role in SUPPLEMENTAL_ROLES:
        round_candidates = sorted(
            (
                (observation, track.track_id)
                for track in ordered
                for observation in track.observations
                if observation.role is role
            ),
            key=lambda item: (-item[0].selection_micro, item[1]),
        )
        for observation, track_id in round_candidates:
            size = observation.crop.size_bytes
            if total + size <= quota_bytes:
                total += size
                admitted_roles[track_id].add(role)
            else:
                omitted.append(OmittedEvidence(track_id, observation))

    kept_tracks = tuple(_keep(track, admitted_roles[track.track_id]) for track in ordered)
    return AdmissionResult(
        tracks=kept_tracks,
        omitted=tuple(omitted),
        accounting=_accounting(ordered, kept_tracks),
    )


def _keep(track: ProcessedTrack, roles: set[EvidenceRole]) -> ProcessedTrack:
    kept = [observation for observation in track.observations if observation.role in roles]
    if len(kept) == len(track.observations):
        return track
    return replace(
        track,
        observations=tuple(
            replace(observation, rank=rank) for rank, observation in enumerate(kept)
        ),
    )


def _accounting(
    candidates: Sequence[ProcessedTrack],
    admitted: Sequence[ProcessedTrack],
) -> EvidenceAccounting:
    by_role: dict[EvidenceRole, RoleAccounting] = {}
    for role in ROLE_ORDER:
        candidate_sizes = [
            observation.crop.size_bytes
            for track in candidates
            for observation in track.observations
            if observation.role is role
        ]
        admitted_sizes = [
            observation.crop.size_bytes
            for track in admitted
            for observation in track.observations
            if observation.role is role
        ]
        by_role[role] = RoleAccounting(
            candidates=len(candidate_sizes),
            admitted=len(admitted_sizes),
            omitted=len(candidate_sizes) - len(admitted_sizes),
            candidate_bytes=sum(candidate_sizes),
            admitted_bytes=sum(admitted_sizes),
        )
    return EvidenceAccounting.of(by_role)
