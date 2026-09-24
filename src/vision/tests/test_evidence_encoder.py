"""Evidence encoder: the exact ladder, caps, floors and fixed JPEG options (E1–E8)."""

from __future__ import annotations

import hashlib
import os
import sys
from io import BytesIO

import numpy as np
import PIL
import pytest
from PIL import Image, JpegImagePlugin, features

import mavi_vision.evidence.encoder as encoder_module
from mavi_vision.evidence.encoder import (
    JpegLadderEncoder,
    LadderStep,
    encoding_ladder,
    scaled_size,
)
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.policy import PRODUCTION_ENCODER_POLICY as POLICY
from mavi_vision.evidence.roles import REPRESENTATIVE_CAP_BYTES, SUPPLEMENTAL_CAP_BYTES

FULL_LADDER = (
    (1024, 85), (1024, 75), (819, 75), (655, 75), (524, 75), (419, 75), (335, 75),
    (268, 75), (214, 75), (171, 75), (136, 75), (128, 75), (128, 65), (128, 55), (128, 50),
)


def _steps(width: int, height: int) -> tuple[tuple[int, int], ...]:
    return tuple((s.long_edge, s.quality) for s in encoding_ladder(width, height, POLICY))


def _noise(height: int, width: int, seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (height, width, 3), dtype=np.uint8)


