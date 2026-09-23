from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.runtime.errors import RuntimeDisposition, TrackerError
from mavi_vision.runtime.profile import ByteTrackProfile
import mavi_vision.tracking.bytetrack as bytetrack_module
from mavi_vision.tracking.bytetrack import ByteTrackTracker
from mavi_vision.tracking.interfaces import TrackerUpdate
from mavi_vision.video.reader import DecodedFrame


class FakeDetections:
    def __init__(
        self,
        *,
        xyxy: np.ndarray,
        confidence: np.ndarray,
        data: dict[str, np.ndarray],
    ) -> None:
        self.xyxy = np.asarray(xyxy)
        self.confidence = np.asarray(confidence)
        self.data = {key: np.asarray(value) for key, value in data.items()}
        self.tracker_id: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.xyxy)


Script = Callable[[FakeDetections, float], object]


class FakeNativeTracker:
    def __init__(self, script: Script) -> None:
        self._script = script
        self.calls: list[tuple[FakeDetections, float]] = []

    def update(self, detections: FakeDetections, *, timestamp: float) -> object:
        self.calls.append((detections, timestamp))
        return self._script(detections, timestamp)


class RecordingTrackerFactory:
    def __init__(self, scripts: tuple[Script, Script]) -> None:
        self._scripts = iter(scripts)
        self.kwargs: list[dict[str, object]] = []
        self.trackers: list[FakeNativeTracker] = []

    def __call__(self, **kwargs: object) -> FakeNativeTracker:
        self.kwargs.append(dict(kwargs))
        tracker = FakeNativeTracker(next(self._scripts))
        self.trackers.append(tracker)
        return tracker


def profile() -> ByteTrackProfile:
    return ByteTrackProfile(
        reference_frame_rate=30.0,
        track_activation_threshold=0.7,
        high_confidence_threshold=0.6,
        minimum_iou_threshold=0.1,
        minimum_consecutive_frames=2,
        lost_track_buffer_seconds=1.0,
    )


def frame(
    *,
    number: int = 10,
    offset_ms: int = 400,
    width: int = 200,
    height: int = 100,
) -> DecodedFrame:
    return DecodedFrame(
        source_frame_number=number,
        offset_ms=offset_ms,
        image=np.zeros((height, width, 3), dtype=np.uint8),
    )


def detection(
    object_class: ObjectClass,
    *,
    ordinal: int,
    confidence: float = 0.9,
    bbox: tuple[float, float, float, float] = (0.1, 0.2, 0.3, 0.4),
) -> DetectionCandidate:
    return DetectionCandidate(
        object_class=object_class,
        confidence=confidence,
        bounding_box=NormalizedBoundingBox(*bbox),
        frame_ordinal=ordinal,
    )


def result(
    source: FakeDetections,
    tracker_ids: object,
    *,
    ordinals: object | None = None,
    xyxy: object | None = None,
    confidence: object | None = None,
) -> FakeDetections:
    output = FakeDetections(
        xyxy=np.asarray(source.xyxy if xyxy is None else xyxy),
        confidence=np.asarray(source.confidence if confidence is None else confidence),
        data={
            "mavi_ordinal": np.asarray(
                source.data["mavi_ordinal"] if ordinals is None else ordinals
            )
        },
    )
    output.tracker_id = np.asarray(tracker_ids)
    return output


def echo_ids(*ids: int) -> Script:
    def script(detections: FakeDetections, timestamp: float) -> object:
        if len(detections) == 0:
            return result(detections, np.empty((0,), dtype=np.int64))
        selected = ids if ids else tuple(range(100, 100 + len(detections)))
        return result(detections, np.asarray(selected, dtype=np.int64))

    return script


def install_bindings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    person_script: Script | None = None,
    vehicle_script: Script | None = None,
) -> RecordingTrackerFactory:
    factory = RecordingTrackerFactory(
        (
            person_script or echo_ids(),
            vehicle_script or echo_ids(),
        )
    )
    bindings = SimpleNamespace(
        tracker_factory=factory,
        detections_factory=FakeDetections,
    )
    monkeypatch.setattr(
        bytetrack_module,
        "_load_bytetrack_bindings",
        lambda: bindings,
    )
    return factory


