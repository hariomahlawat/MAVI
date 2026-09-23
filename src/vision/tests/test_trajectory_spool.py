from __future__ import annotations

import gc
import json
import os
import random
import struct
import sys
import tracemalloc
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import msgpack
import pytest

from mavi_vision.common.analytical import TrajectoryPoint
from mavi_vision.storage.artifact_store import StagingArtifactError, StagingArtifactStore
from mavi_vision.video.trajectory import (
    deserialize_trajectory,
    iter_trajectory_v1,
    serialize_trajectory,
    trajectory_v1_header,
)
from mavi_vision.video.trajectory_spool import (
    DEFAULT_CHUNK_POINTS,
    RECORD_BYTES,
    TrajectorySpool,
    TrajectorySpoolError,
    TrajectorySummary,
)


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
TRACK_ID = "person-0001"
GOLDEN = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "scene-analytics"


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


# --- Spool: helpers ------------------------------------------------------------


def _store(root: Path, attempt: int = 1) -> StagingArtifactStore:
    return StagingArtifactStore(root, JOB_ID, attempt)


def _attempt(root: Path, attempt: int = 1) -> Path:
    return root / "staging" / str(JOB_ID) / f"attempt-{attempt:04d}"


def _spool_file(root: Path, attempt: int = 1) -> Path:
    return _attempt(root, attempt) / "spool" / f"{TRACK_ID}.traj"


def _published(root: Path, attempt: int = 1) -> Path:
    return _attempt(root, attempt) / "trajectories" / f"{TRACK_ID}.msgpack"


def _fill(spool: TrajectorySpool, points) -> None:
    for point in points:
        spool.append(point.offset_ms, point.center_x, point.center_y)


def _finalise(spool: TrajectorySpool, store: StagingArtifactStore):
    return spool.finalise(
        lambda chunks: store.write_stream(
            f"trajectories/{TRACK_ID}.msgpack", chunks, "application/msgpack"
        )
    )


def _spooled_bytes(root: Path, points, chunk_points: int) -> bytes:
    store = _store(root)
    spool = TrajectorySpool(store, TRACK_ID, chunk_points=chunk_points)
    _fill(spool, points)
    descriptor = _finalise(spool, store)
    payload = _published(root).read_bytes()
    assert descriptor.size_bytes == len(payload)
    assert descriptor.sha256 == sha256(payload).hexdigest()
    return payload


# --- T1 through the spool: byte identity with the pre-S1.2b serializer ---------


@pytest.mark.parametrize("count", BOUNDARY_COUNTS)
def test_spooled_payload_identical_to_reference_at_default_chunk(tmp_path: Path, count: int) -> None:
    points = _random_points(count, seed=100 + count)

    assert _spooled_bytes(tmp_path, points, DEFAULT_CHUNK_POINTS) == _reference_v1(points)


# --- T2: output independent of chunk size and spill count ----------------------


@pytest.mark.parametrize(
    ("count", "chunk_points"),
    [
        (1, 1), (2, 1), (5000, 1), (5000, 7), (5000, 4096), (5000, 5001),
        (4097, 4096), (4096, 4096), (70000, 7), (70000, 4096), (70000, 70001),
        (65536, 65536), (65537, 65536),
    ],
)
def test_bytes_identical_across_chunk_sizes_and_spill_counts(
    tmp_path: Path, count: int, chunk_points: int
) -> None:
    points = _random_points(count, seed=count)

    payload = _spooled_bytes(tmp_path, points, chunk_points)

    assert sha256(payload).digest() == sha256(_reference_v1(points)).digest()
    assert deserialize_trajectory(payload) == points


def test_spool_file_holds_exact_little_endian_records_until_removed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spool = TrajectorySpool(store, TRACK_ID, chunk_points=3)
    points = _random_points(7, seed=11)
    _fill(spool, points)

    raw = _spool_file(tmp_path).read_bytes()
    assert len(raw) == 6 * RECORD_BYTES
    assert list(struct.iter_unpack("<qdd", raw)) == [
        (p.offset_ms, p.center_x, p.center_y) for p in points[:6]
    ]
    assert (spool.spilled_points, spool.buffered_points, spool.point_count) == (6, 1, 7)
    assert spool.summary() == TrajectorySummary(7, points[0].offset_ms, points[-1].offset_ms)

    _finalise(spool, store)

    # Removed only after the publication succeeded; nothing else is left behind.
    assert not _spool_file(tmp_path).exists()
    assert list((_attempt(tmp_path) / "spool").iterdir()) == []
    assert _published(tmp_path).read_bytes() == _reference_v1(points)


