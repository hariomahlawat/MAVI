"""Bounded-memory trajectory accumulation for one live Track (S1.2b).

A Track can live for the whole video, so its trajectory is the one piece of live
state that would otherwise grow with the Track's duration. The spool keeps at
most one chunk of points in compact arrays, spills each full chunk to an
attempt-scoped internal file, and at finalisation streams the canonical
trajectory-v1 bytes from the spilled chunks and the in-memory remainder through
the shared v1 encoder. No point list, per-point object, cached chunk or file
handle survives between calls.

The spill format is internal to the worker: little-endian ``<qdd`` records
(int64 offset, float64 x, float64 y; 24 bytes per point), never published and
never referenced by any descriptor. float64 is stored bit-exact, so the
streamed payload is byte-identical to ``serialize_trajectory`` of the same
points.

Integrity is checked, not assumed. Each append checks that the file is exactly
as long as this spool has written, and the spool keeps a running SHA-256 of
every spilled byte. The read-back must match that digest, the expected length,
the record alignment, strictly increasing offsets and valid coordinates.
Anything else raises ``trajectory_spool_corrupt`` before the publication
completes, so a damaged spool fails the attempt and is never published.
"""

from __future__ import annotations

import struct
from array import array
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from typing import TypeVar

from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.video.trajectory import iter_trajectory_v1


DEFAULT_CHUNK_POINTS = 4096
MAX_CHUNK_POINTS = 1 << 20

_RECORD = struct.Struct("<qdd")
RECORD_BYTES = _RECORD.size  # 24

_OPEN = "open"
_FINALISING = "finalising"
_CLOSED = "closed"

T = TypeVar("T")


class TrajectorySpoolError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class TrajectorySummary:
    """What finalisation needs to know about a trajectory without its points."""

    point_count: int
    first_offset_ms: int
    last_offset_ms: int