def test_exact_profile_to_native_constructor_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = install_bindings(monkeypatch)

    ByteTrackTracker(profile())

    expected = {
        "frame_rate": 30.0,
        "lost_track_buffer": 30,
        "track_activation_threshold": 0.7,
        "high_conf_det_threshold": 0.6,
        "minimum_iou_threshold": 0.1,
        "minimum_consecutive_frames": 2,
    }
    assert factory.kwargs == [expected, expected]


def test_pixel_conversion_timestamp_and_metadata_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = install_bindings(monkeypatch)
    tracker = ByteTrackTracker(profile())
    source = detection(ObjectClass.PERSON, ordinal=7, confidence=0.83)

    output = tracker.update(frame(), (source,)).candidates

    person_call, vehicle_call = factory.trackers[0].calls[0], factory.trackers[1].calls[0]
    native, timestamp = person_call
    assert timestamp == 0.4
    np.testing.assert_allclose(native.xyxy, [[20.0, 20.0, 80.0, 60.0]])
    np.testing.assert_allclose(native.confidence, [0.83])
    np.testing.assert_array_equal(native.data["mavi_ordinal"], [7])
    assert vehicle_call[1] == 0.4
    assert len(vehicle_call[0]) == 0
    assert output[0].bounding_box is source.bounding_box
    assert output[0].confidence == source.confidence


def test_both_native_domains_advance_on_every_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = install_bindings(monkeypatch)
    tracker = ByteTrackTracker(profile())

    tracker.update(frame(number=1, offset_ms=10), ())
    tracker.update(
        frame(number=2, offset_ms=20),
        (detection(ObjectClass.VEHICLE, ordinal=0),),
    )
    tracker.update(
        frame(number=3, offset_ms=30),
        (detection(ObjectClass.PERSON, ordinal=0),),
    )

    assert [call[1] for call in factory.trackers[0].calls] == [0.01, 0.02, 0.03]
    assert [call[1] for call in factory.trackers[1].calls] == [0.01, 0.02, 0.03]
    assert [len(call[0]) for call in factory.trackers[0].calls] == [0, 0, 1]
    assert [len(call[0]) for call in factory.trackers[1].calls] == [0, 1, 0]


@pytest.mark.parametrize(
    ("first_number", "first_offset", "second_number", "second_offset", "message"),
    [
        (1, 10, 1, 20, "bytetrack_frame_number_non_monotonic"),
        (2, 10, 1, 20, "bytetrack_frame_number_non_monotonic"),
        (1, 10, 2, 10, "bytetrack_frame_offset_non_monotonic"),
        (1, 20, 2, 10, "bytetrack_frame_offset_non_monotonic"),
    ],
)
def test_frame_sequence_must_be_strictly_monotonic_before_native_mutation(
    monkeypatch: pytest.MonkeyPatch,
    first_number: int,
    first_offset: int,
    second_number: int,
    second_offset: int,
    message: str,
) -> None:
    factory = install_bindings(monkeypatch)
    tracker = ByteTrackTracker(profile())
    tracker.update(frame(number=first_number, offset_ms=first_offset), ())

    with pytest.raises(TrackerError, match=message):
        tracker.update(frame(number=second_number, offset_ms=second_offset), ())

    assert len(factory.trackers[0].calls) == 1
    assert len(factory.trackers[1].calls) == 1


def test_duplicate_global_frame_ordinal_fails_before_native_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = install_bindings(monkeypatch)
    tracker = ByteTrackTracker(profile())
    detections = (
        detection(ObjectClass.PERSON, ordinal=4),
        detection(ObjectClass.VEHICLE, ordinal=4),
    )

    with pytest.raises(TrackerError, match="bytetrack_frame_ordinal_duplicate"):
        tracker.update(frame(), detections)

    assert factory.trackers[0].calls == []
    assert factory.trackers[1].calls == []