def test_unspilled_track_never_creates_a_spool_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spool = TrajectorySpool(store, TRACK_ID, chunk_points=100)
    _fill(spool, _random_points(99, seed=2))

    _finalise(spool, store)

    assert not (_attempt(tmp_path) / "spool").exists()


# --- T3: retained state does not grow with the Track's length -----------------


@pytest.mark.parametrize("count", [60, 600, 6000, 60000])
def test_retained_points_never_exceed_one_chunk(tmp_path: Path, count: int) -> None:
    chunk_points = 256
    spool = TrajectorySpool(_store(tmp_path), TRACK_ID, chunk_points=chunk_points)
    high_water = 0
    for index in range(count):
        spool.append(index * 33, 0.5, 0.25)
        high_water = max(high_water, spool.buffered_points)

    assert high_water < chunk_points  # a full chunk is spilled on the append that fills it
    assert spool.buffered_points == count % chunk_points
    assert spool.spilled_points == count - count % chunk_points
    # The spool's only per-point storage is its three compact arrays.
    assert sys.getsizeof(spool) < 256
    assert not any(isinstance(getattr(spool, slot), (list, tuple, dict)) for slot in TrajectorySpool.__slots__)


def test_traced_memory_is_flat_from_60_to_60000_points(tmp_path: Path) -> None:
    # Chunk 30 divides every count, so each spool ends with an empty buffer and
    # any difference in retained memory can only be per-point growth.
    chunk_points = 30
    retained: dict[int, int] = {}
    peaks: dict[int, int] = {}
    for count in (60, 600, 6000, 60000):
        root = tmp_path / str(count)
        root.mkdir()
        store = _store(root)
        gc.collect()
        tracemalloc.start()
        try:
            baseline = tracemalloc.get_traced_memory()[0]
            spool = TrajectorySpool(store, TRACK_ID, chunk_points=chunk_points)
            for index in range(count):
                spool.append(index * 33, 0.5, 0.25)
            gc.collect()
            current, peak = tracemalloc.get_traced_memory()
            retained[count] = current - baseline
            peaks[count] = peak - baseline
        finally:
            tracemalloc.stop()
        assert spool.point_count == count

    # 60,000 points are 1.4 MB of records; the live spool retains none of them.
    assert retained[60000] - retained[60] <= 4 * 1024, retained
    # The transient peak also counts garbage awaiting collection: on Windows the
    # backend's per-call ctypes structures form short-lived cycles, and the peak
    # settles (about 190-440 KB on CI runners) once collections run regularly.
    # It must stop growing with the Track, and stay far below what per-point
    # retention needs (a spool keeping a point list peaks at about 6.3 MB here).
    assert peaks[60000] - peaks[6000] <= 64 * 1024, peaks
    assert max(peaks.values()) <= 1024 * 1024, peaks


# --- T4: finalisation streams; it never loads the whole trajectory ------------


def test_finalise_reads_one_chunk_at_a_time_and_keeps_peak_memory_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk_points = 512
    count = 200_000  # a 4.8 MB spool and a 4.8 MB payload
    store = _store(tmp_path)
    spool = TrajectorySpool(store, TRACK_ID, chunk_points=chunk_points)
    for index in range(count):
        spool.append(index * 33, (index % 1000) / 1000.0, 0.5)

    read_sizes: list[int] = []
    real_read_chunks = store._backend.read_chunks

    def recording_read_chunks(parts, chunk_bytes):
        for chunk in real_read_chunks(parts, chunk_bytes):
            read_sizes.append(len(chunk))
            yield chunk

    monkeypatch.setattr(store._backend, "read_chunks", recording_read_chunks)

    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        descriptor = _finalise(spool, store)
        peak = tracemalloc.get_traced_memory()[1] - before
    finally:
        tracemalloc.stop()

    assert descriptor.size_bytes > 4_500_000
    assert max(read_sizes) <= RECORD_BYTES * chunk_points
    assert sum(read_sizes) == RECORD_BYTES * (count - count % chunk_points)
    # One read chunk plus one encoder batch (4096 points) plus their Python
    # objects: far below the 4.8 MB the whole payload or spool would need.
    assert peak <= 1024 * 1024, peak


def test_points_stream_in_append_order_across_spill_and_buffer(tmp_path: Path) -> None:
    points = _random_points(1000, seed=5)

    payload = _spooled_bytes(tmp_path, points, chunk_points=64)

    assert [p.offset_ms for p in deserialize_trajectory(payload)] == [p.offset_ms for p in points]


