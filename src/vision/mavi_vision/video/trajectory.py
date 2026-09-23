from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence

import msgpack

from mavi_vision.common.analytical import TrajectoryPoint


# Points encoded per yielded buffer. It bounds the encoder's output buffer
# (a v1 point is at most 28 bytes) without making the caller handle one tiny
# bytes object per point.
_ENCODE_BATCH_POINTS = 4096


def _validate_monotonic(points: Sequence[TrajectoryPoint]) -> None:
    offsets = [point.offset_ms for point in points]
    if any(current <= previous for previous, current in zip(offsets, offsets[1:])):
        raise ValueError("trajectory_offsets_not_monotonic")


def trajectory_v1_header(point_count: int) -> bytes:
    """Return the canonical v1 bytes that precede the first point.

    ``msgpack.packb({"v": 1, "points": [...]})`` writes a two-entry map, the
    key ``"v"``, ``1``, the key ``"points"`` and an array header whose width
    depends on the point count (fixarray, array16 or array32). This asks the
    same packer for the same header, so the rule cannot drift from msgpack's.
    """
    if isinstance(point_count, bool) or not isinstance(point_count, int):
        raise TypeError("trajectory_point_count_invalid")
    if point_count < 0:
        raise ValueError("trajectory_point_count_invalid")
    packer = msgpack.Packer(use_bin_type=True, autoreset=False)
    packer.pack_map_header(2)
    packer.pack("v")
    packer.pack(1)
    packer.pack("points")
    packer.pack_array_header(point_count)
    return packer.bytes()


def iter_trajectory_v1(
    point_count: int,
    points: Iterable[tuple[int, float, float]],
) -> Iterator[bytes]:
    """Stream the canonical trajectory-v1 bytes for exactly ``point_count`` points.

    The concatenation of the yielded buffers is byte-for-byte what
    ``serialize_trajectory`` returns for the same points: msgpack encodes each
    array element independently of its neighbours, so the header followed by
    each ``[offset, x, y]`` packed on its own is the one-shot encoding. Values are
    packed as given (a Python float is always float64), so no precision is lost.

    It fails closed rather than emit a payload that disagrees with its own
    header: fewer or more points than ``point_count``, or offsets that are not
    strictly increasing, raise before the offending bytes are yielded.
    """
    yield trajectory_v1_header(point_count)
    packer = msgpack.Packer(use_bin_type=True, autoreset=False)
    emitted = 0
    batched = 0
    previous: int | None = None
    for offset_ms, center_x, center_y in points:
        if emitted == point_count:
            raise ValueError("trajectory_point_count_mismatch")
        if previous is not None and offset_ms <= previous:
            raise ValueError("trajectory_offsets_not_monotonic")
        previous = offset_ms
        packer.pack([offset_ms, center_x, center_y])
        emitted += 1
        batched += 1
        if batched == _ENCODE_BATCH_POINTS:
            yield packer.bytes()
            packer.reset()
            batched = 0
    if emitted != point_count:
        raise ValueError("trajectory_point_count_mismatch")
    if batched:
        yield packer.bytes()


def serialize_trajectory(points: Sequence[TrajectoryPoint]) -> bytes:
    point_tuple = tuple(points)
    _validate_monotonic(point_tuple)
    return b"".join(
        iter_trajectory_v1(
            len(point_tuple),
            (
                (point.offset_ms, point.center_x, point.center_y)
                for point in point_tuple
            ),
        )
    )


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