def test_backend_reordering_is_recovered_by_ordinal_and_final_output_is_global_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reverse_person(detections: FakeDetections, timestamp: float) -> object:
        return result(
            detections,
            [202, 101],
            ordinals=detections.data["mavi_ordinal"][::-1],
            xyxy=np.asarray([[999, 999, 1000, 1000], [888, 888, 999, 999]]),
            confidence=[0.01, 0.02],
        )

    factory = install_bindings(
        monkeypatch,
        person_script=reverse_person,
        vehicle_script=echo_ids(303),
    )
    tracker = ByteTrackTracker(profile())
    left = detection(
        ObjectClass.PERSON,
        ordinal=2,
        confidence=0.71,
        bbox=(0.1, 0.1, 0.1, 0.2),
    )
    right = detection(
        ObjectClass.PERSON,
        ordinal=0,
        confidence=0.91,
        bbox=(0.7, 0.1, 0.1, 0.2),
    )
    vehicle = detection(
        ObjectClass.VEHICLE,
        ordinal=1,
        confidence=0.81,
        bbox=(0.4, 0.4, 0.2, 0.2),
    )

    output = tracker.update(frame(), (left, right, vehicle)).candidates

    assert [item.object_class for item in output] == [
        ObjectClass.PERSON,
        ObjectClass.VEHICLE,
        ObjectClass.PERSON,
    ]
    assert output[0].bounding_box is right.bounding_box
    assert output[0].confidence == right.confidence
    assert output[2].bounding_box is left.bounding_box
    assert output[2].confidence == left.confidence
    # MAVI identity allocation is geometric, not native-ID or output-row order.
    assert output[2].track_id == "person-000001"
    assert output[0].track_id == "person-000002"
    assert output[1].track_id == "vehicle-000001"
    assert len(factory.trackers) == 2


@pytest.mark.parametrize(
    "bad_ordinals",
    [
        np.asarray([0.0], dtype=np.float64),
        np.asarray([0, 0], dtype=np.int64),
        np.asarray([99], dtype=np.int64),
    ],
)
def test_malformed_ordinal_round_trip_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    bad_ordinals: np.ndarray,
) -> None:
    def script(detections: FakeDetections, timestamp: float) -> object:
        return result(detections, np.ones(len(bad_ordinals), dtype=np.int64), ordinals=bad_ordinals)

    install_bindings(monkeypatch, person_script=script)
    tracker = ByteTrackTracker(profile())
    sources = (
        detection(ObjectClass.PERSON, ordinal=0),
        detection(ObjectClass.PERSON, ordinal=1),
    )
    selected = sources if len(bad_ordinals) == 2 else sources[:1]

    with pytest.raises(TrackerError, match="bytetrack_ordinal_contract_invalid"):
        tracker.update(frame(), selected)


def test_missing_ordinal_metadata_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def script(detections: FakeDetections, timestamp: float) -> object:
        output = result(detections, [1])
        output.data = {}
        return output

    install_bindings(monkeypatch, person_script=script)
    tracker = ByteTrackTracker(profile())

    with pytest.raises(TrackerError, match="bytetrack_ordinal_contract_invalid"):
        tracker.update(frame(), (detection(ObjectClass.PERSON, ordinal=0),))


@pytest.mark.parametrize(
    "tracker_ids",
    [
        None,
        np.asarray([1.0], dtype=np.float64),
        np.asarray([-2], dtype=np.int64),
        np.asarray([1, 1], dtype=np.int64),
    ],
)
def test_malformed_tracker_ids_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tracker_ids: object,
) -> None:
    def script(detections: FakeDetections, timestamp: float) -> object:
        output = result(
            detections,
            [1, 2][: len(detections)],
        )
        output.tracker_id = tracker_ids
        return output

    install_bindings(monkeypatch, person_script=script)
    tracker = ByteTrackTracker(profile())
    count = 2 if isinstance(tracker_ids, np.ndarray) and len(tracker_ids) == 2 else 1
    sources = tuple(
        detection(ObjectClass.PERSON, ordinal=index) for index in range(count)
    )

    with pytest.raises(TrackerError, match="bytetrack_tracker_id_contract_invalid"):
        tracker.update(frame(), sources)


def test_tentative_minus_one_is_suppressed_and_never_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def person_script(detections: FakeDetections, timestamp: float) -> object:
        nonlocal calls
        calls += 1
        return result(detections, [-1] if calls == 1 else [44])

    install_bindings(monkeypatch, person_script=person_script)
    tracker = ByteTrackTracker(profile())
    source = detection(ObjectClass.PERSON, ordinal=0)

    first = tracker.update(frame(number=1, offset_ms=10), (source,))
    second = tracker.update(frame(number=2, offset_ms=20), (source,)).candidates

    assert first == TrackerUpdate(candidates=())
    assert [item.track_id for item in second] == ["person-000001"]
    assert len(second) == 1


def test_person_and_vehicle_native_id_spaces_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(
        monkeypatch,
        person_script=echo_ids(7),
        vehicle_script=echo_ids(7),
    )
    tracker = ByteTrackTracker(profile())

    output = tracker.update(
        frame(),
        (
            detection(ObjectClass.PERSON, ordinal=0),
            detection(ObjectClass.VEHICLE, ordinal=1),
        ),
    ).candidates

    assert [item.track_id for item in output] == [
        "person-000001",
        "vehicle-000001",
    ]