class TrajectorySpool:
    """Append-only trajectory of one Track, memory-bounded by ``chunk_points``.

    Offsets must strictly increase and centres must be finite floats in
    ``[0, 1]``; a violation fails closed at ``append`` (the Track, and so the
    attempt, fails). Centres must already be ``float``: the spill stores float64,
    and silently turning an integer into a float would change its v1 encoding.
    """

    __slots__ = (
        "_store",
        "_name",
        "_chunk_points",
        "_offsets",
        "_xs",
        "_ys",
        "_spilled_points",
        "_spilled_digest",
        "_first_offset_ms",
        "_last_spilled_offset_ms",
        "_last_offset_ms",
        "_state",
    )

    def __init__(
        self,
        store: StagingArtifactStore,
        track_id: str,
        *,
        chunk_points: int = DEFAULT_CHUNK_POINTS,
    ) -> None:
        if (
            isinstance(chunk_points, bool)
            or not isinstance(chunk_points, int)
            or not 1 <= chunk_points <= MAX_CHUNK_POINTS
        ):
            raise ValueError("trajectory_chunk_points_invalid")
        self._store = store
        self._name = store.spool_relative_name(track_id)
        self._chunk_points = chunk_points
        self._offsets = array("q")
        self._xs = array("d")
        self._ys = array("d")
        self._spilled_points = 0
        self._spilled_digest = sha256()
        self._first_offset_ms: int | None = None
        self._last_spilled_offset_ms: int | None = None
        self._last_offset_ms: int | None = None
        self._state = _OPEN

    @property
    def point_count(self) -> int:
        return self._spilled_points + len(self._offsets)

    @property
    def spilled_points(self) -> int:
        return self._spilled_points

    @property
    def buffered_points(self) -> int:
        return len(self._offsets)

    @property
    def chunk_points(self) -> int:
        return self._chunk_points

    def summary(self) -> TrajectorySummary:
        if self._first_offset_ms is None or self._last_offset_ms is None:
            return TrajectorySummary(0, 0, 0)
        return TrajectorySummary(
            self.point_count,
            self._first_offset_ms,
            self._last_offset_ms,
        )

    def append(self, offset_ms: int, center_x: float, center_y: float) -> None:
        if self._state != _OPEN:
            raise TrajectorySpoolError("trajectory_spool_closed")
        if (
            isinstance(offset_ms, bool)
            or not isinstance(offset_ms, int)
            or not 0 <= offset_ms < 1 << 63
        ):
            raise TrajectorySpoolError("trajectory_offset_invalid")
        if self._last_offset_ms is not None and offset_ms <= self._last_offset_ms:
            raise TrajectorySpoolError("trajectory_offsets_not_monotonic")
        _require_centre(center_x)
        _require_centre(center_y)

        self._offsets.append(offset_ms)
        self._xs.append(center_x)
        self._ys.append(center_y)
        if self._first_offset_ms is None:
            self._first_offset_ms = offset_ms
        self._last_offset_ms = offset_ms
        if len(self._offsets) == self._chunk_points:
            self._spill()

    def finalise(self, publish: Callable[[Iterator[bytes]], T]) -> T:
        """Stream the canonical v1 payload into ``publish``; remove the spool after.

        ``publish`` receives an iterator of v1 byte buffers and must consume it
        fully (``write_stream`` does). The spool file is removed only once
        ``publish`` has returned; if it raises, the spool is left for attempt
        cleanup and this spool refuses further use.
        """
        if self._state != _OPEN:
            raise TrajectorySpoolError("trajectory_spool_closed")
        self._state = _FINALISING
        with closing(
            iter_trajectory_v1(self.point_count, self._iter_points())
        ) as chunks:
            result = publish(chunks)
        self.discard()
        return result

    def discard(self) -> None:
        """Release the buffered points and remove the spool file, if any."""
        self._state = _CLOSED
        self._offsets = array("q")
        self._xs = array("d")
        self._ys = array("d")
        if self._spilled_points:
            self._store.remove(self._name)

    def _spill(self) -> None:
        count = len(self._offsets)
        record = bytearray(count * RECORD_BYTES)
        pack_into = _RECORD.pack_into
        offsets, xs, ys = self._offsets, self._xs, self._ys
        for index in range(count):
            pack_into(record, index * RECORD_BYTES, offsets[index], xs[index], ys[index])

        size = self._store.append_bytes(self._name, record)
        expected = (self._spilled_points + count) * RECORD_BYTES
        if size != expected:
            # Something other than this spool wrote to (or truncated) the file.
            raise TrajectorySpoolError("trajectory_spool_corrupt")
        self._spilled_digest.update(record)
        self._spilled_points += count
        self._last_spilled_offset_ms = offsets[count - 1]
        self._offsets = array("q")
        self._xs = array("d")
        self._ys = array("d")

    def _iter_points(self) -> Iterator[tuple[int, float, float]]:
        if self._spilled_points:
            yield from self._iter_spilled()
        yield from zip(self._offsets, self._xs, self._ys)

    def _iter_spilled(self) -> Iterator[tuple[int, float, float]]:
        digest = sha256()
        read = 0
        previous: int | None = None
        first: int | None = None
        chunks = self._store.read_chunks(
            self._name,
            chunk_bytes=self._chunk_points * RECORD_BYTES,
            expected_size=self._spilled_points * RECORD_BYTES,
        )
        with closing(chunks):
            for chunk in chunks:
                if len(chunk) % RECORD_BYTES:
                    raise TrajectorySpoolError("trajectory_spool_corrupt")
                digest.update(chunk)
                for offset_ms, center_x, center_y in _RECORD.iter_unpack(chunk):
                    if (
                        offset_ms < 0
                        or (previous is not None and offset_ms <= previous)
                        or not (isfinite(center_x) and 0.0 <= center_x <= 1.0)
                        or not (isfinite(center_y) and 0.0 <= center_y <= 1.0)
                    ):
                        raise TrajectorySpoolError("trajectory_spool_corrupt")
                    if first is None:
                        first = offset_ms
                    previous = offset_ms
                    read += 1
                    yield offset_ms, center_x, center_y
        if (
            read != self._spilled_points
            or first != self._first_offset_ms
            or previous != self._last_spilled_offset_ms
            or digest.digest() != self._spilled_digest.digest()
        ):
            raise TrajectorySpoolError("trajectory_spool_corrupt")


def _require_centre(value: float) -> None:
    if not isinstance(value, float) or not isfinite(value) or not 0.0 <= value <= 1.0:
        raise TrajectorySpoolError("trajectory_center_invalid")
