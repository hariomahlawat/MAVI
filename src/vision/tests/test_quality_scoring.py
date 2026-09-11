from __future__ import annotations

import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.quality.scoring import representative_quality
from mavi_vision.video.reader import DecodedFrame


def _frame(image: np.ndarray) -> DecodedFrame:
    return DecodedFrame(0, 0, np.ascontiguousarray(image, dtype=np.uint8))


def test_flat_centered_bbox_uses_exact_area_and_margin_weights() -> None:
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    bbox = NormalizedBoundingBox(0.1, 0.1, 0.2, 0.5)

    score = representative_quality(_frame(image), bbox)

    assert score == pytest.approx(0.375)


def test_edge_bbox_has_lower_margin_score() -> None:
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    centered = NormalizedBoundingBox(0.1, 0.1, 0.2, 0.5)
    edge = NormalizedBoundingBox(0.0, 0.0, 0.2, 0.5)

    assert representative_quality(_frame(image), edge) == pytest.approx(0.175)
    assert representative_quality(_frame(image), centered) > representative_quality(
        _frame(image), edge
    )


def test_sharp_content_scores_higher_than_flat_content() -> None:
    flat = np.zeros((20, 20, 3), dtype=np.uint8)
    checker = np.indices((20, 20)).sum(axis=0) % 2 * 255
    sharp = np.repeat(checker[:, :, None], 3, axis=2).astype(np.uint8)
    bbox = NormalizedBoundingBox(0.1, 0.1, 0.8, 0.8)

    assert representative_quality(_frame(sharp), bbox) > representative_quality(
        _frame(flat), bbox
    )


def test_quality_score_is_deterministic_and_bounded() -> None:
    rng = np.random.default_rng(42)
    image = rng.integers(0, 256, size=(32, 32, 3), dtype=np.uint8)
    bbox = NormalizedBoundingBox(0.2, 0.2, 0.4, 0.4)

    first = representative_quality(_frame(image), bbox)
    second = representative_quality(_frame(image), bbox)

    assert first == second
    assert 0.0 <= first <= 1.0
