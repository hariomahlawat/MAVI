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


def _frame_offset_ms(
    pts: int | None,
    time_base: object | None,
    frame_number: int,
    frame_rate_num: int,
    frame_rate_den: int,
    *,
    origin_pts: int | None,
) -> int:
    if pts is not None and origin_pts is not None:
        rational_time_base = _as_fraction(time_base)
        if rational_time_base is not None and rational_time_base > 0:
            offset = _round_fraction_nearest(
                Fraction(pts - origin_pts) * rational_time_base * 1000
            )
            if offset < 0:
                raise VideoReadError("frame_timestamp_unavailable")
            return offset

    if frame_number >= 0 and frame_rate_num > 0 and frame_rate_den > 0:
        return _round_fraction_nearest(
            Fraction(frame_number * 1000 * frame_rate_den, frame_rate_num)
        )

    raise VideoReadError("frame_timestamp_unavailable")


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

        origin_pts: int | None = None
        try:
            for frame_number, frame in enumerate(container.decode(stream)):
                time_base = frame.time_base if frame.time_base is not None else stream.time_base
                rational_time_base = _as_fraction(time_base)
                if (
                    origin_pts is None
                    and frame.pts is not None
                    and rational_time_base is not None
                    and rational_time_base > 0
                ):
                    origin_pts = frame.pts
                offset_ms = _frame_offset_ms(
                    frame.pts,
                    time_base,
                    frame_number,
                    frame_rate_num,
                    frame_rate_den,
                    origin_pts=origin_pts,
                )
                image = np.ascontiguousarray(frame.to_ndarray(format="rgb24"), dtype=np.uint8)
                yield DecodedFrame(frame_number, offset_ms, image)
        except VideoReadError:
            raise
        except (av.error.FFmpegError, OSError, ValueError) as exc:
            raise VideoReadError("video_decode_failed") from exc