def _smooth(height: int, width: int) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width]
    image = np.stack([(x * 255 // max(1, width - 1)), (y * 255 // max(1, height - 1)), (x + y) % 256], axis=2)
    return image.astype(np.uint8)


# E1 ---------------------------------------------------------------------------


def test_ladder_steps_are_exact_from_the_1024_start() -> None:
    assert _steps(1024, 700) == FULL_LADDER
    # A larger crop starts at 1024 too: it is downscaled, never encoded above it.
    assert _steps(4000, 1200) == FULL_LADDER
    assert len(FULL_LADDER) == 15


def test_ladder_for_mid_and_small_crops_never_upscales() -> None:
    assert _steps(300, 120) == (
        (300, 85), (300, 75), (240, 75), (192, 75), (153, 75), (128, 75),
        (128, 65), (128, 55), (128, 50),
    )
    # At or below the floor there is no resize step at all.
    assert _steps(128, 60) == ((128, 85), (128, 75), (128, 65), (128, 55), (128, 50))
    assert _steps(90, 40) == ((90, 85), (90, 75), (90, 65), (90, 55), (90, 50))


def test_scaled_size_keeps_aspect_with_half_up_rounding() -> None:
    assert scaled_size(2000, 1000, 1024) == (1024, 512)
    assert scaled_size(1000, 2001, 1024) == (512, 1024)  # 511.744 -> 512
    assert scaled_size(3, 2000, 128) == (1, 128)  # never below one pixel
    assert scaled_size(100, 50, 1024) == (100, 50)  # never upscaled


# E2 / E3 / E4 with a size-reporting stub, so the chosen step is asserted --------


def _stub_sizes(monkeypatch: pytest.MonkeyPatch, sizes: list[int]) -> list[tuple[tuple[int, int], int]]:
    calls: list[tuple[tuple[int, int], int]] = []

    def fake_encode(image: Image.Image, quality: int) -> bytes:
        calls.append((image.size, quality))
        return b"\x00" * sizes[len(calls) - 1]

    monkeypatch.setattr(encoder_module, "_encode_jpeg", fake_encode)
    return calls


@pytest.mark.parametrize("winning_step", [0, 1, 2, 11, 12, 14])
def test_stops_at_the_first_step_under_cap(monkeypatch: pytest.MonkeyPatch, winning_step: int) -> None:
    cap = 1000
    calls = _stub_sizes(monkeypatch, [cap + 1] * winning_step + [cap] + [1] * 20)

    encoded = JpegLadderEncoder(POLICY).encode(_smooth(700, 1024), cap)

    assert encoded is not None
    assert encoded.ladder_step == winning_step
    assert (encoded.width, encoded.quality) == FULL_LADDER[winning_step]
    assert len(calls) == winning_step + 1
    assert [(size[0], quality) for size, quality in calls] == list(FULL_LADDER[: winning_step + 1])


def test_returns_none_past_the_floor_after_exactly_fifteen_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_sizes(monkeypatch, [10_000] * 20)

    assert JpegLadderEncoder(POLICY).encode(_smooth(700, 1024), 1000) is None
    assert len(calls) == 15
    assert calls[-1] == ((128, 88), 50)


def test_never_upscales_a_small_crop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_sizes(monkeypatch, [10_000] * 5)

    assert JpegLadderEncoder(POLICY).encode(_smooth(40, 60), 1000) is None
    assert {size for size, _ in calls} == {(60, 40)}


# Real encodes -----------------------------------------------------------------


def _decode(payload: bytes) -> Image.Image:
    image = Image.open(BytesIO(payload))
    image.load()
    return image


def test_small_smooth_crop_is_admitted_at_the_first_step_with_real_dimensions() -> None:
    encoded = JpegLadderEncoder(POLICY).encode(_smooth(90, 60), REPRESENTATIVE_CAP_BYTES)

    assert encoded is not None
    assert (encoded.ladder_step, encoded.quality) == (0, 85)
    assert _decode(encoded.payload).size == (encoded.width, encoded.height) == (60, 90)


def test_large_crop_is_downscaled_to_1024_and_the_decoded_size_matches() -> None:
    encoded = JpegLadderEncoder(POLICY).encode(_smooth(600, 2400), SUPPLEMENTAL_CAP_BYTES)

    assert encoded is not None
    assert encoded.width == 1024 and encoded.height == 256
    assert _decode(encoded.payload).size == (1024, 256)
    assert encoded.size_bytes <= SUPPLEMENTAL_CAP_BYTES


def test_adversarial_noise_is_admitted_as_measured_under_each_cap() -> None:
    """E6: admissibility at the ADR caps is a measured property; record the step."""
    encoder = JpegLadderEncoder(POLICY)
    near = encoder.encode(_noise(1024, 1024), SUPPLEMENTAL_CAP_BYTES)
    representative = encoder.encode(_noise(1024, 1024), REPRESENTATIVE_CAP_BYTES)
    tiny = encoder.encode(_noise(128, 128), REPRESENTATIVE_CAP_BYTES)

    for encoded, cap in ((near, SUPPLEMENTAL_CAP_BYTES), (representative, REPRESENTATIVE_CAP_BYTES), (tiny, REPRESENTATIVE_CAP_BYTES)):
        assert encoded is not None
        assert encoded.size_bytes <= cap
        assert FULL_LADDER[encoded.ladder_step][1] == encoded.quality or encoded.width < 1024
    # Worst-case noise needs a smaller step for the tighter Representative cap.
    assert representative.ladder_step > near.ladder_step


def test_encoding_is_deterministic_within_a_process() -> None:
    crop = _noise(300, 500, seed=3)
    first = JpegLadderEncoder(POLICY).encode(crop, SUPPLEMENTAL_CAP_BYTES)
    second = JpegLadderEncoder(POLICY).encode(crop.copy(), SUPPLEMENTAL_CAP_BYTES)

    assert first == second


# Golden bytes are claimed only within a runtime variant (S1.2 plan §8, S1.4
# plan §5.2). A variant's encoding identity is its OS platform, its Pillow
# build and the libjpeg-turbo that build bundles: any of the three can change
# the bytes, so all three are the key.
#
# Two cases, so the pin covers both encoder paths: a smooth crop that fits at
# the first ladder step, and a noise crop that the Representative cap forces
# down the reduction ladder (a smaller long edge and a lower quality).
GOLDEN_CASES = {
    "smooth-400x300-supplemental": (lambda: _smooth(300, 400), SUPPLEMENTAL_CAP_BYTES),
    "noise-500x300-representative": (lambda: _noise(300, 500, seed=3), REPRESENTATIVE_CAP_BYTES),
}
GOLDEN_SHA256 = {
    ("linux", "11.3.0", "3.1.1"): {
        "smooth-400x300-supplemental": "0e30820563fb84ddf7de44d6a59278cf12a2f184d344cf7d19a1537d678765d2",
        "noise-500x300-representative": "ec2a23be5f16bae00276639984731befb4f70f24b1e5162e01222a98268fd0ca",
    },
    # Derived on the qualified windows-x86_64-cpu Task-10 job (run 36005519545,
    # job 107652556538, source 5f26a3a), where the fail-closed test reported the
    # actual digests. They equal the Linux digests; that is observed, not
    # assumed, and a future divergence would fail here rather than skip.
    ("win32", "11.3.0", "3.1.1"): {
        "smooth-400x300-supplemental": "0e30820563fb84ddf7de44d6a59278cf12a2f184d344cf7d19a1537d678765d2",
        "noise-500x300-representative": "ec2a23be5f16bae00276639984731befb4f70f24b1e5162e01222a98268fd0ca",
    },
}

# The qualified CPU variants (Task 10) and the platform each must run on. In a
# qualified job ``MAVI_RUNTIME_VARIANT`` names the variant, and a missing pin
# there is a failure, never a skip: final B1 closure admits no golden skip.
QUALIFIED_VARIANT_PLATFORMS = {
    "linux-x86_64-cpu": "linux",
    "windows-x86_64-cpu": "win32",
}


def _encoding_identity() -> tuple[str, str, str | None]:
    return (sys.platform, PIL.__version__, features.version("libjpeg_turbo"))


@pytest.mark.parametrize("case", sorted(GOLDEN_CASES))
def test_golden_bytes_per_runtime_variant(case: str) -> None:
    make_crop, cap = GOLDEN_CASES[case]
    encoded = JpegLadderEncoder(POLICY).encode(make_crop(), cap)
    assert encoded is not None
    actual = hashlib.sha256(encoded.payload).hexdigest()

    identity = _encoding_identity()
    variant = os.environ.get("MAVI_RUNTIME_VARIANT")
    if variant is not None:
        assert variant in QUALIFIED_VARIANT_PLATFORMS, f"unknown qualified runtime variant {variant!r}"
        assert sys.platform == QUALIFIED_VARIANT_PLATFORMS[variant], (
            f"runtime variant {variant!r} is running on {sys.platform!r}"
        )

    pinned = GOLDEN_SHA256.get(identity)
    if pinned is None:
        detail = f"encoding identity {identity}: {case} sha256 {actual} ({encoded.size_bytes} B, step {encoded.ladder_step})"
        if variant is not None:
            pytest.fail(f"no pinned golden for qualified variant {variant} at {detail}")
        pytest.skip(f"no pinned golden outside a qualified variant; {detail}")
    assert actual == pinned[case]


def test_every_qualified_variant_has_a_complete_pin() -> None:
    """A pin table that lost a case, or a qualified platform with no pin at all,
    would turn a golden check back into a skip."""
    pinned_platforms = {platform for platform, _, _ in GOLDEN_SHA256}
    assert set(QUALIFIED_VARIANT_PLATFORMS.values()) <= pinned_platforms
    for identity, digests in GOLDEN_SHA256.items():
        assert set(digests) == set(GOLDEN_CASES), identity
        assert all(len(value) == 64 and int(value, 16) >= 0 for value in digests.values()), identity


# E7 / E8 --------------------------------------------------------------------------


@pytest.mark.parametrize(("height", "width"), [(1, 1), (1, 2000), (2000, 1), (3, 1500), (1500, 3)])
def test_extreme_aspect_ratios_and_one_pixel_edges(height: int, width: int) -> None:
    encoded = JpegLadderEncoder(POLICY).encode(_noise(height, width), REPRESENTATIVE_CAP_BYTES)

    assert encoded is not None
    decoded = _decode(encoded.payload)
    assert decoded.size == (encoded.width, encoded.height)
    assert max(decoded.size) <= 1024 and min(decoded.size) >= 1


def test_output_is_baseline_420_without_metadata() -> None:
    encoded = JpegLadderEncoder(POLICY).encode(_smooth(200, 300), SUPPLEMENTAL_CAP_BYTES)
    assert encoded is not None
    decoded = _decode(encoded.payload)

    assert decoded.format == "JPEG" and decoded.mode == "RGB"
    assert "exif" not in decoded.info and "icc_profile" not in decoded.info
    assert not decoded.info.get("progressive") and not decoded.info.get("progression")
    assert JpegImagePlugin.get_sampling(decoded) == 2  # 4:2:0


def test_empty_crop_is_not_admitted_and_malformed_crops_fail_closed() -> None:
    encoder = JpegLadderEncoder(POLICY)

    assert encoder.encode(np.zeros((0, 10, 3), dtype=np.uint8), 1000) is None
    for bad in (
        np.zeros((10, 10), dtype=np.uint8),
        np.zeros((10, 10, 4), dtype=np.uint8),
        np.zeros((10, 10, 3), dtype=np.float32),
        [[1, 2, 3]],
    ):
        with pytest.raises(EvidenceError, match="evidence_crop_invalid"):
            encoder.encode(bad, 1000)  # type: ignore[arg-type]
    with pytest.raises(EvidenceError, match="evidence_cap_invalid"):
        encoder.encode(_smooth(10, 10), 0)


def test_ladder_steps_value_type() -> None:
    assert encoding_ladder(1024, 1024, POLICY)[0] == LadderStep(1024, 85)
