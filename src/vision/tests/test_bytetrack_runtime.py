from __future__ import annotations

import importlib.metadata
import os
from types import SimpleNamespace

import numpy as np
import pytest

if os.environ.get("MAVI_RUN_QUALIFIED_BYTETRACK_TESTS") != "1":
    pytest.skip(
        "exact Trackers 2.6 qualification suite runs only in the qualified runtime job",
        allow_module_level=True,
    )


def _require_exact_distribution(name: str, expected: str) -> None:
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        pytest.fail(f"qualified runtime dependency missing: {name}", pytrace=False)
    if actual != expected:
        pytest.fail(
            f"qualified runtime dependency drift: {name}={actual}, expected={expected}",
            pytrace=False,
        )


_require_exact_distribution("trackers", "2.6.0")
_require_exact_distribution("supervision", "0.30.2")

import supervision as sv  # noqa: E402
from trackers import ByteTrackTracker as NativeByteTrackTracker  # noqa: E402

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass  # noqa: E402
from mavi_vision.detection.interfaces import DetectionCandidate  # noqa: E402
from mavi_vision.runtime.profile import ByteTrackProfile  # noqa: E402
import mavi_vision.tracking.bytetrack as bytetrack_module  # noqa: E402
from mavi_vision.tracking.bytetrack import ByteTrackTracker  # noqa: E402
from mavi_vision.video.reader import DecodedFrame  # noqa: E402


def _native_tracker() -> NativeByteTrackTracker:
    return NativeByteTrackTracker(
        frame_rate=30.0,
        lost_track_buffer=30,
        track_activation_threshold=0.7,
        high_conf_det_threshold=0.6,
        minimum_iou_threshold=0.1,
        minimum_consecutive_frames=2,
    )


def _native_detections(
    boxes: list[tuple[float, float, float, float]],
    confidences: list[float],
    ordinals: list[int] | None = None,
) -> sv.Detections:
    return sv.Detections(
        xyxy=np.asarray(boxes, dtype=np.float64).reshape((-1, 4)),
        confidence=np.asarray(confidences, dtype=np.float64),
        data={
            "mavi_ordinal": np.asarray(
                ordinals if ordinals is not None else list(range(len(boxes))),
                dtype=np.int64,
            )
        },
    )


def _empty_native() -> sv.Detections:
    return _native_detections([], [])


def _profile() -> ByteTrackProfile:
    return ByteTrackProfile(
        reference_frame_rate=30.0,
        track_activation_threshold=0.7,
        high_confidence_threshold=0.6,
        minimum_iou_threshold=0.1,
        minimum_consecutive_frames=2,
        lost_track_buffer_seconds=1.0,
    )


def _frame(number: int, offset_ms: int) -> DecodedFrame:
    return DecodedFrame(
        source_frame_number=number,
        offset_ms=offset_ms,
        image=np.zeros((100, 200, 3), dtype=np.uint8),
    )


def _candidate(
    object_class: ObjectClass,
    ordinal: int,
    *,
    x: float,
    y: float = 0.2,
    confidence: float = 0.9,
) -> DetectionCandidate:
    return DetectionCandidate(
        object_class=object_class,
        confidence=confidence,
        bounding_box=NormalizedBoundingBox(x, y, 0.12, 0.2),
        frame_ordinal=ordinal,
    )


def _serialize(output) -> tuple[tuple[str, str, float, float, float], ...]:
    return tuple(
        (
            item.track_id,
            item.object_class.value,
            item.confidence,
            item.bounding_box.x,
            item.bounding_box.y,
        )
        for item in output
    )


def test_supervision_ordinal_data_survives_native_style_reordering() -> None:
    detections = _native_detections(
        [(0, 0, 10, 10), (20, 0, 30, 10)],
        [0.9, 0.8],
        [11, 22],
    )
    reordered = detections[np.asarray([1, 0], dtype=np.int64)]
    np.testing.assert_array_equal(reordered.data["mavi_ordinal"], [22, 11])


def test_native_first_spawn_is_tentative_then_confirms() -> None:
    tracker = _native_tracker()
    detections = _native_detections([(10, 10, 30, 40)], [0.9], [7])
    first = tracker.update(detections, timestamp=0.0)
    second = tracker.update(detections, timestamp=1.0 / 30.0)
    assert int(first.tracker_id[0]) == -1
    assert int(second.tracker_id[0]) >= 0
    assert int(second.data["mavi_ordinal"][0]) == 7


def test_native_continuous_object_retains_identity() -> None:
    tracker = _native_tracker()
    ids: list[int] = []
    for index, x in enumerate((10.0, 11.0, 12.0, 13.0)):
        tracked = tracker.update(
            _native_detections([(x, 10, x + 20, 40)], [0.9]),
            timestamp=index / 30.0,
        )
        ids.append(int(tracked.tracker_id[0]))
    assert ids[0] == -1
    assert ids[1] >= 0
    assert ids[1:] == [ids[1], ids[1], ids[1]]


def test_native_low_confidence_associates_but_cannot_spawn() -> None:
    tracker = _native_tracker()
    high = _native_detections([(10, 10, 30, 40)], [0.9])
    tracker.update(high, timestamp=0.0)
    confirmed = tracker.update(high, timestamp=1.0 / 30.0)
    confirmed_id = int(confirmed.tracker_id[0])
    assert confirmed_id >= 0
    low = _native_detections([(11, 10, 31, 40)], [0.55])
    associated = tracker.update(low, timestamp=2.0 / 30.0)
    assert int(associated.tracker_id[0]) == confirmed_id
    fresh = _native_tracker()
    low_only = fresh.update(low, timestamp=0.0)
    assert not any(int(value) >= 0 for value in low_only.tracker_id)


