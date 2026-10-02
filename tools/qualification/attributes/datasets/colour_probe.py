"""``mavi-dev-colour-probe-v1``: a deterministic development colour probe (plan §7).

It is **not PC-B0 or VC-B0** and fixes nothing about them. Every value that affects the
output is read from the committed configuration ``data/mavi-dev-colour-probe-v1.json``:
- region geometry and rounding;
- decoding;
- sRGB linearisation, the sRGB→XYZ matrix and the D65 white point;
- the CIE 1976 L*a*b* constants and the Lab centres;
- the distance, tie rules, minimum region size and minimum winning share.

The method identity is the SHA-256 of that configuration in canonical JSON. Changing any
value changes the identity.

For one crop and one attribute region:
1. decode with Pillow and ``convert("RGB")``, with no resize;
2. convert every region pixel to Lab in float64;
3. assign each pixel the nearest centre by CIE76, ties to the first centre in task
   schema order;
4. the most frequent name wins, ties to the first in schema order.

The probe abstains with ``undecodable``, ``insufficient-area`` (too few region pixels) or
``ambiguous`` (winning share below the minimum).
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path

from attributes.corpus.canonical import CorpusError, canonical_json, require, require_keys, sha256_hex
from attributes.corpus.task import Task, load_task

PROBE_SCHEMA = "mavi-dev-colour-probe-config-v1"
PROBE_ID = "mavi-dev-colour-probe-v1"
CONFIG_PATH = Path(__file__).resolve().parent / "data" / "mavi-dev-colour-probe-v1.json"
ABSTENTIONS = ("ambiguous", "insufficient-area", "undecodable")
CENTRE_SETS = {"person": "person-upper-colour", "vehicle": "vehicle-colour"}  # schema order comes from these task attributes


def _number(value: object, code: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), code)
    return float(value)


def _fraction_pair(value: object, code: str) -> tuple[float, float]:
    require(isinstance(value, list) and len(value) == 2, code)
    start, end = (_number(v, code) for v in value)
    require(0 <= start < end <= 1, code)
    return start, end


def parse_probe_config(document: object, task: Task | None = None) -> dict:
    """Validate the full probe configuration; every behavioural value must be present."""
    code = "colour_probe_config_invalid"
    task = task or load_task()
    require(isinstance(document, dict), code)
    require_keys(document, code, ("schemaVersion", "methodId", "status", "decoding", "regions", "regionRounding", "srgbLinearisation",
                                  "srgbToXyz", "whitePointD65", "cieLab", "arithmetic", "centres", "centreDerivation", "distance",
                                  "pixelTies", "winnerTies", "minRegionPixels", "minWinningShare", "abstentionReasons"))
    require(document["schemaVersion"] == PROBE_SCHEMA and document["methodId"] == PROBE_ID, f"{code}:schema")
    require(document["decoding"] == {"library": "Pillow", "convert": "RGB", "resize": "none", "onDecodeError": "abstain:undecodable"}, f"{code}:decoding")
    require(document["regionRounding"] == "pixel bounds are floor(fraction * size); start inclusive, end exclusive", f"{code}:rounding")
    require(document["arithmetic"] == "float64 throughout; no quantisation", f"{code}:arithmetic")
    require(document["distance"] == "cie76", f"{code}:distance")
    require(document["pixelTies"] == "first centre in task schema order" and document["winnerTies"] == "first name in task schema order", f"{code}:ties")
    require(document["abstentionReasons"] == list(ABSTENTIONS), f"{code}:abstentions")
    regions = document["regions"]
    require(isinstance(regions, dict) and set(regions) == {"person-upper-colour", "person-lower-colour", "vehicle-colour"}, f"{code}:regions")
    for attribute, region in regions.items():
        require(isinstance(region, dict), f"{code}:region")
        require_keys(region, f"{code}:region", ("objectClass", "implemented", "rows", "columns"))
        require(region["objectClass"] == task.attribute(attribute).object_class, f"{code}:region_class:{attribute}")
        require(isinstance(region["implemented"], bool), f"{code}:region_implemented:{attribute}")
        _fraction_pair(region["rows"], f"{code}:region_rows:{attribute}")
        _fraction_pair(region["columns"], f"{code}:region_columns:{attribute}")
    lin = document["srgbLinearisation"]
    require(isinstance(lin, dict) and set(lin) == {"threshold", "linearDivisor", "offset", "scale", "exponent", "inputScale"}, f"{code}:linearisation")
    for value in lin.values():
        require(_number(value, f"{code}:linearisation") > 0, f"{code}:linearisation")
    matrix = document["srgbToXyz"]
    require(isinstance(matrix, list) and len(matrix) == 3 and all(isinstance(r, list) and len(r) == 3 for r in matrix), f"{code}:matrix")
    for row in matrix:
        for value in row:
            _number(value, f"{code}:matrix")
    white = document["whitePointD65"]
    require(isinstance(white, list) and len(white) == 3 and all(_number(v, f"{code}:white") > 0 for v in white), f"{code}:white")
    lab = document["cieLab"]
    require(isinstance(lab, dict) and set(lab) == {"epsilon", "kappa", "cubeRootExponent", "lightnessScale", "lightnessOffset", "aScale", "bScale"}, f"{code}:lab")
    for key in ("epsilon", "kappa", "lightnessScale", "lightnessOffset", "aScale", "bScale"):
        require(_number(lab[key], f"{code}:lab") > 0, f"{code}:lab")
    require(isinstance(lab["cubeRootExponent"], list) and len(lab["cubeRootExponent"]) == 2 and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in lab["cubeRootExponent"]), f"{code}:lab")
    centres = document["centres"]
    require(isinstance(centres, dict) and set(centres) == set(CENTRE_SETS), f"{code}:centres")
    for object_class, attribute in CENTRE_SETS.items():
        names = list(task.attribute(attribute).values)
        given = centres[object_class]
        require(isinstance(given, dict), f"{code}:centres:{object_class}")
        unknown = sorted(set(given) - set(names))
        require(not unknown, f"{code}:centre_unknown:{object_class}:{','.join(unknown)}")
        missing = [n for n in names if n not in given]
        require(not missing, f"{code}:centre_missing:{object_class}:{','.join(missing)}")
        for name in names:
            require(isinstance(given[name], list) and len(given[name]) == 3, f"{code}:centre_shape:{object_class}:{name}")
            for value in given[name]:
                _number(value, f"{code}:centre_value:{object_class}:{name}")
    require(isinstance(document["minRegionPixels"], int) and not isinstance(document["minRegionPixels"], bool) and document["minRegionPixels"] > 0, f"{code}:min_pixels")
    share = _number(document["minWinningShare"], f"{code}:min_share")
    require(0 < share <= 1, f"{code}:min_share")
    return document


def load_probe_config(path: Path = CONFIG_PATH) -> dict:
    return parse_probe_config(json.loads(Path(path).read_text(encoding="utf-8")))


def probe_sha256(config: dict) -> str:
    return sha256_hex(canonical_json(config))


class ColourProbe:
    """A configured probe. Construct once per configuration; ``predict`` is deterministic."""

    def __init__(self, config: dict, task: Task | None = None):
        import numpy as np  # declared MAVI Vision project dependency, as Pillow is

        task = task or load_task()
        self.config = config
        self.sha256 = probe_sha256(config)
        self._np = np
        lin, lab = config["srgbLinearisation"], config["cieLab"]
        self._lin = {k: float(v) for k, v in lin.items()}
        self._matrix = np.array(config["srgbToXyz"], dtype=np.float64)
        self._white = np.array(config["whitePointD65"], dtype=np.float64)
        self._lab = {k: (float(v) if not isinstance(v, list) else v) for k, v in lab.items()}
        self._names: dict[str, list[str]] = {}
        self._centres: dict[str, object] = {}
        for object_class, attribute in CENTRE_SETS.items():
            names = list(task.attribute(attribute).values)  # task schema order: the tie order
            self._names[object_class] = names
            self._centres[object_class] = np.array([config["centres"][object_class][n] for n in names], dtype=np.float64)

    def to_lab(self, rgb):
        """uint8 or float RGB array (..., 3) to Lab (float64), entirely from the configuration."""
        np, lin, lab = self._np, self._lin, self._lab
        c = np.asarray(rgb, dtype=np.float64) / lin["inputScale"]
        linear = np.where(c <= lin["threshold"], c / lin["linearDivisor"], ((c + lin["offset"]) / lin["scale"]) ** lin["exponent"])
        xyz = (linear @ self._matrix.T) / self._white
        numerator, denominator = lab["cubeRootExponent"]
        f = np.where(xyz > lab["epsilon"], xyz ** (numerator / denominator), (lab["kappa"] * xyz + lab["lightnessOffset"]) / lab["lightnessScale"])
        return np.stack([lab["lightnessScale"] * f[..., 1] - lab["lightnessOffset"],
                         lab["aScale"] * (f[..., 0] - f[..., 1]),
                         lab["bScale"] * (f[..., 1] - f[..., 2])], axis=-1)

    def predict(self, attribute: str, image_bytes: bytes) -> dict:
        """``{outcome: value, value, share: {numerator, denominator}}`` or ``{outcome: abstain, reason}``."""
        np = self._np
        region = self.config["regions"].get(attribute)
        require(region is not None, f"colour_probe_attribute_unknown:{attribute}")
        require(region["implemented"], f"colour_probe_region_not_implemented:{attribute}")
        from PIL import Image  # declared MAVI Vision dependency

        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
        except Exception:  # Pillow raises several types for corrupt or unknown data
            return {"outcome": "abstain", "reason": "undecodable"}
        height, width = pixels.shape[0], pixels.shape[1]
        (r0, r1), (c0, c1) = region["rows"], region["columns"]
        block = pixels[math.floor(r0 * height):math.floor(r1 * height), math.floor(c0 * width):math.floor(c1 * width)].reshape(-1, 3)
        if block.shape[0] < self.config["minRegionPixels"]:
            return {"outcome": "abstain", "reason": "insufficient-area"}
        object_class = region["objectClass"]
        lab = self.to_lab(block)
        centres = self._centres[object_class]
        distances = ((lab[:, None, :] - centres[None, :, :]) ** 2).sum(axis=-1)  # CIE76 order is preserved by the square
        nearest = distances.argmin(axis=1)  # argmin returns the first minimum: schema order breaks pixel ties
        counts = np.bincount(nearest, minlength=len(centres))
        winner = int(counts.argmax())  # first maximum: schema order breaks winner ties
        total = int(block.shape[0])
        if counts[winner] < self.config["minWinningShare"] * total:
            return {"outcome": "abstain", "reason": "ambiguous"}
        return {"outcome": "value", "value": self._names[object_class][winner], "share": {"numerator": int(counts[winner]), "denominator": total}}


__all__ = ["ABSTENTIONS", "CONFIG_PATH", "ColourProbe", "CorpusError", "PROBE_ID", "load_probe_config", "parse_probe_config", "probe_sha256"]
