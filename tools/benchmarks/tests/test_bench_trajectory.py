"""Trajectory artefact decoding (S3.2d-1 slice 2; format v1)."""

from __future__ import annotations

import msgpack
import pytest

from tools.benchmarks.capabilities.vehicle_tracks import trajectory as t
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error

POINTS = [[0, 0.25, 0.5], [200, 0.3, 0.5], [400, 1, 0]]


def pack(document) -> bytes:
    return msgpack.packb(document, use_bin_type=True)


def refused(code: str):
    return pytest.raises(S32Error, match=f"^{code}")


def test_valid_trajectory_decodes_exactly():
    assert t.decode(pack({"v": 1, "points": POINTS})) == ((0, 0.25, 0.5), (200, 0.3, 0.5), (400, 1.0, 0.0))


def test_decoding_is_deterministic():
    data = pack({"v": 1, "points": POINTS})
    assert t.decode(data) == t.decode(bytes(data))


def test_agrees_with_the_vision_writer():
    vision = pytest.importorskip("mavi_vision.video.trajectory")
    analytical = pytest.importorskip("mavi_vision.common.analytical")
    points = [analytical.TrajectoryPoint(offset_ms=o, center_x=x, center_y=y) for o, x, y in
              [(0, 0.1, 0.2), (33, 0.11, 0.21), (67, 0.125, 0.22)]]
    data = vision.serialize_trajectory(points)
    assert t.decode(data) == tuple((p.offset_ms, p.center_x, p.center_y) for p in points)
    assert tuple(vision.deserialize_trajectory(data)) == tuple(points)


@pytest.mark.parametrize("data, code", [
    (pack({"v": 2, "points": POINTS}), "trajectory_format_unsupported"),
    (pack({"v": True, "points": POINTS}), "trajectory_format_unsupported"),
    (pack({"v": 1}), "trajectory_invalid:fields"),
    (pack({"v": 1, "points": POINTS, "extra": 0}), "trajectory_invalid:fields"),
    (pack([1, POINTS]), "trajectory_invalid:fields"),
    (b"\xc1", "trajectory_invalid:malformed"),
    (pack({"v": 1, "points": POINTS}) + b"\x00", "trajectory_invalid:malformed"),
    (pack({"v": 1, "points": POINTS})[:-3], "trajectory_invalid:malformed"),
    (pack({1: 1, "points": POINTS}), "trajectory_invalid:malformed"),
    (pack({"v": 1, "points": "abc"}), "trajectory_invalid:points"),
    (pack({"v": 1, "points": []}), "trajectory_invalid:points"),
    (pack({"v": 1, "points": [[0, 0.1]]}), "trajectory_invalid:point"),
    (pack({"v": 1, "points": [[0, 0.1, 0.2, 0.3]]}), "trajectory_invalid:point"),
    (pack({"v": 1, "points": [{"o": 0}]}), "trajectory_invalid:point"),
    (pack({"v": 1, "points": [[0.5, 0.1, 0.2]]}), "trajectory_invalid:offset"),
    (pack({"v": 1, "points": [[True, 0.1, 0.2]]}), "trajectory_invalid:offset"),
    (pack({"v": 1, "points": [[-1, 0.1, 0.2]]}), "trajectory_invalid:offset"),
    (pack({"v": 1, "points": [[0, "0.1", 0.2]]}), "trajectory_invalid:centre"),
    (pack({"v": 1, "points": [[0, None, 0.2]]}), "trajectory_invalid:centre"),
    (pack({"v": 1, "points": [[0, 0.1, False]]}), "trajectory_invalid:centre"),
    (pack({"v": 1, "points": [[0, float("nan"), 0.2]]}), "trajectory_invalid:centre"),
    (pack({"v": 1, "points": [[0, 1.0000001, 0.2]]}), "trajectory_invalid:centre"),
    (pack({"v": 1, "points": [[0, 0.1, -0.0001]]}), "trajectory_invalid:centre"),
    (pack({"v": 1, "points": [[200, 0.1, 0.2], [100, 0.1, 0.2]]}), "trajectory_invalid:offsets_not_increasing"),
    (pack({"v": 1, "points": [[200, 0.1, 0.2], [200, 0.1, 0.2]]}), "trajectory_invalid:offsets_not_increasing"),
])
def test_malformed_trajectories_are_refused(data, code):
    with refused(code):
        t.decode(data)


def test_read_locates_by_hash_and_verifies_before_decoding(tmp_path):
    data = pack({"v": 1, "points": POINTS})
    sha = artefacts.sha256_hex(data)
    sealed = tmp_path / "evidence" / "job" / "attempt-0001" / "trajectories"
    sealed.mkdir(parents=True)
    path = sealed / f"track-{sha}.msgpack"
    path.write_bytes(data)
    assert t.read(tmp_path / "evidence", sha) == t.decode(data)
    path.write_bytes(pack({"v": 1, "points": POINTS[:2]}))
    with refused(f"trajectory_hash_mismatch:{sha}$"):
        t.read(tmp_path / "evidence", sha)
    with refused("trajectory_missing:"):
        t.read(tmp_path / "evidence", "0" * 64)


def test_a_hash_matching_malformed_payload_is_still_refused(tmp_path):
    data = pack({"v": 1, "points": [[0, 2.0, 0.2]]})
    sha = artefacts.sha256_hex(data)
    (tmp_path / f"t-{sha}.msgpack").write_bytes(data)
    with refused("trajectory_invalid:centre$"):
        t.read(tmp_path, sha)