def test_native_time_budget_retains_inside_and_expires_beyond_one_second() -> None:
    tracker = _native_tracker()
    high = _native_detections([(10, 10, 30, 40)], [0.9])
    tracker.update(high, timestamp=0.0)
    confirmed = tracker.update(high, timestamp=1.0 / 30.0)
    original_id = int(confirmed.tracker_id[0])
    assert original_id >= 0
    tracker.update(_empty_native(), timestamp=0.50)
    inside = tracker.update(
        _native_detections([(11, 10, 31, 40)], [0.9]),
        timestamp=0.90,
    )
    assert int(inside.tracker_id[0]) == original_id
    tracker.update(_empty_native(), timestamp=2.00)
    after_expiry_first = tracker.update(
        _native_detections([(12, 10, 32, 40)], [0.9]),
        timestamp=2.01,
    )
    after_expiry_second = tracker.update(
        _native_detections([(12.5, 10, 32.5, 40)], [0.9]),
        timestamp=2.01 + 1.0 / 30.0,
    )
    assert int(after_expiry_first.tracker_id[0]) == -1
    assert int(after_expiry_second.tracker_id[0]) >= 0
    assert int(after_expiry_second.tracker_id[0]) != original_id


def test_mavi_adapter_handles_regular_and_vfr_timestamp_gaps() -> None:
    tracker = ByteTrackTracker(_profile())
    outputs = []
    for number, offset_ms, x in (
        (1, 0, 0.10),
        (2, 33, 0.105),
        (3, 67, 0.11),
        (4, 420, 0.115),
        (5, 920, 0.12),
    ):
        outputs.append(
            tracker.update(
                _frame(number, offset_ms),
                (_candidate(ObjectClass.PERSON, 0, x=x),),
            )
        )
    assert outputs[0] == ()
    confirmed = outputs[1][0].track_id
    assert all(batch[0].track_id == confirmed for batch in outputs[1:])


def test_mavi_person_vehicle_overlap_never_shares_association_state() -> None:
    tracker = ByteTrackTracker(_profile())
    detections = (
        _candidate(ObjectClass.PERSON, 0, x=0.2),
        _candidate(ObjectClass.VEHICLE, 1, x=0.2),
    )
    assert tracker.update(_frame(1, 0), detections) == ()
    confirmed = tracker.update(_frame(2, 33), detections)
    assert [(item.object_class, item.track_id) for item in confirmed] == [
        (ObjectClass.PERSON, "person-000001"),
        (ObjectClass.VEHICLE, "vehicle-000001"),
    ]


def test_crossing_association_is_independent_of_detection_input_order() -> None:
    left_to_right = (0.10, 0.18, 0.26, 0.34, 0.42, 0.50, 0.58)
    right_to_left = (0.70, 0.62, 0.54, 0.46, 0.38, 0.30, 0.22)
    tracker_a = ByteTrackTracker(_profile())
    tracker_b = ByteTrackTracker(_profile())
    outputs_a = []
    outputs_b = []
    for index, (x_a, x_b) in enumerate(zip(left_to_right, right_to_left, strict=True)):
        first = _candidate(ObjectClass.PERSON, 0, x=x_a, y=0.15)
        second = _candidate(ObjectClass.PERSON, 1, x=x_b, y=0.55)
        timestamp = round(index * 1000 / 30)
        outputs_a.append(
            tracker_a.update(_frame(index + 1, timestamp), (first, second))
        )
        outputs_b.append(
            tracker_b.update(_frame(index + 1, timestamp), (second, first))
        )
    assert outputs_a[0] == outputs_b[0] == ()
    assert [_serialize(batch) for batch in outputs_a[1:]] == [
        _serialize(batch) for batch in outputs_b[1:]
    ]
    for batch in outputs_a[1:]:
        assert {item.track_id for item in batch} == {
            "person-000001",
            "person-000002",
        }


def test_exact_native_row_reordering_still_emits_original_mavi_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReorderingTracker:
        def __init__(self, **kwargs) -> None:
            self._tracker = NativeByteTrackTracker(**kwargs)

        def update(self, detections, *, timestamp):
            tracked = self._tracker.update(detections, timestamp=timestamp)
            if len(tracked) <= 1:
                return tracked
            order = np.arange(len(tracked) - 1, -1, -1, dtype=np.int64)
            return tracked[order]

    monkeypatch.setattr(
        bytetrack_module,
        "_load_bytetrack_bindings",
        lambda: SimpleNamespace(
            tracker_factory=ReorderingTracker,
            detections_factory=sv.Detections,
        ),
    )
    tracker = ByteTrackTracker(_profile())
    first = (
        _candidate(ObjectClass.PERSON, 0, x=0.10, confidence=0.91),
        _candidate(ObjectClass.PERSON, 1, x=0.60, confidence=0.82),
    )
    second = (
        _candidate(ObjectClass.PERSON, 0, x=0.105, confidence=0.73),
        _candidate(ObjectClass.PERSON, 1, x=0.605, confidence=0.77),
    )
    assert tracker.update(_frame(1, 0), first) == ()
    output = tracker.update(_frame(2, 33), second)
    assert [item.bounding_box for item in output] == [
        second[0].bounding_box,
        second[1].bounding_box,
    ]
    assert [item.confidence for item in output] == [0.73, 0.77]
