"""The BDD100K box-tracking ("MOT 2020", ``box_track_20``) adapter (S3.2d-1 plan §16 slice 4).

Reads Scalabel-format labels from the canonical source layout (``docs/qualification/stage3/
bdd100k-mot-acquisition.md``), always through the reconciled, hash-verified manifest:

    labels/box_track_20/<split>/<videoName>.json       one JSON list of frame records per video
    images/track/<split>/<videoName>/<name>            the frame image a record's ``name`` names

Facts used, with their sources (all read 2026-10-04; the capability matrix records them):

- Label files are Scalabel format: a list of frame objects with ``name``, ``videoName``, ``frameIndex`` and
  ``labels[] {id, category, attributes, box2d {x1, y1, x2, y2}}`` (BDD100K ``doc/source/format.rst``; Scalabel
  ``doc/src/format.rst``). Without a ``url`` a frame's file is ``<data_root>/<videoName>/<name>`` (Scalabel), so the
  image path comes from the record, never from a frame number: in the official Scalabel sample, ``frameIndex`` 0 is
  ``…-0000001.jpg``.
- "The same object in each video has the same label id but objects across videos are always distinct even if they
  have the same id" (``download.rst``): the label ``id`` is the ``gtTrackId`` within its sequence.
- Box tracking evaluates eight classes (``format.rst``). The official evaluation also names three distractor classes,
  ``other person``, ``other vehicle`` and ``trailer`` (``evaluate.rst``), and the official config
  ``bdd100k/configs/box_track.toml`` folds the raw names ``bike, caravan, motor, person, van`` into the eight. The
  adapter applies that official alias table and keeps the distractors as native classes; any other category is
  refused, because its class meaning is unknown.
- ``box2d`` includes the pixel at ``x2, y2``: width ``x2 - x1 + 1`` (Scalabel; ``format.rst``). Official labels reach
  ``x2 = image width`` at the right edge (the official Scalabel sample), so the inclusive extent is clipped to the
  image before normalisation: a sub-pixel effect on edge boxes. A box with no area left inside the image is refused.
- Frames are 5 Hz, "resampled to 5Hz from 30Hz" (``download.rst``): the descriptor declares ``index-at-fps`` 5/1, and
  label ``frameIndex`` k is media offset ``k × 200`` ms in the derived labelled-rate video.
- Frame size comes from each frame's own JPEG header (all frames of a video must agree), never from a constant.

Auxiliary attributes (``occluded``, ``truncated``, ``crowd`` and any other) do not change ground truth. In
particular ``crowd`` is **not** turned into an ignore region: the official evaluation ignores false positives that
overlap a crowd box by more than half (``evaluate.rst``), which is not MAVI's ignore rule, so crowd boxes stay
ordinary ground truth of their native class and results are not comparable with official BDD100K MOT scores. The
distractor classes likewise stay ordinary ground truth with an ``unsupported`` mapping. No ignore regions are emitted.
"""

from __future__ import annotations

import copy
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core.identity import rational, require

GT_TRACK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}")
FRAME_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}")
ADAPTER_ID = "bdd100k-mot"
ADAPTER_VERSION = "1"
DATASET_ID = "bdd100k-mot-2020"
RELEASE = "MOT 2020 (box_track_20)"
LABELS = "labels/box_track_20"
IMAGES = "images/track"
FPS = (5, 1)
SOURCE_DOCS = "https://github.com/bdd100k/bdd100k/tree/master/doc/source"
NO_DEFINITION = ("BDD100K publishes no written definition in its repository documentation (format.rst, read "
                 "2026-10-04); meaning is taken from the category name in a road-scene dataset.")
