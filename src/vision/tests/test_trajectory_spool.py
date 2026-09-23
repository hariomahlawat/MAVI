from __future__ import annotations

import random

import msgpack
import pytest

from mavi_vision.common.analytical import TrajectoryPoint
from mavi_vision.video.trajectory import (
    iter_trajectory_v1,
    serialize_trajectory,
    trajectory_v1_header,
)


# Array-header widths (fixarray / array16 / array32), both sides of every
# boundary, the encoder's batch size, and a multi-batch count.
BOUNDARY_COUNTS = (
    0, 1, 2, 15, 16, 17, 255, 256,
    4095, 4096, 4097, 8192, 65535, 65536, 70000,
)


def _reference_v1(points: tuple[TrajectoryPoint, ...]) -> bytes:
    """The pre-S1.2b serializer body, verbatim: the byte-identity oracle."""
    payload = {
        "v": 1,
        "points": [
            [point.offset_ms, point.center_x, point.center_y] for point in points
        ],
    }
    return msgpack.packb(payload, use_bin_type=True)


def _random_points(count: int, seed: int) -> tuple[TrajectoryPoint, ...]:
    rng = random.Random(seed)
    offset = rng.randrange(0, 1000)
    points: list[TrajectoryPoint] = []
    for _ in range(count):
        points.append(TrajectoryPoint(offset, rng.random(), rng.random()))
        offset += rng.randrange(1, 400)
    return tuple(points)


def _tuples(points: tuple[TrajectoryPoint, ...]) -> list[tuple[int, float, float]]:
    return [(p.offset_ms, p.center_x, p.center_y) for p in points]


@pytest.mark.parametrize("count", BOUNDARY_COUNTS)
def test_streamed_v1_bytes_identical_to_reference_serializer(count: int) -> None:
    points = _random_points(count, seed=count)
    reference = _reference_v1(points)

    streamed = b"".join(iter_trajectory_v1(count, _tuples(points)))

    assert streamed == reference
    assert serialize_trajectory(points) == reference


def test_extreme_values_keep_exact_encoding() -> None:
    # Integer offsets across every msgpack integer width, and float64 values a
    # float32 or decimal round trip would change.
    offsets = (0, 127, 128, 255, 256, 65535, 65536, 2**32 - 1, 2**32, 2**53 + 1, 2**63 - 1)
    coords = (0.0, -0.0, 1.0, 5e-324, 0.1, 1 / 3, 0.9999999999999999, 2.2250738585072014e-308)
    points = tuple(
        TrajectoryPoint(offset, coords[i % len(coords)], coords[(i + 3) % len(coords)])
        for i, offset in enumerate(offsets)
    )
    # Integer centres are legal TrajectoryPoints and must stay integers on the wire.
    points += (TrajectoryPoint(2**63, 0, 1),)

    streamed = b"".join(iter_trajectory_v1(len(points), _tuples(points)))

    assert streamed == _reference_v1(points)
    decoded = msgpack.unpackb(streamed, raw=False)["points"]
    assert [tuple(item) for item in decoded] == _tuples(points)


@pytest.mark.parametrize("count", BOUNDARY_COUNTS)
def test_header_matches_the_one_shot_prefix(count: int) -> None:
    reference = _reference_v1(_random_points(count, seed=7))

    header = trajectory_v1_header(count)

    assert reference.startswith(header)
    # fixmap(2) + "v" + 1 + "points" is 11 bytes; then the array header.
    assert len(header) == 11 + (1 if count < 16 else 3 if count < 65536 else 5)


def test_encoder_yields_bounded_buffers() -> None:
    count = 70000
    buffers = list(iter_trajectory_v1(count, _tuples(_random_points(count, seed=3))))

    # Header, then one buffer per 4096 points: never one buffer for the Track.
    assert len(buffers) == 1 + -(-count // 4096)
    assert max(len(buffer) for buffer in buffers[1:]) <= 4096 * 28


@pytest.mark.parametrize(
    ("declared", "actual"),
    [(3, 2), (2, 3), (0, 1), (1, 0)],
)
def test_point_count_mismatch_fails_closed(declared: int, actual: int) -> None:
    points = _tuples(_random_points(actual, seed=1))

    with pytest.raises(ValueError, match="trajectory_point_count_mismatch"):
        b"".join(iter_trajectory_v1(declared, points))


@pytest.mark.parametrize("second_offset", [100, 99])
def test_non_increasing_offsets_fail_closed(second_offset: int) -> None:
    points = [(100, 0.1, 0.1), (second_offset, 0.2, 0.2)]

    with pytest.raises(ValueError, match="trajectory_offsets_not_monotonic"):
        b"".join(iter_trajectory_v1(2, points))


@pytest.mark.parametrize("count", [-1, True, 1.0])
def test_header_rejects_invalid_counts(count: object) -> None:
    with pytest.raises((TypeError, ValueError), match="trajectory_point_count_invalid"):
        trajectory_v1_header(count)  # type: ignore[arg-type]
