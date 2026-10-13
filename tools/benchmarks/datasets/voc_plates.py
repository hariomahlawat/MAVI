"""Pascal VOC plate adapter for Indian still-image plate data (Stage 4 PR-1, E-A Indian stills).

First consumer: the DataCluster Labs *Indian Number Plates Dataset — Sample* (Hugging Face
``Dataclusterlabspvtltd/indian-number-plates-dataset``, CC BY-NC-ND 4.0, "free sample subset for evaluation
purposes"). Source layout under the descriptor's source root::

    Annotations/<stem>.xml     one Pascal VOC annotation per image
    images/<stem>.jpg          the image

Facts used (dataset card, read 2026-10-12): objects named ``number_plate`` carry a ``bndbox`` and an
``attributes/attribute`` list; the plate text is the attribute ``number_plate_text`` ("all the characters present
within the plate"). Image 0001 of the sample carries only a ``rotation`` attribute, so a plate without the text
attribute is a plate with **no text label** (``textUnusableReason: unlabelled``), never an empty string. The images are
mobile-phone photographs; they have no vehicle box, so E-A needs vehicle candidates from the phase-1 detector
(``adequacy`` vehicle-candidates input) and the domain is not surveillance (recorded as a limitation).

Fail-closed: an XML with a DOCTYPE or ENTITY declaration, a size that disagrees with the image, a box outside the
image or an object of another name is refused and listed in ``exclusions``; a missing image or annotation partner is a
manifest refusal. Layout is not labelled: ``unknown`` (``lineCount`` null); illumination ``unknown``; occlusion from
VOC ``occluded`` (0/1).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, Iterable

from tools.benchmarks.capabilities.plates import truth as truths
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core.identity import S32Error, require, sha256_hex
from tools.benchmarks.capabilities.plates.measure import display_size

ADAPTER_ID = "voc-plates-datacluster"
ADAPTER_VERSION = "1"
DATASET_ID = "datacluster-indian-number-plates-sample"
RELEASE = "Hugging Face Dataclusterlabspvtltd/indian-number-plates-dataset (sample)"
SPLIT = "sample"
TEXT_ATTRIBUTE = "number_plate_text"
PLATE = "number_plate"
STEM = re.compile(r"[A-Za-z0-9_-]{1,128}")
TERMS = "https://huggingface.co/datasets/Dataclusterlabspvtltd/indian-number-plates-dataset"


def descriptor(revision: str, entries: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """The release descriptor at a pinned Hub ``revision`` (commit); the manifest is frozen on intake."""
    document = {
        "schemaVersion": descriptors.SCHEMA,
        "datasetId": DATASET_ID,
        "datasetName": "Indian Number Plates Dataset (DataCluster Labs sample)",
        "release": f"{RELEASE} at {revision}",
        "task": "plate-recognition",
        "source": {"kind": "official", "url": TERMS, "retrievedOn": "2026-10-12"},
        "access": {"mechanism": "direct", "preconditions": [
            "Downloaded by the owner from the publisher's Hugging Face repository at the pinned revision.",
            "The full dataset is a commercial product and is not used."]},
        "intendedUse": "development-benchmarking",
        "researchUse": {
            "status": "RESEARCH-ADMISSIBLE",
            "basis": "CC BY-NC-ND 4.0; the card offers the sample 'for evaluation purposes'. Non-commercial research "
                     "evaluation with attribution; derived crops stay local and are never shared (NoDerivatives "
                     "restricts sharing adapted material), so nothing is redistributed.",
            "termsReference": TERMS,
            "redistribution": "not-permitted-by-default"},
        "splits": [{"name": SPLIT, "labelled": True, "role": "evaluation"}],
        "nativeTaxonomy": [{"code": PLATE, "name": "Number plate",
                            "definition": "DataCluster object 'number_plate' with optional number_plate_text."}],
        "frameTime": {"kind": "still-images"},
        "manifest": {"kind": "file-hashes", "entries": [dict(entry) for entry in entries]},
        "exposure": {"status": "possible",
                     "basis": "A public sample on Hugging Face and Kaggle; public plate recognisers may have seen "
                              "it. Each instrument's exposure is recorded in its specification."},
    }
    return descriptors.check(document)


def _number(element: ElementTree.Element | None, code: str) -> float:
    require(element is not None and element.text is not None, code)
    try:
        value = float(element.text.strip())  # type: ignore[union-attr]
    except ValueError as exc:
        raise S32Error(code) from exc
    require(value == value and value not in (float("inf"), float("-inf")), code)
    return value


def parse_annotation(data: bytes, size: tuple[int, int], code: str) -> list[dict[str, Any]]:
    require(b"<!DOCTYPE" not in data and b"<!ENTITY" not in data, f"{code}:dtd")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise S32Error(f"{code}:xml") from exc
    require(root.tag == "annotation", f"{code}:root")
    width = _number(root.find("size/width"), f"{code}:size")
    height = _number(root.find("size/height"), f"{code}:size")
    require((int(width), int(height)) == size, f"{code}:size_mismatch")
    plates = []
    for index, element in enumerate(root.findall("object")):
        require((element.findtext("name") or "").strip() == PLATE, f"{code}:object_name")
        box = element.find("bndbox")
        require(box is not None, f"{code}:bndbox")
        x1, y1 = _number(box.find("xmin"), f"{code}:bndbox"), _number(box.find("ymin"), f"{code}:bndbox")
        x2, y2 = _number(box.find("xmax"), f"{code}:bndbox"), _number(box.find("ymax"), f"{code}:bndbox")
        require(0 <= x1 < x2 <= size[0] and 0 <= y1 < y2 <= size[1], f"{code}:box_outside_image")
        text = None
        for attribute in element.findall("attributes/attribute"):
            if (attribute.findtext("name") or "").strip() == TEXT_ATTRIBUTE:
                require(text is None, f"{code}:duplicate_text")
                text = attribute.findtext("value") or ""
        occluded = (element.findtext("occluded") or "").strip()
        plates.append(truths.plate(f"plate-{index:02d}", truths.box_polygon(x1, y1, x2 - x1, y2 - y1), text, "unknown",
                                   occluded={"1": True, "0": False}.get(occluded)))
    return plates


class VocPlatesAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def stems(self, entries: Iterable[str]) -> list[str]:
        annotations, images = set(), set()
        for path in entries:
            parts = path.split("/")
            if len(parts) == 2 and parts[0] == "Annotations" and parts[1].endswith(".xml"):
                annotations.add(parts[1].removesuffix(".xml"))
            elif len(parts) == 2 and parts[0] == "images" and parts[1].endswith(".jpg"):
                images.add(parts[1].removesuffix(".jpg"))
        unpaired = sorted(annotations ^ images)
        require(not unpaired, f"source_manifest_incomplete:unpaired:{unpaired[0] if unpaired else ''}")
        for stem in annotations:
            require(STEM.fullmatch(stem) is not None, f"adapter_frame_invalid:{stem}:name")
        return sorted(annotations)

    def plate_items(self, source_root: Path, entries: dict[str, dict[str, Any]]
                    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        items, exclusions = [], []
        for stem in self.stems(entries):
            image_path, annotation_path = f"images/{stem}.jpg", f"Annotations/{stem}.xml"
            image = descriptors.read_verified(entries, source_root, image_path)
            size = display_size(image)  # annotations are in display orientation (EXIF applied)
            prefix = f"adapter_label_invalid:{stem}"
            try:
                plates = parse_annotation(descriptors.read_verified(entries, source_root, annotation_path), size,
                                          prefix)
            except S32Error as exc:
                reason = re.sub(r"[^a-z0-9]+", "-", str(exc)[len(prefix) + 1:].lower()).strip("-")
                exclusions.append({"path": annotation_path, "reason": reason or "annotation-invalid"})
                continue
            items.append({"itemId": stem, "imagePath": image_path, "imageSha256": sha256_hex(image),
                          "frameSize": {"width": size[0], "height": size[1]}, "sequenceId": None, "frameIndex": None,
                          "gtTrackId": None, "vehicleBox": None, "vehicleClass": "unknown", "plates": plates})
        return items, exclusions