# native code, raw Scalabel category, name, definition
TAXONOMY = (
    ("bicycle", "bicycle", "Bicycle", f"BDD100K box-tracking category 'bicycle'. {NO_DEFINITION}"),
    ("bus", "bus", "Bus", f"BDD100K box-tracking category 'bus'. {NO_DEFINITION}"),
    ("car", "car", "Car", f"BDD100K box-tracking category 'car'; the official box_track config folds the raw "
                          f"names 'van' and 'caravan' into it. {NO_DEFINITION}"),
    ("motorcycle", "motorcycle", "Motorcycle", f"BDD100K box-tracking category 'motorcycle'; the official config "
                                               f"folds the raw name 'motor' into it. {NO_DEFINITION}"),
    ("other-person", "other person", "Other person", "BDD100K distractor category 'other person' (evaluate.rst: "
                                                     "an ignored region in official scoring)."),
    ("other-vehicle", "other vehicle", "Other vehicle", "BDD100K distractor category 'other vehicle' (evaluate.rst: "
                                                        "an ignored region in official scoring)."),
    ("pedestrian", "pedestrian", "Pedestrian", f"BDD100K box-tracking category 'pedestrian'; the official config "
                                               f"folds the raw name 'person' into it. {NO_DEFINITION}"),
    ("rider", "rider", "Rider", f"BDD100K box-tracking category 'rider'. {NO_DEFINITION}"),
    ("trailer", "trailer", "Trailer", "BDD100K distractor category 'trailer' (evaluate.rst: an ignored region in "
                                      "official scoring)."),
    ("train", "train", "Train", f"BDD100K box-tracking category 'train'. {NO_DEFINITION}"),
    ("truck", "truck", "Truck", f"BDD100K box-tracking category 'truck'. {NO_DEFINITION}"),
)
# Official raw-name aliases (bdd100k/configs/box_track.toml [name_mapping]).
ALIASES = {"bike": "bicycle", "caravan": "car", "motor": "motorcycle", "person": "pedestrian", "van": "car"}
CATEGORIES = {raw: code for code, raw, _, _ in TAXONOMY} | ALIASES
# Practical (operational-compatibility) mapping; differences are caveats, recorded in the reasons.
MAPPINGS = (
    ("bicycle", None, "unsupported", "outside-capability",
     "Not one of the four MAVI motor-vehicle classes (harness plan section 12)."),
    ("bus", "bus", "exact",  None,
     "Same practical meaning: passenger buses and coaches. Caveat: the minibus boundary is not documented by "
     "BDD100K."),
    ("car", "car", "exact", None,
     "Same practical meaning: passenger cars. Caveat: the official config folds raw 'van' and 'caravan' into "
     "'car', while the MAVI guide (s3-2-labeling-guide.md) puts windowless cargo vans in truck, so some BDD100K "
     "cars may be MAVI trucks; recorded as a domain caveat and a taxonomy-review item."),
    ("motorcycle", "motorcycle", "exact", None,
     "Same practical meaning: motorised two-wheelers ridden seated. Caveat: scooter and moped inclusion is not "
     "stated in the repository documentation; the official config folds raw 'motor' into it."),
    ("other-person", None, "unsupported", "outside-capability", "A person, not a Vehicle."),
    ("other-vehicle", None, "unsupported", "vehicle-unresolved",
     "A vehicle whose type the dataset does not resolve into one of the four MAVI classes."),
    ("pedestrian", None, "unsupported", "outside-capability", "A person, not a Vehicle."),
    ("rider", None, "unsupported", "outside-capability", "The person on a two-wheeler, not the vehicle."),
    ("trailer", None, "unsupported", "vehicle-unresolved",
     "Towed equipment; the MAVI guide resolves a trailer only together with its towing vehicle."),
    ("train", None, "unsupported", "outside-capability",
     "Rail vehicle, outside the four MAVI road-vehicle classes (harness plan section 12)."),
    ("truck", "truck", "exact", None,
     "Same practical meaning: goods and work vehicles. Caveat: pickup and cargo-van handling is not stated in "
     "the repository documentation."),
)