def test_existing_native_mapping_is_stable_across_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=echo_ids(91))
    tracker = ByteTrackTracker(profile())
    first_detection = detection(
        ObjectClass.PERSON,
        ordinal=0,
        bbox=(0.1, 0.1, 0.2, 0.2),
    )
    second_detection = detection(
        ObjectClass.PERSON,
        ordinal=0,
        bbox=(0.2, 0.1, 0.2, 0.2),
    )

    first = tracker.update(frame(number=1, offset_ms=10), (first_detection,)).candidates
    second = tracker.update(frame(number=2, offset_ms=20), (second_detection,)).candidates

    assert first[0].track_id == "person-000001"
    assert second[0].track_id == "person-000001"
    assert second[0].bounding_box is second_detection.bounding_box


def test_new_adapter_resets_native_trackers_maps_and_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(
        monkeypatch,
        person_script=echo_ids(50),
        vehicle_script=echo_ids(),
    )
    first = ByteTrackTracker(profile())
    assert first.update(
        frame(number=1, offset_ms=10),
        (detection(ObjectClass.PERSON, ordinal=0),),
    ).candidates[0].track_id == "person-000001"

    factory = install_bindings(
        monkeypatch,
        person_script=echo_ids(999),
        vehicle_script=echo_ids(),
    )
    second = ByteTrackTracker(profile())
    assert second.update(
        frame(number=1, offset_ms=10),
        (detection(ObjectClass.PERSON, ordinal=0),),
    ).candidates[0].track_id == "person-000001"
    assert len(factory.trackers) == 2


def test_native_construction_exception_is_translated_without_third_party_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingFactory:
        def __call__(self, **kwargs: object) -> object:
            raise RuntimeError("third-party-secret")

    monkeypatch.setattr(
        bytetrack_module,
        "_load_bytetrack_bindings",
        lambda: SimpleNamespace(
            tracker_factory=ExplodingFactory(),
            detections_factory=FakeDetections,
        ),
    )

    with pytest.raises(TrackerError) as captured:
        ByteTrackTracker(profile())

    assert captured.value.failure_code == "vision_tracker_failed"
    assert captured.value.runtime_disposition is RuntimeDisposition.CONTINUE
    assert str(captured.value) == "bytetrack_backend_initialization_failed"
    assert captured.value.__cause__ is None


def test_native_update_exception_is_translated_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(detections: FakeDetections, timestamp: float) -> object:
        raise RuntimeError("third-party-secret")

    install_bindings(monkeypatch, person_script=explode)
    tracker = ByteTrackTracker(profile())

    with pytest.raises(TrackerError) as captured:
        tracker.update(frame(), (detection(ObjectClass.PERSON, ordinal=0),))

    assert captured.value.failure_code == "vision_tracker_failed"
    assert captured.value.runtime_disposition is RuntimeDisposition.CONTINUE
    assert str(captured.value) == "bytetrack_backend_update_failed"
    assert captured.value.__cause__ is None


def test_native_failure_invalidates_attempt_instead_of_reusing_partial_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def vehicle_script(detections: FakeDetections, timestamp: float) -> object:
        raise RuntimeError("boom")

    factory = install_bindings(monkeypatch, vehicle_script=vehicle_script)
    tracker = ByteTrackTracker(profile())
    sources = (detection(ObjectClass.VEHICLE, ordinal=0),)

    with pytest.raises(TrackerError, match="bytetrack_backend_update_failed"):
        tracker.update(frame(number=1, offset_ms=10), sources)

    with pytest.raises(TrackerError, match="bytetrack_attempt_invalidated"):
        tracker.update(frame(number=1, offset_ms=10), sources)

    # No second native mutation is permitted after a failed attempt. A retry is
    # performed by Task 9 with a new attempt-scoped adapter instead.
    assert len(factory.trackers[0].calls) == 1
    assert len(factory.trackers[1].calls) == 1


def test_module_has_no_top_level_trackers_or_supervision_import() -> None:
    source_path = Path(bytetrack_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])

    assert "trackers" not in imported
    assert "supervision" not in imported


