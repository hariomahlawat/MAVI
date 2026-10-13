"""The UC3M-LP adapter (Stage 4 PR-1, E-A stills; Ramajo-Ballester et al., Robotics and Autonomous Systems 172, 2024).

UC3M-LP holds 1,975 street photographs (train 1,580, test 395) of Spanish vehicles with 2,547 plates. Each plate has a
four-corner polygon, per-character boxes and a two-letter code: plate type (A long one-row white; B motorcycle
two-row; C light-motorcycle one-row yellow; D taxi/VTC blue; E trailer red) and lighting (D day, N night). Source:
the authors' Zenodo record 17152029 (CC BY 4.0; ``UC3M-LP.zip``, MD5 published); the repository
``github.com/ramajoballester/uc3m-lp`` (ODbL-1.0) documents the format. Source layout under the descriptor's source
root (the archive extracted)::

    <split>/<NNNNN>.jpg     the photograph
    <split>/<NNNNN>.json    {imagePath, imageHeight, imageWidth, lps: [{lp_id, poly_coord, characters}]}
    train.txt, test.txt     the split lists (stems)

Facts used: ``lp_id`` is ``<type><lighting>-<text>``; for GDPR the authors blurred some characters in every plate and
label each as ``*`` (README "privacy modifications"), so the text is a **masked label** (protocol §5 R6). ``poly_coord``
is TL, TR, BR, BL in image pixels. The JSON's own ``imagePath`` is not relied on (the published sample
``00026.json`` names ``00027.jpg``): the image is the same-stem JPEG, and the declared size must equal its header.

Fail-closed: an unknown type or lighting code, a malformed ``lp_id``, a polygon that is not four points inside the
image, or a size mismatch refuses that annotation (listed in ``exclusions``). Measurement uses ``test`` only; ``train``
stays unread. Mappings: type B and C → vehicle ``motorcycle``; D → ``car``; E → ``commercial`` (trailer); A →
``unknown`` (cars and goods vehicles share the plate). Layout: B two-line, others one-line. Lighting D/N → day/night.
There is no vehicle box: E-A uses phase-1 detector vehicle candidates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from tools.benchmarks.capabilities.plates import truth as truths
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core.identity import S32Error, require, sha256_hex
from tools.benchmarks.capabilities.plates.measure import display_size

ADAPTER_ID = "uc3m-lp"
ADAPTER_VERSION = "1"
DATASET_ID = "uc3m-lp"
RELEASE = "UC3M-LP (Zenodo record 17152029, v1, 2024-02-01; UC3M-LP.zip md5 496e3b5e66b78d231f71d85c0e5e11a3)"
SPLITS = ("test", "train")
MEASUREMENT_SPLIT = "test"
LP_ID = re.compile(r"([A-E])([DN])-(.+)")
STEM = re.compile(r"[0-9]{5}")
VEHICLE = {"A": "unknown", "B": "motorcycle", "C": "motorcycle", "D": "car", "E": "commercial"}
LAYOUT = {"A": "one-line", "B": "two-line", "C": "one-line", "D": "one-line", "E": "one-line"}
LIGHT = {"D": "day", "N": "night"}
ZENODO = "https://zenodo.org/records/17152029"


def descriptor(entries: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    document = {
        "schemaVersion": descriptors.SCHEMA,
        "datasetId": DATASET_ID,
        "datasetName": "UC3M-LP Spanish licence plates",
        "release": RELEASE,
        "task": "plate-recognition",
        "source": {"kind": "official", "url": ZENODO, "retrievedOn": "2026-10-12"},
        "access": {"mechanism": "direct", "preconditions": [
            "Downloaded from the authors' Zenodo record (open access); the archive MD5 equals the record's."]},
        "intendedUse": "development-benchmarking",
        "researchUse": {
            "status": "RESEARCH-ADMISSIBLE",
            "basis": "The authors publish the data openly: the Zenodo record states CC BY 4.0 and the documenting "
                     "repository states ODbL-1.0. Both permit research evaluation with attribution; nothing is "
                     "redistributed. The images were anonymised by the authors (blurred characters, altered colours).",
            "termsReference": f"{ZENODO}; https://github.com/ramajoballester/uc3m-lp",
            "redistribution": "not-permitted-by-default"},
        "splits": [{"name": "test", "labelled": True, "role": "evaluation"},
                   {"name": "train", "labelled": True, "role": "reserved-unread"}],
        "nativeTaxonomy": [{"code": code, "name": f"Type {code}", "definition": definition} for code, definition in (
            ("A", "Long one-row white plate (most vehicles)."), ("B", "Motorcycle two-row white plate."),
            ("C", "Light-motorcycle one-row yellow plate."), ("D", "Taxi/VTC blue plate."),
            ("E", "Trailer-tow red plate."))],
        "frameTime": {"kind": "still-images"},
        "manifest": {"kind": "file-hashes", "entries": [dict(entry) for entry in entries]},
        "exposure": {"status": "possible",
                     "basis": "An open benchmark since 2024; public plate recognisers may have trained on it. The "
                              "phase-1 detector trains on COCO 2017 only."},
    }
    return descriptors.check(document)


def parse(data: bytes, size: tuple[int, int], code: str) -> list[dict[str, Any]]:
    try:
        document = json.loads(data)
    except ValueError as exc:
        raise S32Error(f"{code}:json") from exc
    require(isinstance(document, dict) and isinstance(document.get("lps"), list), f"{code}:shape")
    require((document.get("imageWidth"), document.get("imageHeight")) == size, f"{code}:size_mismatch")
    plates = []
    for index, lp in enumerate(document["lps"]):
        match = LP_ID.fullmatch(str(lp.get("lp_id", "")))
        require(match is not None, f"{code}:lp_id")
        kind, light, text = match.groups()
        polygon = lp.get("poly_coord")
        require(isinstance(polygon, list) and len(polygon) == 4
                and all(isinstance(p, list) and len(p) == 2 and all(type(v) in (int, float) for v in p)
                        for p in polygon), f"{code}:polygon")
        require(all(0 <= p[0] <= size[0] and 0 <= p[1] <= size[1] for p in polygon), f"{code}:polygon_outside_image")
        plates.append(truths.plate(f"plate-{index:02d}", [[float(p[0]), float(p[1])] for p in polygon], text,
                                   LAYOUT[kind], illumination=LIGHT[light]) | {"_vehicleClass": VEHICLE[kind]})
    return plates


class Uc3mLpAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def stems(self, entries: Iterable[str], split: str) -> list[str]:
        require(split in SPLITS, f"adapter_split_unknown:{split}")
        images, annotations = set(), set()
        for path in entries:
            parts = path.split("/")
            if len(parts) == 2 and parts[0] == split:
                stem, _, extension = parts[1].partition(".")
                if extension == "jpg":
                    images.add(stem)
                elif extension == "json":
                    annotations.add(stem)
        unpaired = sorted(images ^ annotations)
        require(not unpaired, f"source_manifest_incomplete:unpaired:{unpaired[0] if unpaired else ''}")
        for stem in images:
            require(STEM.fullmatch(stem) is not None, f"adapter_frame_invalid:{stem}:name")
        return sorted(images)

    def plate_items(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str
                    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        listed = descriptors.read_verified(entries, source_root, f"{split}.txt").decode("ascii").split()
        stems = self.stems(entries, split)
        require(sorted(listed) == stems, f"source_manifest_incomplete:split_list:{split}")
        items, exclusions = [], []
        for stem in stems:
            image_path, annotation_path = f"{split}/{stem}.jpg", f"{split}/{stem}.json"
            image = descriptors.read_verified(entries, source_root, image_path)
            size = display_size(image)  # annotations are in display orientation (EXIF applied)
            prefix = f"adapter_label_invalid:{stem}"
            try:
                plates = parse(descriptors.read_verified(entries, source_root, annotation_path), size, prefix)
            except S32Error as exc:
                reason = re.sub(r"[^a-z0-9]+", "-", str(exc)[len(prefix) + 1:].lower()).strip("-")
                exclusions.append({"path": annotation_path, "reason": reason or "annotation-invalid"})
                continue
            classes = {plate.pop("_vehicleClass") for plate in plates}
            items.append({"itemId": stem, "imagePath": image_path, "imageSha256": sha256_hex(image),
                          "frameSize": {"width": size[0], "height": size[1]}, "sequenceId": None, "frameIndex": None,
                          "gtTrackId": None, "vehicleBox": None,
                          "vehicleClass": classes.pop() if len(classes) == 1 else "unknown", "plates": plates})
        return items, exclusions
