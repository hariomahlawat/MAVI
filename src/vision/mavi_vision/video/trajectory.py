from __future__ import annotations

from collections.abc import Sequence

import msgpack

from mavi_vision.common.analytical import TrajectoryPoint


def _validate_monotonic(points: Sequence[TrajectoryPoint]) -> None:
    offsets = [point.offset_ms for point in points]
    if any(current <= previous for previous, current in zip(offsets, offsets[1:])):
        raise ValueError("trajectory_offsets_not_monotonic")


def serialize_trajectory(points: Sequence[TrajectoryPoint]) -> bytes:
    point_tuple = tuple(points)
    _validate_monotonic(point_tuple)
    payload = {
        "v": 1,
        "points": [
            [point.offset_ms, point.center_x, point.center_y] for point in point_tuple
        ],
    }
    return msgpack.packb(payload, use_bin_type=True)


def deserialize_trajectory(payload: bytes) -> tuple[TrajectoryPoint, ...]:
    try:
        unpacked = msgpack.unpackb(
            payload,
            raw=False,
            strict_map_key=True,
        )
        if not isinstance(unpacked, dict) or set(unpacked) != {"v", "points"}:
            raise ValueError
        if unpacked["v"] != 1 or not isinstance(unpacked["points"], list):
            raise ValueError

        points: list[TrajectoryPoint] = []
        for item in unpacked["points"]:
            if (
                not isinstance(item, list)
                or len(item) != 3
                or isinstance(item[0], bool)
                or not isinstance(item[0], int)
                or isinstance(item[1], bool)
                or not isinstance(item[1], (int, float))
                or isinstance(item[2], bool)
                or not isinstance(item[2], (int, float))
            ):
                raise ValueError
            points.append(
                TrajectoryPoint(
                    offset_ms=item[0],
                    center_x=float(item[1]),
                    center_y=float(item[2]),
                )
            )
        result = tuple(points)
        _validate_monotonic(result)
        return result
    except (msgpack.ExtraData, msgpack.FormatError, msgpack.StackError, ValueError, TypeError, OverflowError):
        raise ValueError("trajectory_payload_invalid") from None
