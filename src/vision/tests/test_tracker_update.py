"""Per-update invariants of the model-neutral tracker lifecycle contract."""

from __future__ import annotations

import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.runtime.errors import RuntimeDisposition, TrackerError
from mavi_vision.tracking.interfaces import TrackCandidate, TrackerUpdate


def _candidate(track_id: str) -> TrackCandidate:
    return TrackCandidate(
        track_id=track_id,
        object_class=ObjectClass.PERSON,
        confidence=0.9,
        bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.2),
    )


def test_update_defaults_to_no_retirements() -> None:
    update = TrackerUpdate(candidates=(_candidate("person-1"),))

    assert update.retired_track_ids == ()


def test_update_accepts_disjoint_candidates_and_sorted_retirements() -> None:
    update = TrackerUpdate(
        candidates=(_candidate("person-3"),),
        retired_track_ids=("person-1", "vehicle-1"),
    )

    assert update.retired_track_ids == ("person-1", "vehicle-1")


@pytest.mark.parametrize(
    ("candidates", "retired", "code"),
    [
        ([_candidate("person-1")], (), "tracker_update_invalid"),
        ((_candidate("person-1"),), ["person-2"], "tracker_update_invalid"),
        (("person-1",), (), "tracker_update_invalid"),
        ((), ("",), "tracker_update_invalid"),
        ((), ("x" * 65,), "tracker_update_invalid"),
        ((), (7,), "tracker_update_invalid"),
        (
            (_candidate("person-1"), _candidate("person-1")),
            (),
            "tracker_update_candidate_duplicate",
        ),
        ((), ("person-1", "person-1"), "tracker_update_retirement_duplicate"),
        ((), ("person-2", "person-1"), "tracker_update_retirement_unordered"),
        (
            (_candidate("person-1"),),
            ("person-1",),
            "tracker_update_retired_candidate",
        ),
    ],
)
def test_update_rejects_per_update_contract_violations(candidates, retired, code) -> None:
    with pytest.raises(TrackerError, match=code) as raised:
        TrackerUpdate(candidates=candidates, retired_track_ids=retired)

    # A malformed tracker update is a tracker failure: the attempt stops and the
    # job continues through the normal retry path.
    assert raised.value.disposition is RuntimeDisposition.CONTINUE
