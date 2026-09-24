"""Run-level evidence admission: order, quota, accounting and re-ranking (A1–A6)."""

from __future__ import annotations

import random
from uuid import UUID

import pytest

from mavi_vision.common.analytical import (
    ArtifactDescriptor,
    NormalizedBoundingBox,
    ObjectClass,
    ObservationDescriptor,
    ProcessedTrack,
    VisionProcessingResult,
)
from mavi_vision.evidence.admission import admit
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole

REP, NEAR, EARLY, LATE = ROLE_ORDER
JOB = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")


def _obs(role: EvidenceRole, rank: int, frame: int, size: int, score: int, track_id: str) -> ObservationDescriptor:
    return ObservationDescriptor(
        role=role,
        rank=rank,
        offset_ms=frame * 100,
        source_frame_number=frame,
        confidence=0.9,
        bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.2),
        quality_micro=score,
        selection_micro=score,
        crop=ArtifactDescriptor(
            storage_key=f"staging/{JOB}/attempt-0001/evidence/{track_id}-{role.value}.jpg",
            media_type="image/jpeg",
            size_bytes=size,
            sha256="a" * 64,
        ),
    )


def _track(track_id: str, roles: dict[EvidenceRole, tuple[int, int]]) -> ProcessedTrack:
    """``roles`` maps role -> (size_bytes, selection_micro)."""
    observations = tuple(
        _obs(role, rank, frame=rank, size=size, score=score, track_id=track_id)
        for rank, (role, (size, score)) in enumerate(
            (role, roles[role]) for role in ROLE_ORDER if role in roles
        )
    )
    return ProcessedTrack(
        track_id=track_id,
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=1000,
        detection_count=10,
        mean_confidence=0.9,
        max_confidence=0.9,
        observations=observations,
        trajectory_artifact=ArtifactDescriptor(
            storage_key=f"staging/{JOB}/attempt-0001/trajectories/{track_id}.msgpack",
            media_type="application/msgpack",
            size_bytes=10,
            sha256="b" * 64,
        ),
    )


def _roles(result, track_id: str) -> list[tuple[int, EvidenceRole]]:
    track = next(t for t in result.tracks if t.track_id == track_id)
    return [(o.rank, o.role) for o in track.observations]


def test_everything_fits_so_nothing_is_omitted_or_changed() -> None:
    tracks = (
        _track("person-2", {REP: (100, 5), NEAR: (200, 5), LATE: (50, 5)}),
        _track("person-1", {REP: (100, 5), EARLY: (70, 5)}),
    )

    result = admit(tracks, 10_000)

    assert result.omitted == ()
    assert [t.track_id for t in result.tracks] == ["person-1", "person-2"]
    assert result.tracks[1] is tracks[0]  # untouched when fully admitted
    assert result.accounting.near_view.admitted == 1
    assert result.accounting.representative.candidates == 2


def test_representatives_are_admitted_first_then_rounds_by_role() -> None:
    """A1: a high-scoring LateDiverse loses to any NearView when budget is short."""
    tracks = (
        _track("person-1", {REP: (100, 1), LATE: (300, 999_000)}),
        _track("person-2", {REP: (100, 1), NEAR: (300, 1)}),
    )

    result = admit(tracks, 500)

    assert _roles(result, "person-2") == [(0, REP), (1, NEAR)]
    assert _roles(result, "person-1") == [(0, REP)]
    assert [o.observation.role for o in result.omitted] == [LATE]


def test_within_a_round_orders_by_score_desc_then_track_id() -> None:
    """A2"""
    tracks = (
        _track("person-3", {REP: (10, 1), NEAR: (100, 500_000)}),
        _track("person-1", {REP: (10, 1), NEAR: (100, 700_000)}),
        _track("person-2", {REP: (10, 1), NEAR: (100, 500_000)}),
    )

    # Room for Representatives and two NearViews.
    result = admit(tracks, 30 + 200)

    assert {t.track_id for t in result.tracks if len(t.observations) == 2} == {"person-1", "person-2"}
    assert [o.observation.crop.storage_key.rsplit("/", 1)[1] for o in result.omitted] == ["person-3-near-view.jpg"]


