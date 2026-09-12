from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.runtime.errors import TrackerError
from mavi_vision.runtime.profile import ByteTrackProfile
from mavi_vision.tracking.interfaces import TrackCandidate
from mavi_vision.video.reader import DecodedFrame


_MAVI_ORDINAL_KEY = "mavi_ordinal"


@dataclass(frozen=True, slots=True)
class _ByteTrackBindings:
    tracker_factory: Callable[..., object]
    detections_factory: Callable[..., object]


@dataclass(frozen=True, slots=True)
class _TrackedRow:
    native_tracker_id: int
    detection: DetectionCandidate


def _load_bytetrack_bindings() -> _ByteTrackBindings:
    # Imports remain inside the loader so the core worker can be imported and its
    # non-runtime tests can run without the optional qualified vision graph.
    from trackers import ByteTrackTracker as NativeByteTrackTracker
    from supervision import Detections

    return _ByteTrackBindings(
        tracker_factory=NativeByteTrackTracker,
        detections_factory=Detections,
    )


class ByteTrackTracker:
    """Attempt-scoped Trackers-2.6 ByteTrack adapter.

    Person and Vehicle detections are tracked in completely independent native
    association domains. MAVI evidence is always recovered from the original
    detection by the round-tripped frame ordinal; native boxes/confidences and
    native output row order never become authoritative evidence.
    """

    def __init__(self, profile: ByteTrackProfile) -> None:
        self._profile = profile
        try:
            bindings = _load_bytetrack_bindings()
            native_parameters = self._native_parameters(profile)
            self._person_tracker = bindings.tracker_factory(**native_parameters)
            self._vehicle_tracker = bindings.tracker_factory(**native_parameters)
        except Exception:
            raise TrackerError("bytetrack_backend_initialization_failed") from None

        self._bindings = bindings
        self._person_native_to_mavi: dict[int, str] = {}
        self._vehicle_native_to_mavi: dict[int, str] = {}
        self._person_counter = 0
        self._vehicle_counter = 0
        self._last_source_frame_number: int | None = None
        self._last_offset_ms: int | None = None

    @staticmethod
    def _native_parameters(profile: ByteTrackProfile) -> dict[str, int | float]:
        return {
            "frame_rate": profile.reference_frame_rate,
            "lost_track_buffer": profile.lost_track_buffer,
            "track_activation_threshold": profile.track_activation_threshold,
            "high_conf_det_threshold": profile.high_confidence_threshold,
            "minimum_iou_threshold": profile.minimum_iou_threshold,
            "minimum_consecutive_frames": profile.minimum_consecutive_frames,
        }

    def update(
        self,
        frame: DecodedFrame,
        detections: Sequence[DetectionCandidate],
    ) -> tuple[TrackCandidate, ...]:
        try:
            materialized = tuple(detections)
        except Exception:
            raise TrackerError("bytetrack_detection_sequence_invalid") from None

        self._validate_frame_and_inputs(frame, materialized)

        person_detections = tuple(
            detection
            for detection in materialized
            if detection.object_class is ObjectClass.PERSON
        )
        vehicle_detections = tuple(
            detection
            for detection in materialized
            if detection.object_class is ObjectClass.VEHICLE
        )

        timestamp_seconds = frame.offset_ms / 1000.0

        # Both native domains are advanced on every accepted frame, including
        # class-empty frames, so timestamp anchors and lost-track ageing remain
        # consistent and independent.
        person_rows = self._update_class(
            self._person_tracker,
            frame,
            person_detections,
            timestamp_seconds,
        )
        vehicle_rows = self._update_class(
            self._vehicle_tracker,
            frame,
            vehicle_detections,
            timestamp_seconds,
        )

        outputs: list[tuple[int, TrackCandidate]] = []
        outputs.extend(
            self._materialize_class_outputs(
                ObjectClass.PERSON,
                person_rows,
                self._person_native_to_mavi,
            )
        )
        outputs.extend(
            self._materialize_class_outputs(
                ObjectClass.VEHICLE,
                vehicle_rows,
                self._vehicle_native_to_mavi,
            )
        )

        # Advance accepted-frame state only after both native domains completed
        # and their outputs passed the complete backend contract validation.
        self._last_source_frame_number = frame.source_frame_number
        self._last_offset_ms = frame.offset_ms

        outputs.sort(key=lambda item: item[0])
        return tuple(candidate for _, candidate in outputs)

    def _validate_frame_and_inputs(
        self,
        frame: DecodedFrame,
        detections: tuple[DetectionCandidate, ...],
    ) -> None:
        height, width, _ = frame.image.shape
        if width <= 0 or height <= 0:
            raise TrackerError("bytetrack_frame_geometry_invalid")
        if (
            self._last_source_frame_number is not None
            and frame.source_frame_number <= self._last_source_frame_number
        ):
            raise TrackerError("bytetrack_frame_number_non_monotonic")
        if self._last_offset_ms is not None and frame.offset_ms <= self._last_offset_ms:
            raise TrackerError("bytetrack_frame_offset_non_monotonic")

        ordinals: set[int] = set()
        for detection in detections:
            if not isinstance(detection, DetectionCandidate):
                raise TrackerError("bytetrack_detection_candidate_invalid")
            if detection.object_class not in (ObjectClass.PERSON, ObjectClass.VEHICLE):
                raise TrackerError("bytetrack_object_class_invalid")
            if detection.frame_ordinal in ordinals:
                raise TrackerError("bytetrack_frame_ordinal_duplicate")
            ordinals.add(detection.frame_ordinal)

    def _update_class(
        self,
        native_tracker: object,
        frame: DecodedFrame,
        detections: tuple[DetectionCandidate, ...],
        timestamp_seconds: float,
    ) -> tuple[_TrackedRow, ...]:
        native_detections = self._build_native_detections(frame, detections)
        try:
            tracked = native_tracker.update(
                native_detections,
                timestamp=timestamp_seconds,
            )
        except Exception:
            raise TrackerError("bytetrack_backend_update_failed") from None

        # Empty input is intentionally advanced but can never create MAVI
        # evidence. This also prevents predicted-only native rows from leaking.
        if not detections:
            return ()

        tracker_ids = self._require_integral_vector(
            getattr(tracked, "tracker_id", None),
            expected_length=len(detections),
            code="bytetrack_tracker_id_contract_invalid",
        )
        data = getattr(tracked, "data", None)
        if not isinstance(data, Mapping):
            raise TrackerError("bytetrack_ordinal_contract_invalid")
        ordinals = self._require_integral_vector(
            data.get(_MAVI_ORDINAL_KEY),
            expected_length=len(detections),
            code="bytetrack_ordinal_contract_invalid",
        )

        input_by_ordinal = {
            detection.frame_ordinal: detection for detection in detections
        }
        output_ordinal_values = [int(value) for value in ordinals]
        if len(set(output_ordinal_values)) != len(output_ordinal_values):
            raise TrackerError("bytetrack_ordinal_contract_invalid")
        if set(output_ordinal_values) != set(input_by_ordinal):
            raise TrackerError("bytetrack_ordinal_contract_invalid")

        native_ids = [int(value) for value in tracker_ids]
        if any(native_id < -1 for native_id in native_ids):
            raise TrackerError("bytetrack_tracker_id_contract_invalid")
        confirmed_ids = [native_id for native_id in native_ids if native_id >= 0]
        if len(set(confirmed_ids)) != len(confirmed_ids):
            raise TrackerError("bytetrack_tracker_id_contract_invalid")

        return tuple(
            _TrackedRow(
                native_tracker_id=native_id,
                detection=input_by_ordinal[ordinal],
            )
            for native_id, ordinal in zip(native_ids, output_ordinal_values, strict=True)
            if native_id >= 0
        )

    def _build_native_detections(
        self,
        frame: DecodedFrame,
        detections: tuple[DetectionCandidate, ...],
    ) -> object:
        height, width, _ = frame.image.shape
        xyxy: NDArray[np.float64] = np.empty((len(detections), 4), dtype=np.float64)
        confidence: NDArray[np.float64] = np.empty((len(detections),), dtype=np.float64)
        ordinals: NDArray[np.int64] = np.empty((len(detections),), dtype=np.int64)

        for index, detection in enumerate(detections):
            box = detection.bounding_box
            xyxy[index] = (
                box.x * width,
                box.y * height,
                (box.x + box.width) * width,
                (box.y + box.height) * height,
            )
            confidence[index] = detection.confidence
            ordinals[index] = detection.frame_ordinal

        try:
            return self._bindings.detections_factory(
                xyxy=xyxy,
                confidence=confidence,
                data={_MAVI_ORDINAL_KEY: ordinals},
            )
        except Exception:
            raise TrackerError("bytetrack_detection_conversion_failed") from None

    @staticmethod
    def _require_integral_vector(
        value: object,
        *,
        expected_length: int,
        code: str,
    ) -> NDArray[np.integer]:
        if value is None:
            raise TrackerError(code)
        try:
            array = np.asarray(value)
        except Exception:
            raise TrackerError(code) from None
        if (
            array.ndim != 1
            or len(array) != expected_length
            or array.dtype.kind not in {"i", "u"}
        ):
            raise TrackerError(code)
        return array

    def _materialize_class_outputs(
        self,
        object_class: ObjectClass,
        rows: tuple[_TrackedRow, ...],
        native_to_mavi: dict[int, str],
    ) -> list[tuple[int, TrackCandidate]]:
        new_rows = [
            row for row in rows if row.native_tracker_id not in native_to_mavi
        ]
        new_rows.sort(key=self._new_identity_sort_key)

        for row in new_rows:
            if object_class is ObjectClass.PERSON:
                self._person_counter += 1
                counter = self._person_counter
            else:
                self._vehicle_counter += 1
                counter = self._vehicle_counter
            native_to_mavi[row.native_tracker_id] = (
                f"{object_class.value}-{counter:06d}"
            )

        return [
            (
                row.detection.frame_ordinal,
                TrackCandidate(
                    track_id=native_to_mavi[row.native_tracker_id],
                    object_class=object_class,
                    confidence=row.detection.confidence,
                    bounding_box=row.detection.bounding_box,
                ),
            )
            for row in rows
        ]

    @staticmethod
    def _new_identity_sort_key(
        row: _TrackedRow,
    ) -> tuple[float, float, float, float, float, int]:
        box = row.detection.bounding_box
        return (
            box.x,
            box.y,
            box.width,
            box.height,
            -row.detection.confidence,
            row.detection.frame_ordinal,
        )
