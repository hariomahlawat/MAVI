from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.runtime.errors import InferenceContractError, ProcessingDependencyError
from mavi_vision.runtime.interfaces import DetectorRuntime
from mavi_vision.runtime.profile import PipelineProfile
from mavi_vision.video.reader import DecodedFrame


def _finite_number(value: object, *, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise InferenceContractError(code)
    number = float(value)
    if not isfinite(number):
        raise InferenceContractError(code)
    # IEEE-754 signed zero compares equal but serializes differently. Normalize
    # it before any canonical sort/ordinal assignment so backend ordering cannot
    # leak into deterministic MAVI output.
    return 0.0 if number == 0.0 else number


class RTMDetDetector:
    """Normalize framework-neutral RTMDet outputs into deterministic MAVI detections."""

    def __init__(self, runtime: DetectorRuntime, profile: PipelineProfile) -> None:
        self._runtime = runtime
        self._profile = profile

        metadata = runtime.metadata
        if metadata.model_id != profile.model_id:
            raise InferenceContractError("runtime_model_profile_mismatch")

        allowed = tuple(profile.allowed_source_classes)
        allowed_set = set(allowed)
        if len(allowed_set) != len(allowed):
            raise InferenceContractError("profile_allowed_classes_invalid")

        mapping_keys = set(profile.class_mapping)
        if mapping_keys != allowed_set:
            raise InferenceContractError("profile_class_mapping_invalid")

        runtime_vocabulary = tuple(metadata.ordered_class_vocabulary)
        runtime_vocabulary_set = set(runtime_vocabulary)
        if any(source_class not in runtime_vocabulary_set for source_class in allowed):
            raise InferenceContractError("profile_runtime_vocabulary_mismatch")

        self._runtime_vocabulary = frozenset(runtime_vocabulary_set)
        self._allowed_source_classes = frozenset(allowed_set)

    def detect(self, frame: DecodedFrame) -> tuple[DetectionCandidate, ...]:
        height, width, _ = frame.image.shape
        if height <= 0 or width <= 0:
            raise InferenceContractError("frame_geometry_invalid")

        try:
            raw_output = self._runtime.infer(frame.image)
        except ProcessingDependencyError:
            raise

        try:
            raw_detections = tuple(raw_output)
        except TypeError as exc:
            raise InferenceContractError("runtime_detection_sequence_invalid") from exc

        normalized: list[DetectionCandidate] = []
        for raw in raw_detections:
            parsed = self._parse_raw_detection(raw)

            # Classes that are valid for the verified detector vocabulary but are
            # outside the selected pipeline profile are intentionally ignored.
            if parsed.source_class not in self._allowed_source_classes:
                continue

            clipped = self._clip_and_normalize(
                parsed.x1,
                parsed.y1,
                parsed.x2,
                parsed.y2,
                frame_width=width,
                frame_height=height,
            )
            if clipped is None:
                continue

            object_class = self._profile.class_mapping.get(parsed.source_class)
            if object_class is None:
                raise InferenceContractError("profile_class_mapping_invalid")

            try:
                candidate = DetectionCandidate(
                    object_class=object_class,
                    confidence=parsed.confidence,
                    bounding_box=clipped,
                    frame_ordinal=0,
                )
            except ValueError as exc:
                raise InferenceContractError("detection_candidate_invalid") from exc

            normalized.append(candidate)

        normalized.sort(
            key=lambda candidate: (
                candidate.object_class.value,
                -candidate.confidence,
                candidate.bounding_box.x,
                candidate.bounding_box.y,
                candidate.bounding_box.width,
                candidate.bounding_box.height,
            )
        )

        return tuple(
            DetectionCandidate(
                object_class=candidate.object_class,
                confidence=candidate.confidence,
                bounding_box=candidate.bounding_box,
                frame_ordinal=ordinal,
            )
            for ordinal, candidate in enumerate(normalized)
        )

    def _parse_raw_detection(self, raw: object) -> "_ParsedRawDetection":
        if raw is None:
            raise InferenceContractError("raw_detection_invalid")

        source_class = getattr(raw, "source_class", None)
        if not isinstance(source_class, str) or not source_class or source_class != source_class.strip():
            raise InferenceContractError("raw_detection_source_class_invalid")

        confidence = _finite_number(
            getattr(raw, "confidence", None),
            code="raw_detection_confidence_invalid",
        )
        if confidence < 0.0 or confidence > 1.0:
            raise InferenceContractError("raw_detection_confidence_invalid")

        if source_class not in self._runtime_vocabulary:
            raise InferenceContractError("raw_detection_vocabulary_violation")

        bounding_box = getattr(raw, "bounding_box", None)
        if bounding_box is None:
            raise InferenceContractError("raw_detection_bbox_invalid")

        x1 = _finite_number(
            getattr(bounding_box, "x1", None),
            code="raw_detection_bbox_non_finite",
        )
        y1 = _finite_number(
            getattr(bounding_box, "y1", None),
            code="raw_detection_bbox_non_finite",
        )
        x2 = _finite_number(
            getattr(bounding_box, "x2", None),
            code="raw_detection_bbox_non_finite",
        )
        y2 = _finite_number(
            getattr(bounding_box, "y2", None),
            code="raw_detection_bbox_non_finite",
        )

        if x2 < x1 or y2 < y1:
            raise InferenceContractError("raw_detection_bbox_inverted")

        return _ParsedRawDetection(
            source_class=source_class,
            confidence=confidence,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
        )

    @staticmethod
    def _clip_and_normalize(
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        frame_width: int,
        frame_height: int,
    ) -> NormalizedBoundingBox | None:
        clipped_x1 = min(max(x1, 0.0), float(frame_width))
        clipped_y1 = min(max(y1, 0.0), float(frame_height))
        clipped_x2 = min(max(x2, 0.0), float(frame_width))
        clipped_y2 = min(max(y2, 0.0), float(frame_height))

        if clipped_x2 <= clipped_x1 or clipped_y2 <= clipped_y1:
            return None

        left = clipped_x1 / frame_width
        top = clipped_y1 / frame_height
        right = clipped_x2 / frame_width
        bottom = clipped_y2 / frame_height

        # Bound width/height by the remaining unit interval. This avoids a
        # floating-point round-off artifact from making x+width or y+height
        # microscopically greater than 1.0 for an otherwise valid clipped box.
        normalized_width = min(right - left, 1.0 - left)
        normalized_height = min(bottom - top, 1.0 - top)

        try:
            return NormalizedBoundingBox(
                x=left,
                y=top,
                width=normalized_width,
                height=normalized_height,
            )
        except ValueError as exc:
            raise InferenceContractError(
                "normalized_detection_geometry_invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class _ParsedRawDetection:
    source_class: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