def test_tight_quota_omits_and_continues() -> None:
    """A3: a later, smaller candidate is admitted after a larger one is omitted."""
    tracks = (
        _track("person-1", {REP: (10, 1), NEAR: (500, 900_000)}),
        _track("person-2", {REP: (10, 1), NEAR: (50, 100_000)}),
    )

    result = admit(tracks, 100)

    assert _roles(result, "person-2") == [(0, REP), (1, NEAR)]
    assert _roles(result, "person-1") == [(0, REP)]
    assert result.accounting.near_view.omitted == 1


def test_representatives_over_quota_fail_closed() -> None:
    """A4"""
    tracks = (_track("person-1", {REP: (600, 1)}), _track("person-2", {REP: (600, 1)}))

    with pytest.raises(EvidenceError, match="evidence_quota_exceeded"):
        admit(tracks, 1000)


def test_representatives_exactly_filling_the_quota_are_admitted() -> None:
    tracks = (
        _track("person-1", {REP: (500, 1), NEAR: (1, 900_000)}),
        _track("person-2", {REP: (500, 1)}),
    )

    result = admit(tracks, 1000)

    assert [len(t.observations) for t in result.tracks] == [1, 1]
    assert result.accounting.representative.admitted_bytes == 1000
    assert result.accounting.near_view.omitted == 1


def test_omission_reranks_contiguously_without_gaps() -> None:
    tracks = (_track("person-1", {REP: (10, 1), NEAR: (500, 1), EARLY: (20, 1), LATE: (20, 1)}),)

    result = admit(tracks, 60)

    assert _roles(result, "person-1") == [(0, REP), (1, EARLY), (2, LATE)]


def test_accounting_sums_match_descriptors_and_satisfy_the_result_contract() -> None:
    """A5: accounting is computed from the descriptors; the result re-checks it."""
    rng = random.Random(7)
    tracks = []
    for index in range(40):
        roles = {REP: (rng.randint(1, 65536), rng.randint(0, 10**6))}
        for role in ROLE_ORDER[1:]:
            if rng.random() < 0.7:
                roles[role] = (rng.randint(1, 163840), rng.randint(0, 10**6))
        tracks.append(_track(f"person-{index:03d}", roles))

    result = admit(tracks, 2_500_000)

    for role in ROLE_ORDER:
        present = [o for t in result.tracks for o in t.observations if o.role is role]
        omitted = [o.observation for o in result.omitted if o.observation.role is role]
        accounting = result.accounting.for_role(role)
        assert accounting.admitted == len(present)
        assert accounting.omitted == len(omitted)
        assert accounting.candidates == len(present) + len(omitted)
        assert accounting.admitted_bytes == sum(o.crop.size_bytes for o in present)
        assert accounting.candidate_bytes == accounting.admitted_bytes + sum(o.crop.size_bytes for o in omitted)
    assert sum(o.crop.size_bytes for t in result.tracks for o in t.observations) <= 2_500_000
    # The same accounting is accepted by the processing-result invariants.
    VisionProcessingResult(JOB, 100, result.tracks, result.accounting)


def test_admission_is_deterministic_regardless_of_input_order() -> None:
    tracks = [
        _track(f"person-{i}", {REP: (10, 1), NEAR: (100, (i * 37) % 5 * 100_000)})
        for i in range(12)
    ]
    first = admit(tracks, 12 * 10 + 500)
    shuffled = list(tracks)
    random.Random(3).shuffle(shuffled)
    second = admit(shuffled, 12 * 10 + 500)

    assert first == second


def test_track_id_order_is_ordinal_like_the_platform() -> None:
    """A6: the platform sorts Track ids with StringComparer.Ordinal."""
    ids = ["vehicle-10", "person-2", "person-10", "a.b", "a-b", "a_b", "0x", "person-1"]
    tracks = [_track(track_id, {REP: (10, 1)}) for track_id in ids]

    result = admit(tracks, 10_000)

    expected = sorted(ids, key=lambda value: [ord(c) for c in value])
    assert [t.track_id for t in result.tracks] == expected


def test_track_without_a_representative_is_refused() -> None:
    with pytest.raises(ValueError):
        _track("person-1", {NEAR: (10, 1)})
