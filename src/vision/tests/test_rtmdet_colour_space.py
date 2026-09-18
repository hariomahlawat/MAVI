from __future__ import annotations

import numpy as np
import pytest

from mavi_vision.runtime.mmdetection import _rgb_to_bgr


def test_rgb_to_bgr_swaps_channels_once_without_mutating_source() -> None:
    source = np.array([[[11, 22, 33], [44, 55, 66]]], dtype=np.uint8)
    before = source.copy()

    converted = _rgb_to_bgr(source)

    assert converted.tolist() == [[[33, 22, 11], [66, 55, 44]]]
    assert converted.dtype == np.uint8
    assert converted.shape == source.shape
    assert converted.flags.c_contiguous is True
    assert np.array_equal(source, before)
    assert not np.shares_memory(source, converted)


def test_rgb_to_bgr_makes_noncontiguous_input_contiguous_without_mutation() -> None:
    backing = np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3)
    source = backing[:, ::2, :]
    before = backing.copy()

    converted = _rgb_to_bgr(source)

    assert source.flags.c_contiguous is False
    assert converted.flags.c_contiguous is True
    assert np.array_equal(converted, source[..., ::-1])
    assert np.array_equal(backing, before)


@pytest.mark.parametrize(
    "image",
    [
        np.zeros((1, 1), dtype=np.uint8),
        np.zeros((1, 1, 4), dtype=np.uint8),
        np.zeros((1, 1, 3), dtype=np.float32),
        np.zeros((0, 1, 3), dtype=np.uint8),
        np.zeros((1, 0, 3), dtype=np.uint8),
    ],
)
def test_rgb_to_bgr_rejects_invalid_frame_contract(image: np.ndarray) -> None:
    with pytest.raises(ValueError, match="runtime_input_image_invalid"):
        _rgb_to_bgr(image)