# --- Track lifecycle and exact retirement (ADR-013 §5, S1.1) ------------------
#
# profile(): lost budget 1.0 s at a 30 Hz nominal rate, so an identity last
# emitted at offset t retires at the first accepted frame whose offset exceeds
# t + 1000 + 33.33 ms, i.e. offset >= t + 1034 for integer millisecond offsets.


def scripted_ids(*per_call: tuple[int, ...]) -> Script:
    """Return the native ids scripted for each successive non-empty call."""

    calls = iter(per_call)

    def script(detections: FakeDetections, timestamp: float) -> object:
        if len(detections) == 0:
            return result(detections, np.empty((0,), dtype=np.int64))
        return result(detections, np.asarray(next(calls), dtype=np.int64))

    return script


def person(ordinal: int = 0) -> DetectionCandidate:
    return detection(ObjectClass.PERSON, ordinal=ordinal)


def vehicle(ordinal: int = 0) -> DetectionCandidate:
    return detection(ObjectClass.VEHICLE, ordinal=ordinal)


def candidate_ids(update: TrackerUpdate) -> list[str]:
    return [candidate.track_id for candidate in update.candidates]


def test_unmatched_identity_within_budget_stays_live_and_keeps_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=scripted_ids((5,), (5,)))
    tracker = ByteTrackTracker(profile())

    first = tracker.update(frame(number=1, offset_ms=0), (person(),))
    # Several consecutive frames without a match: unmatched is not retired.
    gaps = [
        tracker.update(frame(number=number, offset_ms=offset), ())
        for number, offset in ((2, 100), (3, 500), (4, 1000))
    ]
    # Reacquired at the last offset still inside the budget.
    reacquired = tracker.update(frame(number=5, offset_ms=1033), (person(),))

    assert candidate_ids(first) == ["person-000001"]
    assert all(update == TrackerUpdate(candidates=()) for update in gaps)
    assert candidate_ids(reacquired) == ["person-000001"]
    assert reacquired.retired_track_ids == ()


def test_retirement_fires_at_first_frame_past_budget_and_never_earlier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=scripted_ids((5,)))
    tracker = ByteTrackTracker(profile())

    tracker.update(frame(number=1, offset_ms=0), (person(),))
    at_threshold = tracker.update(frame(number=2, offset_ms=1033), ())
    past_threshold = tracker.update(frame(number=3, offset_ms=1034), ())
    afterwards = tracker.update(frame(number=4, offset_ms=5000), ())

    assert at_threshold.retired_track_ids == ()
    assert past_threshold.retired_track_ids == ("person-000001",)
    assert past_threshold.candidates == ()
    # Retired exactly once.
    assert afterwards.retired_track_ids == ()


def test_retirement_uses_media_time_not_frame_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=scripted_ids((5,)))
    tracker = ByteTrackTracker(profile())

    tracker.update(frame(number=1, offset_ms=0), (person(),))
    # A single sparse frame far in the future retires immediately; many dense
    # frames within the budget never do.
    dense = [
        tracker.update(frame(number=number, offset_ms=number * 10), ())
        for number in range(2, 100)
    ]
    sparse = tracker.update(frame(number=500, offset_ms=60_000), ())

    assert all(update.retired_track_ids == () for update in dense)
    assert sparse.retired_track_ids == ("person-000001",)


def test_retirement_refreshes_on_every_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=scripted_ids((5,), (5,)))
    tracker = ByteTrackTracker(profile())

    tracker.update(frame(number=1, offset_ms=0), (person(),))
    tracker.update(frame(number=2, offset_ms=900), (person(),))
    # 1500 would retire an identity last seen at 0, but not one seen at 900.
    not_yet = tracker.update(frame(number=3, offset_ms=1500), ())
    retired = tracker.update(frame(number=4, offset_ms=900 + 1034), ())

    assert not_yet.retired_track_ids == ()
    assert retired.retired_track_ids == ("person-000001",)


def test_native_id_seen_again_after_retirement_starts_a_new_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=scripted_ids((5,), (5,)))
    tracker = ByteTrackTracker(profile())

    tracker.update(frame(number=1, offset_ms=0), (person(),))
    retired = tracker.update(frame(number=2, offset_ms=2000), ())
    reused = tracker.update(frame(number=3, offset_ms=2100), (person(),))

    assert retired.retired_track_ids == ("person-000001",)
    assert candidate_ids(reused) == ["person-000002"]
    assert reused.retired_track_ids == ()