# --- T5: malformed input and a damaged spool fail closed ----------------------


@pytest.mark.parametrize(
    ("appended", "code"),
    [
        ([(100, 0.1, 0.1), (100, 0.2, 0.2)], "trajectory_offsets_not_monotonic"),
        ([(100, 0.1, 0.1), (99, 0.2, 0.2)], "trajectory_offsets_not_monotonic"),
        ([(-1, 0.1, 0.1)], "trajectory_offset_invalid"),
        ([(True, 0.1, 0.1)], "trajectory_offset_invalid"),
        ([(1.5, 0.1, 0.1)], "trajectory_offset_invalid"),
        ([(1 << 63, 0.1, 0.1)], "trajectory_offset_invalid"),
        ([(0, float("nan"), 0.1)], "trajectory_center_invalid"),
        ([(0, 0.1, float("inf"))], "trajectory_center_invalid"),
        ([(0, 1.5, 0.1)], "trajectory_center_invalid"),
        ([(0, -0.5, 0.1)], "trajectory_center_invalid"),
        ([(0, 1, 0.1)], "trajectory_center_invalid"),
    ],
)
def test_invalid_append_fails_closed(tmp_path: Path, appended, code: str) -> None:
    spool = TrajectorySpool(_store(tmp_path), TRACK_ID, chunk_points=4)

    with pytest.raises(TrajectorySpoolError, match=code):
        for offset, x, y in appended:
            spool.append(offset, x, y)


def _spilled_spool(root: Path, count: int = 10, chunk_points: int = 4):
    store = _store(root)
    spool = TrajectorySpool(store, TRACK_ID, chunk_points=chunk_points)
    _fill(spool, _random_points(count, seed=9))
    return store, spool


def _assert_finalise_fails_and_publishes_nothing(root, store, spool, match) -> None:
    with pytest.raises((TrajectorySpoolError, StagingArtifactError), match=match):
        _finalise(spool, store)
    trajectories = _attempt(root) / "trajectories"
    assert not trajectories.exists() or list(trajectories.iterdir()) == []


@pytest.mark.parametrize(
    ("damage", "match"),
    [
        # Misaligned truncation: whichever check sees it first, it fails closed.
        (lambda raw: raw[:-1], "staging_read_size_mismatch|trajectory_spool_corrupt"),
        (lambda raw: raw[:-RECORD_BYTES], "staging_read_size_mismatch"),
        (lambda raw: raw + raw[-RECORD_BYTES:], "staging_read_size_mismatch"),
        (lambda raw: b"", "staging_read_size_mismatch"),
        # Same length, records swapped: offsets no longer increase.
        (lambda raw: raw[RECORD_BYTES:2 * RECORD_BYTES] + raw[:RECORD_BYTES] + raw[2 * RECORD_BYTES:], "trajectory_spool_corrupt"),
        # One mantissa bit of one coordinate: still a valid, increasing record.
        (lambda raw: raw[:15] + bytes([raw[15] ^ 0x01]) + raw[16:], "trajectory_spool_corrupt"),
        # Offset byte changed but order preserved: only the digest can tell.
        (lambda raw: bytes([raw[0] ^ 0x01]) + raw[1:], "trajectory_spool_corrupt"),
    ],
)
def test_damaged_spool_fails_closed_before_publication(tmp_path: Path, damage, match: str) -> None:
    store, spool = _spilled_spool(tmp_path)
    path = _spool_file(tmp_path)
    path.write_bytes(damage(path.read_bytes()))

    _assert_finalise_fails_and_publishes_nothing(tmp_path, store, spool, match)
    with pytest.raises(TrajectorySpoolError, match="trajectory_spool_closed"):
        spool.append(10**9, 0.5, 0.5)


def test_deleted_spool_fails_closed(tmp_path: Path) -> None:
    store, spool = _spilled_spool(tmp_path)
    _spool_file(tmp_path).unlink()

    _assert_finalise_fails_and_publishes_nothing(tmp_path, store, spool, "staging_read_failed")


def test_misaligned_read_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, spool = _spilled_spool(tmp_path, count=8, chunk_points=4)
    real_read_chunks = store._backend.read_chunks

    def misaligned(parts, chunk_bytes):
        data = b"".join(real_read_chunks(parts, chunk_bytes))
        yield data[:25]
        yield data[25:]

    monkeypatch.setattr(store._backend, "read_chunks", misaligned)

    _assert_finalise_fails_and_publishes_nothing(tmp_path, store, spool, "trajectory_spool_corrupt")


