from __future__ import annotations

from fractions import Fraction

import av
import numpy as np
import pytest

from mavi_vision.video.reader import DecodedFrame, VideoReadError, _frame_offset_ms, iter_frames


def _write_tiny_mp4(path) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width = 32
        stream.height = 24
        stream.pix_fmt = "yuv420p"
        for index in range(3):
            image = np.full((24, 32, 3), index * 40, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_frame_offset_prefers_pts_and_uses_deterministic_rounding() -> None:
    assert _frame_offset_ms(13, Fraction(1, 25), 999, 1, 1, origin_pts=10) == 120
    assert _frame_offset_ms(2, Fraction(1, 8), 999, 1, 1, origin_pts=1) == 125


def test_frame_offset_normalizes_positive_and_negative_pts_origins() -> None:
    assert _frame_offset_ms(100, Fraction(1, 1000), 0, 25, 1, origin_pts=100) == 0
    assert _frame_offset_ms(140, Fraction(1, 1000), 1, 25, 1, origin_pts=100) == 40
    assert _frame_offset_ms(-20, Fraction(1, 1000), 0, 25, 1, origin_pts=-20) == 0
    assert _frame_offset_ms(20, Fraction(1, 1000), 1, 25, 1, origin_pts=-20) == 40


def test_frame_offset_falls_back_to_rational_frame_rate() -> None:
    assert _frame_offset_ms(None, None, 3, 25, 1, origin_pts=None) == 120
    assert _frame_offset_ms(None, None, 1, 24, 1, origin_pts=None) == 42


def test_frame_offset_requires_pts_or_valid_rate() -> None:
    with pytest.raises(VideoReadError, match="frame_timestamp_unavailable"):
        _frame_offset_ms(None, None, 0, 0, 1, origin_pts=None)


def test_iter_frames_decodes_rgb_with_media_relative_monotonic_offsets(tmp_path) -> None:
    path = tmp_path / "tiny.mp4"
    _write_tiny_mp4(path)

    frames = list(iter_frames(path))

    assert [frame.source_frame_number for frame in frames] == [0, 1, 2]
    assert frames[0].offset_ms == 0
    assert [frame.offset_ms for frame in frames] == sorted(frame.offset_ms for frame in frames)
    assert all(frame.offset_ms >= 0 for frame in frames)
    assert all(frame.image.shape == (24, 32, 3) for frame in frames)
    assert all(frame.image.dtype == np.uint8 for frame in frames)
    assert all(frame.image.flags.c_contiguous for frame in frames)


def test_decoded_frame_rejects_invalid_shape_or_offset() -> None:
    with pytest.raises(ValueError):
        DecodedFrame(0, -1, np.zeros((2, 2, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        DecodedFrame(0, 0, np.zeros((2, 2), dtype=np.uint8))
