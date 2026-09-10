from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO, Iterator

import av
import numpy as np
from numpy.typing import NDArray


class VideoReadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    source_frame_number: int
    offset_ms: int
    image: NDArray[np.uint8]

    def __post_init__(self) -> None:
        if self.source_frame_number < 0:
            raise ValueError("source_frame_number_invalid")
        if self.offset_ms < 0:
            raise ValueError("frame_offset_invalid")
        if (
            not isinstance(self.image, np.ndarray)
            or self.image.dtype != np.uint8
            or self.image.ndim != 3
            or self.image.shape[2] != 3
        ):
            raise ValueError("frame_image_invalid")


def _round_fraction_nearest(value: Fraction) -> int:
    numerator = value.numerator
    denominator = value.denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def _as_fraction(value: object) -> Fraction | None:
    if value is None:
        return None
    if isinstance(value, Fraction):
        return value
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if isinstance(numerator, int) and isinstance(denominator, int) and denominator:
        return Fraction(numerator, denominator)
    try:
        return Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _frame_duration_ms(
    frame_rate_num: int,
    frame_rate_den: int,
) -> Fraction | None:
    if frame_rate_num <= 0 or frame_rate_den <= 0:
        return None
    return Fraction(1000 * frame_rate_den, frame_rate_num)


def _fallback_offset_ms(
    frame_number: int,
    frame_rate_num: int,
    frame_rate_den: int,
) -> int | None:
    duration = _frame_duration_ms(frame_rate_num, frame_rate_den)
    if frame_number < 0 or duration is None:
        return None
    return _round_fraction_nearest(Fraction(frame_number) * duration)


def _frame_offset_ms(
    pts: int | None,
    time_base: object | None,
    frame_number: int,
    frame_rate_num: int,
    frame_rate_den: int,
    *,
    origin_pts: int | None,
    origin_offset_ms: int = 0,
) -> int:
    if pts is not None and origin_pts is not None:
        rational_time_base = _as_fraction(time_base)
        if rational_time_base is not None and rational_time_base > 0:
            offset = origin_offset_ms + _round_fraction_nearest(
                Fraction(pts - origin_pts) * rational_time_base * 1000
            )
            if offset < 0:
                raise VideoReadError("frame_timestamp_unavailable")
            return offset

    fallback = _fallback_offset_ms(frame_number, frame_rate_num, frame_rate_den)
    if fallback is not None:
        return fallback

    raise VideoReadError("frame_timestamp_unavailable")


class _MediaTimeline:
    """Resolve decoded frames onto one strict media-relative integer-ms timeline."""

    def __init__(self, frame_rate_num: int, frame_rate_den: int) -> None:
        self._frame_duration_ms = _frame_duration_ms(frame_rate_num, frame_rate_den)
        self._origin_presentation_ms: Fraction | None = None
        self._origin_offset_ms: Fraction | None = None
        self._last_exact_ms: Fraction | None = None
        self._last_emitted_ms: int | None = None
        self._last_frame_number: int | None = None

    def resolve(
        self,
        frame_number: int,
        pts: int | None,
        time_base: object | None,
    ) -> int:
        if frame_number < 0:
            raise VideoReadError("frame_timestamp_unavailable")
        if self._last_frame_number is not None and frame_number <= self._last_frame_number:
            raise VideoReadError("frame_timestamp_non_monotonic")

        rational_time_base = _as_fraction(time_base)
        usable_pts = (
            pts is not None
            and rational_time_base is not None
            and rational_time_base > 0
        )

        if usable_pts:
            presentation_ms = Fraction(pts) * rational_time_base * 1000
            if self._origin_presentation_ms is None:
                anchor = (
                    Fraction(0)
                    if self._last_exact_ms is None
                    else self._predicted_fallback_exact(frame_number)
                )
                self._origin_presentation_ms = presentation_ms
                self._origin_offset_ms = anchor
            assert self._origin_offset_ms is not None
            exact_ms = (
                self._origin_offset_ms
                + presentation_ms
                - self._origin_presentation_ms
            )
        else:
            exact_ms = self._predicted_fallback_exact(frame_number)

        if exact_ms < 0:
            raise VideoReadError("frame_timestamp_unavailable")
        if self._last_exact_ms is not None and exact_ms <= self._last_exact_ms:
            raise VideoReadError("frame_timestamp_non_monotonic")

        emitted_ms = _round_fraction_nearest(exact_ms)
        if self._last_emitted_ms is not None and emitted_ms <= self._last_emitted_ms:
            emitted_ms = self._last_emitted_ms + 1

        self._last_exact_ms = exact_ms
        self._last_emitted_ms = emitted_ms
        self._last_frame_number = frame_number
        return emitted_ms

    def _predicted_fallback_exact(self, frame_number: int) -> Fraction:
        if self._frame_duration_ms is None:
            raise VideoReadError("frame_timestamp_unavailable")
        if self._last_exact_ms is None or self._last_frame_number is None:
            return Fraction(frame_number) * self._frame_duration_ms
        frame_delta = frame_number - self._last_frame_number
        if frame_delta <= 0:
            raise VideoReadError("frame_timestamp_non_monotonic")
        return self._last_exact_ms + Fraction(frame_delta) * self._frame_duration_ms


def iter_frames(source: Path | BinaryIO) -> Iterator[DecodedFrame]:
    try:
        container = av.open(source if hasattr(source, "read") else str(source), mode="r")
    except (av.error.FFmpegError, OSError) as exc:
        raise VideoReadError("video_open_failed") from exc

    with container:
        streams = list(container.streams.video)
        if len(streams) != 1:
            raise VideoReadError("video_stream_invalid")
        stream = streams[0]
        average_rate = _as_fraction(stream.average_rate)
        if average_rate is None or average_rate <= 0:
            frame_rate_num = 0
            frame_rate_den = 1
        else:
            frame_rate_num = average_rate.numerator
            frame_rate_den = average_rate.denominator

        timeline = _MediaTimeline(frame_rate_num, frame_rate_den)
        try:
            for frame_number, frame in enumerate(container.decode(stream)):
                time_base = frame.time_base if frame.time_base is not None else stream.time_base
                offset_ms = timeline.resolve(
                    frame_number,
                    frame.pts,
                    time_base,
                )
                image = np.ascontiguousarray(frame.to_ndarray(format="rgb24"), dtype=np.uint8)
                yield DecodedFrame(frame_number, offset_ms, image)
        except VideoReadError:
            raise
        except (av.error.FFmpegError, OSError, ValueError) as exc:
            raise VideoReadError("video_decode_failed") from exc