def test_foreign_write_between_spills_fails_at_the_next_spill(tmp_path: Path) -> None:
    store, spool = _spilled_spool(tmp_path, count=4, chunk_points=4)
    with _spool_file(tmp_path).open("ab") as foreign:
        foreign.write(b"x" * RECORD_BYTES)

    with pytest.raises(TrajectorySpoolError, match="trajectory_spool_corrupt"):
        _fill(spool, _random_points(8, seed=9)[4:])


def test_corrupted_record_values_fail_closed(tmp_path: Path) -> None:
    store, spool = _spilled_spool(tmp_path, count=4, chunk_points=4)
    raw = bytearray(_spool_file(tmp_path).read_bytes())
    offset, _, y = struct.unpack_from("<qdd", raw, RECORD_BYTES)
    struct.pack_into("<qdd", raw, RECORD_BYTES, offset, float("nan"), y)
    _spool_file(tmp_path).write_bytes(bytes(raw))

    _assert_finalise_fails_and_publishes_nothing(tmp_path, store, spool, "trajectory_spool_corrupt")


def test_finalise_is_single_use_and_publish_failure_keeps_spool_for_cleanup(tmp_path: Path) -> None:
    store, spool = _spilled_spool(tmp_path)

    def failing_publish(chunks):
        next(chunks)
        raise RuntimeError("publish failed")

    with pytest.raises(RuntimeError, match="publish failed"):
        spool.finalise(failing_publish)

    # Not removed by the spool: the attempt's cleanup owns it now.
    assert _spool_file(tmp_path).exists()
    with pytest.raises(TrajectorySpoolError, match="trajectory_spool_closed"):
        _finalise(spool, store)
    store.cleanup()
    assert not _attempt(tmp_path).exists()


@pytest.mark.parametrize("chunk_points", [0, -1, True, 1.0, (1 << 20) + 1])
def test_invalid_chunk_sizes_are_rejected(tmp_path: Path, chunk_points) -> None:
    with pytest.raises(ValueError, match="trajectory_chunk_points_invalid"):
        TrajectorySpool(_store(tmp_path), TRACK_ID, chunk_points=chunk_points)


# --- T9 (FD/handle bound): no handle is held per live Track --------------------


def _open_handle_count() -> int | None:
    if sys.platform.startswith("linux"):
        return len(os.listdir("/proc/self/fd"))
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetProcessHandleCount.restype = wintypes.BOOL
        count = wintypes.DWORD()
        if kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(count)):
            return int(count.value)
    return None


def test_many_live_spools_hold_no_file_handles(tmp_path: Path) -> None:
    store = _store(tmp_path)
    before = _open_handle_count()
    limits = None
    if os.name == "posix":
        import resource

        limits = resource.getrlimit(resource.RLIMIT_NOFILE)
        open_now = before if before is not None else 64
        # Far fewer descriptors than live Tracks: a handle per Track hits EMFILE.
        resource.setrlimit(resource.RLIMIT_NOFILE, (open_now + 48, limits[1]))
    try:
        spools = [
            TrajectorySpool(store, f"person-{index:04d}", chunk_points=1)
            for index in range(2000)
        ]
        for step in range(3):
            for spool in spools:
                spool.append(step * 40, 0.5, 0.5)
        during = _open_handle_count()
    finally:
        if limits is not None:
            import resource

            resource.setrlimit(resource.RLIMIT_NOFILE, limits)

    assert all(spool.spilled_points == 3 for spool in spools)
    for spool in spools[:50]:
        assert spool.finalise(lambda chunks: b"".join(chunks)) == _reference_v1(
            tuple(TrajectoryPoint(step * 40, 0.5, 0.5) for step in range(3))
        )
    after = _open_handle_count()
    if before is not None and during is not None and after is not None:
        # 6,000 appends, 50 streamed read-backs and 50 removals leak nothing.
        assert during - before <= 8, (before, during)
        assert after - before <= 8, (before, after)


# --- T9 (golden): the Scene Analytics fixture through the spool ----------------


@pytest.mark.parametrize("chunk_points", [1, 2, 3, 4096])
def test_golden_scene_analytics_fixture_reproduced_through_the_spool(
    tmp_path: Path, chunk_points: int
) -> None:
    fixture = json.loads((GOLDEN / "worker-trajectory-v1.json").read_text(encoding="utf-8"))
    expected = (GOLDEN / "worker-trajectory-v1.msgpack").read_bytes()
    points = tuple(TrajectoryPoint(o, x, y) for o, x, y in fixture["points"])

    assert serialize_trajectory(points) == expected
    assert _spooled_bytes(tmp_path, points, chunk_points) == expected