def test_native_id_reused_in_the_retiring_frame_never_extends_the_retired_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The backend pruned native id 5 before this frame's association, so a row
    # carrying 5 again is a new tracklet. It must neither extend person-000001
    # nor be emitted under the id being retired.
    install_bindings(monkeypatch, person_script=scripted_ids((5,), (5,)))
    tracker = ByteTrackTracker(profile())

    tracker.update(frame(number=1, offset_ms=0), (person(),))
    update = tracker.update(frame(number=2, offset_ms=2000), (person(),))

    assert update.retired_track_ids == ("person-000001",)
    assert candidate_ids(update) == ["person-000002"]


def test_tracks_retire_independently_in_canonical_order_across_classes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(
        monkeypatch,
        person_script=scripted_ids((1, 2), (2,)),
        vehicle_script=scripted_ids((1,)),
    )
    tracker = ByteTrackTracker(profile())

    tracker.update(
        frame(number=1, offset_ms=0),
        (person(ordinal=0), person(ordinal=1), vehicle(ordinal=2)),
    )
    tracker.update(frame(number=2, offset_ms=500), (person(ordinal=0),))
    first_wave = tracker.update(frame(number=3, offset_ms=1100), ())
    second_wave = tracker.update(frame(number=4, offset_ms=1600), ())

    assert first_wave.retired_track_ids == ("person-000001", "vehicle-000001")
    assert second_wave.retired_track_ids == ("person-000002",)


def test_live_map_holds_only_live_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(
        monkeypatch,
        person_script=scripted_ids(*((native_id,) for native_id in range(1, 51))),
    )
    tracker = ByteTrackTracker(profile())

    # Fifty short-lived Tracks, each retired by the next one's arrival 2 s later.
    for index in range(50):
        tracker.update(frame(number=index + 1, offset_ms=index * 2000), (person(),))

    assert list(tracker._person_live) == [50]
    assert tracker._vehicle_live == {}


def test_tentative_rows_never_become_live_or_retire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=scripted_ids((-1,)))
    tracker = ByteTrackTracker(profile())

    tentative = tracker.update(frame(number=1, offset_ms=0), (person(),))
    later = tracker.update(frame(number=2, offset_ms=5000), ())

    assert tentative == TrackerUpdate(candidates=())
    assert later == TrackerUpdate(candidates=())


def test_poisoned_adapter_does_not_report_retirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_after_first(detections: FakeDetections, timestamp: float) -> object:
        if timestamp == 0.0:
            return result(detections, np.asarray([5], dtype=np.int64))
        raise RuntimeError("native-failure")

    install_bindings(monkeypatch, person_script=failing_after_first)
    tracker = ByteTrackTracker(profile())
    tracker.update(frame(number=1, offset_ms=0), (person(),))

    with pytest.raises(TrackerError, match="bytetrack_backend_update_failed"):
        tracker.update(frame(number=2, offset_ms=2000), ())
    with pytest.raises(TrackerError, match="bytetrack_attempt_invalidated"):
        tracker.update(frame(number=3, offset_ms=3000), ())


def test_retirement_state_does_not_leak_into_a_new_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=scripted_ids((5,)))
    first = ByteTrackTracker(profile())
    first.update(frame(number=1, offset_ms=0), (person(),))
    assert first.update(frame(number=2, offset_ms=2000), ()).retired_track_ids == (
        "person-000001",
    )

    install_bindings(monkeypatch, person_script=scripted_ids((5,)))
    second = ByteTrackTracker(profile())
    fresh = second.update(frame(number=1, offset_ms=0), (person(),))
    quiet = second.update(frame(number=2, offset_ms=500), ())

    assert candidate_ids(fresh) == ["person-000001"]
    assert quiet.retired_track_ids == ()


def test_retirement_threshold_follows_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_bindings(monkeypatch, person_script=scripted_ids((5,)))
    tracker = ByteTrackTracker(
        ByteTrackProfile(
            reference_frame_rate=10.0,
            track_activation_threshold=0.7,
            high_confidence_threshold=0.6,
            minimum_iou_threshold=0.1,
            minimum_consecutive_frames=2,
            lost_track_buffer_seconds=2.0,
        )
    )

    tracker.update(frame(number=1, offset_ms=0), (person(),))
    boundary = tracker.update(frame(number=2, offset_ms=2100), ())
    past = tracker.update(frame(number=3, offset_ms=2101), ())

    assert boundary.retired_track_ids == ()
    assert past.retired_track_ids == ("person-000001",)