def descriptor(entries: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """The release descriptor; the committed template is this with an empty manifest (pre-acquisition)."""
    document = {
        "schemaVersion": descriptors.SCHEMA,
        "datasetId": DATASET_ID,
        "datasetName": "BDD100K box tracking",
        "release": RELEASE,
        "task": "box-tracking",
        "source": {"kind": "official", "url": "https://dl.cv.ethz.ch/bdd100k/data/", "retrievedOn": "2026-10-04"},
        "access": {"mechanism": "agreement", "preconditions": [
            "The operator agrees to the BDD100K license before downloading (download.rst: 'By downloading the "
            "data, you agree to the BDD100K license'); acceptance is never automated."]},
        "intendedUse": "development-benchmarking",
        "researchUse": {
            "status": "RESEARCH-ADMISSIBLE",
            "basis": "The BDD100K license permits use 'for educational, research, and not-for-profit purposes, "
                     "without fee'; to be confirmed against the licence accepted at download.",
            "termsReference": f"{SOURCE_DOCS}/license.rst",
            "redistribution": "not-permitted-by-default"},
        "splits": [{"name": "val", "labelled": True, "role": "evaluation"}],
        "nativeTaxonomy": [{"code": code, "name": name, "definition": definition}
                           for code, _, name, definition in TAXONOMY],
        "frameTime": {"kind": "index-at-fps", "fpsNumerator": FPS[0], "fpsDenominator": FPS[1]},
        "manifest": {"kind": "file-hashes", "entries": [dict(entry) for entry in entries]},
        "exposure": {"status": "unknown",
                     "basis": "Not yet assessed: the detector's training data must be checked for BDD100K before "
                              "a result is reported (harness plan section 13)."},
    }
    return descriptors.check(document)


def mapping() -> dict[str, Any]:
    rows = []
    for native, mavi, kind, unsupported, reason in MAPPINGS:
        row = {"nativeClass": native, "maviClass": mavi, "kind": kind, "reason": reason,
               "evaluation": {"exact": "scored", "subset": "subset-conditional", "unsupported": "excluded"}[kind]}
        if unsupported is not None:
            row["unsupportedKind"] = unsupported
        rows.append(row)
    return {"schemaVersion": "benchmark-class-mapping-v1", "datasetId": DATASET_ID, "release": RELEASE,
            "capability": "mavi-vehicle-subclass-v1", "mappings": rows}


def annotation_path(split: str, sequence: str) -> str:
    return f"{LABELS}/{split}/{sequence}.json"


def frame_path(split: str, sequence: str, name: str) -> str:
    return f"{IMAGES}/{split}/{sequence}/{name}"


# JPEG frame size (SOF header), so frame geometry comes from the verified image bytes themselves.

_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
_STANDALONE = {0x01, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7}


def jpeg_size(data: bytes, code: str) -> tuple[int, int]:
    """``(width, height)`` from the first SOF segment of a baseline or progressive JPEG."""
    require(data[:2] == b"\xff\xd8", code)
    position = 2
    while True:
        require(position + 4 <= len(data) and data[position] == 0xFF, code)
        marker = data[position + 1]
        if marker == 0xFF:  # fill byte
            position += 1
            continue
        if marker in _STANDALONE:
            position += 2
            continue
        require(marker not in (0xD8, 0xD9, 0xDA), code)  # no SOF before the scan or the end
        length = int.from_bytes(data[position + 2:position + 4], "big")
        require(length >= 2 and position + 2 + length <= len(data), code)
        if marker in _SOF:
            require(length >= 7, code)
            height = int.from_bytes(data[position + 5:position + 7], "big")
            width = int.from_bytes(data[position + 7:position + 9], "big")
            require(width > 0 and height > 0, code)
            return width, height
        position += 2 + length


def _coordinate(value: Any, code: str) -> Fraction:
    require(type(value) in (int, float) and math.isfinite(value), code)
    return Fraction(value)


class Bdd100kMotAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def native_classes(self) -> set[str]:
        return {code for code, _, _, _ in TAXONOMY}

    def sequences_described(self, manifest_paths: Iterable[str], split: str) -> list[str]:
        """Sequences named by label files or frame directories of ``split`` (paths of other splits or packages
        under the source root are not this split's members)."""
        found = set()
        for path in manifest_paths:
            parts = path.split("/")
            if parts[:3] == [*LABELS.split("/"), split] and len(parts) == 4 and parts[3].endswith(".json"):
                found.add(parts[3].removesuffix(".json"))
            elif parts[:3] == [*IMAGES.split("/"), split] and len(parts) == 5:
                found.add(parts[3])
        return sorted(found)

    def discover(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str) -> list[str]:
        """A sequence is complete when its label file and every frame image it names are manifest members."""
        complete = []
        for sequence in self.sequences_described(entries, split):
            if annotation_path(split, sequence) not in entries:
                continue
            frames = self._frames(source_root, entries, split, sequence)
            if all(frame_path(split, sequence, frame["name"]) in entries for frame in frames):
                complete.append(sequence)
        return complete

    def frame_paths(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str,
                    sequence: str) -> list[tuple[int, str]]:
        """``(frameIndex, manifest path)`` of every labelled frame image, in index order (the derived video)."""
        return [(frame["frameIndex"], frame_path(split, sequence, frame["name"]))
                for frame in self._frames(source_root, entries, split, sequence)]

    def _frames(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str,
                sequence: str) -> list[dict[str, Any]]:
        """The label file's frame records, checked and sorted by ``frameIndex``. Only the fields the benchmark
        needs are read; Scalabel's optional fields (frame attributes, timestamps, label attributes) are ignored."""
        from tools.benchmarks.core._stage3 import artefacts

        bad = f"adapter_label_invalid:{sequence}"
        require(GT_TRACK_ID.fullmatch(sequence) is not None, f"{bad}:sequence_id")
        data = descriptors.read_verified(entries, source_root, annotation_path(split, sequence))
        records = artefacts.parse_json(data, bad)
        require(isinstance(records, list) and records, f"{bad}:frames")
        frames, indices, names = [], set(), set()
        for record in records:
            require(isinstance(record, dict) and record.get("videoName") == sequence, f"{bad}:video_name")
            index, name = record.get("frameIndex"), record.get("name")
            require(type(index) is int and index >= 0, f"{bad}:frame_index")
            require(isinstance(name, str) and FRAME_NAME.fullmatch(name) is not None, f"{bad}:frame_name")
            require(index not in indices, f"{bad}:duplicate_frame_index")
            require(name not in names, f"{bad}:duplicate_frame_name")
            indices.add(index)
            names.add(name)
            labels = record.get("labels")
            labels = [] if labels is None else labels  # Scalabel: labels are optional on a frame
            require(isinstance(labels, list), f"{bad}:labels")
            objects, seen = [], set()
            for label in labels:
                require(isinstance(label, dict), f"{bad}:label")
                track_id = label.get("id")
                require(isinstance(track_id, str) and GT_TRACK_ID.fullmatch(track_id) is not None,
                        f"{bad}:object_id")
                # One identity has at most one box per labelled instant: never deduplicated.
                require(track_id not in seen, f"{bad}:duplicate_track_id")
                seen.add(track_id)
                category = label.get("category")
                require(isinstance(category, str) and category in CATEGORIES, f"{bad}:category")
                box = label.get("box2d")
                require(isinstance(box, dict) and {"x1", "y1", "x2", "y2"} <= set(box), f"{bad}:box")
                x1, y1, x2, y2 = (_coordinate(box[key], f"{bad}:box") for key in ("x1", "y1", "x2", "y2"))
                require(x1 <= x2 and y1 <= y2, f"{bad}:box")
                objects.append({"id": track_id, "class": CATEGORIES[category], "box": (x1, y1, x2, y2)})
            frames.append({"frameIndex": index, "name": name, "objects": objects})
        return sorted(frames, key=lambda frame: frame["frameIndex"])

    def ground_truth(self, source_root: Path, entries: dict[str, dict[str, Any]], descriptor: dict[str, Any],
                     split: str, sequence_id: str) -> dict[str, Any]:
        require(descriptor["datasetId"] == DATASET_ID, f"adapter_descriptor_mismatch:{descriptor['datasetId']}")
        bad = f"adapter_label_invalid:{sequence_id}"
        frames = self._frames(source_root, entries, split, sequence_id)
        size = None
        for frame in frames:
            path = frame_path(split, sequence_id, frame["name"])
            require(path in entries, f"adapter_frame_missing:{sequence_id}:{frame['frameIndex']}")
            found = jpeg_size(descriptors.read_verified(entries, source_root, path),
                              f"adapter_frame_invalid:{sequence_id}:{frame['frameIndex']}")
            require(size is None or found == size, f"adapter_frame_invalid:{sequence_id}:frame_size")
            size = found
        width, height = size
        instants, tracks = [], {}
        for frame in frames:
            index = frame["frameIndex"]
            offset = rational(descriptors.index_offset_ms(descriptor, index))
            instants.append({"frameIndex": index, "videoOffsetMs": offset})
            for item in frame["objects"]:
                x1, y1, x2, y2 = item["box"]
                # Inclusive pixel extent (width = x2 - x1 + 1), clipped to the image.
                left, top = max(x1, Fraction(0)), max(y1, Fraction(0))
                right, bottom = min(x2 + 1, Fraction(width)), min(y2 + 1, Fraction(height))
                require(right > left and bottom > top, f"{bad}:box_outside_image")
                track = tracks.setdefault(item["id"], {"gtTrackId": item["id"], "nativeClass": item["class"],
                                                       "frames": []})
                require(track["nativeClass"] == item["class"], f"{bad}:class_change")
                track["frames"].append({
                    "frameIndex": index, "videoOffsetMs": offset, "ignore": False,
                    "box": {"x": float(left / width), "y": float(top / height),
                            "width": float((right - left) / width), "height": float((bottom - top) / height)}})
        return {"sequenceId": sequence_id, "split": split, "frameSize": {"width": width, "height": height},
                "instants": instants, "tracks": [copy.deepcopy(tracks[key]) for key in sorted(tracks)]}
