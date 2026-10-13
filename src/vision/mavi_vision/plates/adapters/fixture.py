"""The Development fixture plate detector and recogniser (Stage 4 PR-3; plan §7, PR-3).

Model-free and exactly reproducible: every output is derived from the verified crop SHA-256 and the
fixture seed, never from a clock or a random source. It exercises the real lease, evidence, upload and
completion path with plausible shapes — zero to two plates, ranked readings, two-line and unreadable
plates — and claims nothing about any plate. Its pipeline profile is ``developmentOnly`` and the
registry refuses it in Production.
"""

from __future__ import annotations

import hashlib

from PIL import Image

from mavi_vision.plates.inference import PlateBox, Reading, VerifiedCrop

FIXTURE_ADAPTER_ID = "plates-fixture-v1"
_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
_STATES = ("KA", "MH", "DL", "TN", "GJ", "UP")


def _stream(seed: str, *parts: object) -> bytes:
    text = "\0".join([seed, *(str(part) for part in parts)])
    return hashlib.sha256(text.encode("utf-8")).digest()


class FixturePlateDetector:
    def __init__(self, seed: str) -> None:
        if not seed:
            raise ValueError("plate_fixture_seed_required")
        self._seed = seed

    def detect(self, crop: Image.Image, verified: VerifiedCrop) -> list[PlateBox]:
        width, height = crop.size
        digest = _stream(self._seed, "detect", verified.sha256)
        count = digest[0] % 3  # 0, 1 or 2 boxes
        boxes: list[PlateBox] = []
        for index in range(count):
            box_width = max(1, min(width, width * (20 + digest[1 + index] % 20) // 100))
            box_height = max(1, min(height, height * (6 + digest[3 + index] % 6) // 100))
            x = (width - box_width) * (digest[5 + index] % 101) // 100
            y = (height - box_height) * (50 + digest[7 + index] % 51) // 100
            score = round(0.2 + (digest[9 + index] % 80) / 100, 2)
            boxes.append(PlateBox(x, y, box_width, box_height, score))
        return boxes


class FixturePlateRecogniser:
    def __init__(self, seed: str) -> None:
        if not seed:
            raise ValueError("plate_fixture_seed_required")
        self._seed = seed

    def read(self, region: Image.Image, verified: VerifiedCrop, box: PlateBox) -> list[Reading]:
        digest = _stream(self._seed, "read", verified.sha256, box.x, box.y, box.width, box.height)
        state = _STATES[digest[0] % len(_STATES)]
        district = f"{digest[1] % 100:02d}"
        series = _LETTERS[digest[2] % len(_LETTERS)] + _LETTERS[digest[3] % len(_LETTERS)]
        number = f"{int.from_bytes(digest[4:6], 'big') % 10_000:04d}"
        two_line = digest[6] % 5 == 0
        text = f"{state}{district}\n{series} {number}" if two_line else f"{state} {district} {series} {number}"
        first = round(0.3 + (digest[7] % 70) / 100, 2)
        # A second hypothesis differs in one character, as real OCR alternatives do.
        alternative = text[:-1] + str((int(text[-1]) + 1) % 10)
        second = round(first * (digest[8] % 90) / 100, 2)
        return [Reading(text, first), Reading(alternative, second)]


__all__ = ["FIXTURE_ADAPTER_ID", "FixturePlateDetector", "FixturePlateRecogniser"]
