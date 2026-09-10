from __future__ import annotations

import msgpack
import pytest

from mavi_vision.common.analytical import TrajectoryPoint
from mavi_vision.video.trajectory import deserialize_trajectory, serialize_trajectory


def test_trajectory_serialization_is_deterministic_and_round_trips() -> None:
    points = (
        TrajectoryPoint(0, 0.2, 0.3),
        TrajectoryPoint(100, 0.25, 0.35),
    )

    first = serialize_trajectory(points)
    second = serialize_trajectory(points)

    assert first == second
    assert deserialize_trajectory(first) == points
    assert msgpack.unpackb(first, raw=False) == {
        "v": 1,
        "points": [[0, 0.2, 0.3], [100, 0.25, 0.35]],
    }


def test_trajectory_serializer_requires_strictly_monotonic_offsets() -> None:
    with pytest.raises(ValueError, match="trajectory_offsets_not_monotonic"):
        serialize_trajectory(
            (TrajectoryPoint(100, 0.2, 0.3), TrajectoryPoint(100, 0.3, 0.4))
        )


def test_trajectory_deserializer_rejects_malformed_payloads() -> None:
    malformed = (
        b"not-msgpack",
        msgpack.packb({"v": 2, "points": []}, use_bin_type=True),
        msgpack.packb({"v": 1, "points": [[0, 1.2, 0.2]]}, use_bin_type=True),
        msgpack.packb({"v": 1, "points": [[100, 0.2, 0.2], [50, 0.2, 0.2]]}, use_bin_type=True),
    )

    for payload in malformed:
        with pytest.raises(ValueError, match="trajectory_payload_invalid"):
            deserialize_trajectory(payload)
