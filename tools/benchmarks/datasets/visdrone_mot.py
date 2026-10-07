"""The VisDrone2019-MOT adapter (Stage-3 H4 domain-diversity benchmark; aerial drone footage).

Reads the official release archives' layout, always through the reconciled, hash-verified manifest:

    VisDrone2019-MOT-<split>/annotations/<sequence>.txt        one MOT text file per sequence
    VisDrone2019-MOT-<split>/sequences/<sequence>/NNNNNNN.jpg  frame N (1-based, seven digits)

Facts used, with their sources (read 2026-10-06):

- Annotation rows are ``frame_index, target_id, bbox_left, bbox_top, bbox_width, bbox_height, score,
  object_category, truncation, occlusion``; in ground truth ``score`` 1 means "considered in evaluation" and 0
  "ignored"; categories are "ignored regions(0), pedestrian(1), people(2), bicycle(3), car(4), van(5), truck(6),
  tricycle(7), awning-tricycle(8), bus(9), motor(10), others(11)" (VisDrone2018-MOT toolkit README,
  ``github.com/VisDrone/VisDrone2018-MOT-toolkit``). Boxes are top-left plus width and height in pixels.
- Ignored-region rows (category 0) carry target ids that collide with object ids in the same sequence (observed on
  the val release), so they are never tracks: each becomes an ``ignoreRegions`` box at its frame.
- An object row with ``score`` 0 is an ignored frame of its track (the toolkit's evaluation ignores it).
- Category ``others`` (11) is "an object of no listed category", not necessarily a vehicle, and the VisDrone
  toolkits do not evaluate it: its tracks are ignored on every frame (native class preserved, never in a
  population; their boxes are ignore evidence), never counted as expected vehicles.
- A ``target_id`` whose category changes between frames has no single native class: it is ignored on every frame
  (its first category, in frame order, is recorded and never scored), as the H3 derived adapter treats class changes.
- Frame numbers run 1..N with one JPEG per frame; derived frame ``k`` is file ``k + 1``. Every frame of a sequence
  is labelled, including frames with no boxes.
- The release states no frame rate (toolkit README, the VisDrone and VisDrone-MOT2019 papers). The H4 methodology
  declares ``index-at-fps`` 30/1 as an explicit assumption; both paired producers see identical timing.
- Frame size comes from each frame's own JPEG header (all frames of a sequence must agree).

Native classes are preserved in the ground truth; the mapping states how ``mavi-vehicle-subclass-v1`` scores them.
Truncation and occlusion do not change ground truth.
"""

from __future__ import annotations

import copy
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core.identity import rational, require
from tools.benchmarks.datasets.bdd100k_mot import jpeg_size

ADAPTER_ID = "visdrone2019-mot"
ADAPTER_VERSION = "2"
DATASET_ID = "visdrone2019-mot"
RELEASE = "VisDrone2019-MOT (val, test-dev; toolkit v1.0.2 category scheme)"
SPLITS = ("val", "test-dev")
FPS = (30, 1)
SEQUENCE = re.compile(r"uav[0-9]{7}_[0-9]{5}_v")
FRAME_FILE = re.compile(r"([0-9]{7})\.jpg")
TOOLKIT = "https://github.com/VisDrone/VisDrone2018-MOT-toolkit"
IGNORED_REGION = 0
OTHERS = 11  # ignored on every frame (see the module docstring)
# category number, native code, name, definition
TAXONOMY = (
    (1, "pedestrian", "Pedestrian", "VisDrone category 'pedestrian' (1): a person standing or walking."),
    (2, "people", "People", "VisDrone category 'people' (2): a person in another pose (sitting, lying, riding)."),
    (3, "bicycle", "Bicycle", "VisDrone category 'bicycle' (3)."),
    (4, "car", "Car", "VisDrone category 'car' (4). No written definition in the toolkit README; meaning from the "
                      "name in an aerial road-scene dataset."),
    (5, "van", "Van", "VisDrone category 'van' (5), annotated separately from car and truck."),
    (6, "truck", "Truck", "VisDrone category 'truck' (6). No written definition in the toolkit README."),
    (7, "tricycle", "Tricycle", "VisDrone category 'tricycle' (7): a three-wheeled vehicle."),
    (8, "awning-tricycle", "Awning tricycle", "VisDrone category 'awning-tricycle' (8): a three-wheeled vehicle "
                                              "with an awning."),
    (9, "bus", "Bus", "VisDrone category 'bus' (9). No written definition in the toolkit README."),
    (10, "motor", "Motor", "VisDrone category 'motor' (10): a motorised two-wheeler (the rider is annotated as "
                           "people)."),
    (11, "others", "Others", "VisDrone category 'others' (11): an object of no listed category; not evaluated by "
                             "the VisDrone toolkits and ignored on every frame by this adapter."),
)
CATEGORIES = {number: code for number, code, _, _ in TAXONOMY}
MAPPINGS = (
    ("awning-tricycle", None, "unsupported", "vehicle-unresolved",
     "A three-wheeled vehicle; mavi-vehicle-subclass-v1 has no tricycle class and none of its four classes fits."),
    ("bicycle", None, "unsupported", "outside-capability",
     "Not one of the four MAVI motor-vehicle classes (harness plan section 12)."),
    ("bus", "bus", "exact", None,
     "Same practical meaning: buses and coaches. Caveat: the release gives no written definition."),
    ("car", "car", "exact", None,
     "Same practical meaning: passenger cars; vans are a separate native class. Caveat: the release gives no "
     "written definition (SUV and pickup placement unstated)."),
    ("motor", "motorcycle", "exact", None,
     "Same practical meaning: motorised two-wheelers. Caveat: scooter and moped placement is not stated in the "
     "toolkit README."),
    ("others", None, "unsupported", "vehicle-unresolved",
     "An object of no listed category, not evaluated by the VisDrone toolkits: the adapter ignores it on every "
     "frame, so it never enters a population (the mapping row only completes the taxonomy)."),
    ("pedestrian", None, "unsupported", "outside-capability", "A person, not a Vehicle."),
    ("people", None, "unsupported", "outside-capability", "A person, not a Vehicle."),
    ("tricycle", None, "unsupported", "vehicle-unresolved",
     "A three-wheeled vehicle; mavi-vehicle-subclass-v1 has no tricycle class and none of its four classes fits."),
    ("truck", "truck", "exact", None,
     "Same practical meaning: goods vehicles. Caveat: pickup placement is not stated in the toolkit README."),
    ("van", None, "unsupported", "vehicle-unresolved",
     "v1 splits vans by body into car or truck and the native label does not (taxonomy review)."),
)


def descriptor(entries: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """The release descriptor; the committed template is this with an empty manifest (pre-acquisition)."""
    document = {
        "schemaVersion": descriptors.SCHEMA,
        "datasetId": DATASET_ID,
        "datasetName": "VisDrone2019 multi-object tracking",
        "release": RELEASE,
        "task": "box-tracking",
        "source": {"kind": "author-repository", "url": "https://github.com/VisDrone/VisDrone-Dataset",
                   "retrievedOn": "2026-10-06",
                   "credibilityBasis": "The dataset authors' repository (AISKYEYE team, Tianjin University) links the "
                                       "release archives on the authors' Google Drive; archive bytes are pinned by "
                                       "SHA-256 in the H4 methodology freeze."},
        "access": {"mechanism": "direct", "preconditions": []},
        "intendedUse": "development-benchmarking",
        "researchUse": {
            "status": "RESEARCH-UNCERTAIN",
            "basis": "Openly obtainable without registration; the dataset repository states no licence, and the MOT "
                     "toolkit says it is 'for research purpose only' and asks for citation. Used for Development "
                     "benchmarking only; not redistributed.",
            "termsReference": f"https://github.com/VisDrone/VisDrone-Dataset; {TOOLKIT}",
            "redistribution": "not-permitted-by-default"},
        "splits": [{"name": "test-dev", "labelled": True, "role": "evaluation"},
                   {"name": "val", "labelled": True, "role": "evaluation"}],
        "nativeTaxonomy": [{"code": code, "name": name, "definition": definition}
                           for _, code, name, definition in TAXONOMY],
        "frameTime": {"kind": "index-at-fps", "fpsNumerator": FPS[0], "fpsDenominator": FPS[1]},
        "manifest": {"kind": "file-hashes", "entries": [dict(entry) for entry in entries]},
        "exposure": {"status": "none-known",
                     "basis": "The detector checkpoint is trained on COCO 2017 only (resolved config 377d9f57); no "
                              "MAVI record names VisDrone; VisDrone images are not COCO images."},
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


def root(split: str) -> str:
    require(split in SPLITS, f"adapter_split_unknown:{split}")
    return f"VisDrone2019-MOT-{split}"


def annotation_path(split: str, sequence: str) -> str:
    return f"{root(split)}/annotations/{sequence}.txt"


def frame_path(split: str, sequence: str, number: int) -> str:
    return f"{root(split)}/sequences/{sequence}/{number:07d}.jpg"


class VisDroneMotAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def native_classes(self) -> set[str]:
        return {code for _, code, _, _ in TAXONOMY}

    def sequences_described(self, manifest_paths: Iterable[str], split: str) -> list[str]:
        base = root(split)
        found = set()
        for path in manifest_paths:
            parts = path.split("/")
            if len(parts) == 3 and parts[0] == base and parts[1] == "annotations" and parts[2].endswith(".txt"):
                found.add(parts[2].removesuffix(".txt"))
            elif len(parts) == 4 and parts[0] == base and parts[1] == "sequences":
                found.add(parts[2])
        return sorted(found)

    def _numbers(self, entries: Iterable[str], split: str, sequence: str) -> list[int]:
        prefix = f"{root(split)}/sequences/{sequence}/"
        numbers = []
        for path in entries:
            if path.startswith(prefix):
                match = FRAME_FILE.fullmatch(path[len(prefix):])
                require(match is not None, f"adapter_frame_invalid:{sequence}:name")
                numbers.append(int(match.group(1)))
        return sorted(numbers)

    def discover(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str) -> list[str]:
        """Complete: an annotation file and frames 1..N with no gap."""
        complete = []
        for sequence in self.sequences_described(entries, split):
            numbers = self._numbers(entries, split, sequence)
            if annotation_path(split, sequence) in entries and numbers and numbers == list(range(1, len(numbers) + 1)):
                complete.append(sequence)
        return complete

    def frame_paths(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str,
                    sequence: str) -> list[tuple[int, str]]:
        numbers = self._numbers(entries, split, sequence)
        require(numbers == list(range(1, len(numbers) + 1)), f"derivation_frames_not_contiguous:{sequence}")
        return [(number - 1, frame_path(split, sequence, number)) for number in numbers]

    def _rows(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str,
              sequence: str, frame_count: int) -> list[tuple[int, ...]]:
        bad = f"adapter_label_invalid:{sequence}"
        require(SEQUENCE.fullmatch(sequence) is not None, f"{bad}:sequence_id")
        data = descriptors.read_verified(entries, source_root, annotation_path(split, sequence))
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError as exc:
            raise descriptors.S32Error(f"{bad}:encoding") from exc
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            fields = line.strip().split(",")
            require(len(fields) == 10 and all(re.fullmatch(r"-?[0-9]+", f) for f in fields), f"{bad}:row")
            row = tuple(int(f) for f in fields)
            frame, target, _x, _y, width, height, score, category, _t, _o = row
            require(1 <= frame <= frame_count, f"{bad}:frame_index")
            require(target >= 0 and width > 0 and height > 0, f"{bad}:box")
            require(score in (0, 1), f"{bad}:score")
            require(category == IGNORED_REGION or category in CATEGORIES, f"{bad}:category")
            rows.append(row)
        return rows

    def require_descriptor(self, document: dict[str, Any]) -> None:
        reference = descriptor()
        for field in ("datasetId", "release", "task", "frameTime"):
            require(document.get(field) == reference[field], f"adapter_descriptor_mismatch:{field}")
        codes = [entry.get("code") for entry in document.get("nativeTaxonomy", [])]
        require(len(codes) == len(set(codes)) and sorted(codes) == sorted(descriptors.native_classes(reference)),
                "adapter_descriptor_mismatch:nativeTaxonomy")

    def ground_truth(self, source_root: Path, entries: dict[str, dict[str, Any]], descriptor: dict[str, Any],
                     split: str, sequence_id: str) -> dict[str, Any]:
        self.require_descriptor(descriptor)
        bad = f"adapter_label_invalid:{sequence_id}"
        frames = self.frame_paths(source_root, entries, split, sequence_id)
        size = None
        for index, path in frames:
            found = jpeg_size(descriptors.read_verified(entries, source_root, path),
                              f"adapter_frame_invalid:{sequence_id}:{index}")
            require(size is None or found == size, f"adapter_frame_invalid:{sequence_id}:frame_size")
            size = found
        width, height = size
        rows = self._rows(source_root, entries, split, sequence_id, len(frames))

        def box(x: int, y: int, w: int, h: int) -> dict[str, float] | None:
            left, top = max(Fraction(x), Fraction(0)), max(Fraction(y), Fraction(0))
            right, bottom = min(Fraction(x + w), Fraction(width)), min(Fraction(y + h), Fraction(height))
            if right <= left or bottom <= top:
                return None
            return {"x": float(left / width), "y": float(top / height),
                    "width": float((right - left) / width), "height": float((bottom - top) / height)}

        offsets = {index: rational(descriptors.index_offset_ms(descriptor, index)) for index, _ in frames}
        instants = [{"frameIndex": index, "videoOffsetMs": offsets[index]} for index, _ in frames]
        regions, tracks, classes = [], {}, {}
        for frame, target, x, y, w, h, score, category, _t, _o in sorted(rows, key=lambda r: (r[0], r[1], r[7])):
            index = frame - 1
            clipped = box(x, y, w, h)
            if category == IGNORED_REGION:
                if clipped is not None:
                    regions.append({"frameIndex": index, "box": clipped})
                continue
            require(clipped is not None, f"{bad}:box_outside_image")
            key = str(target)
            classes.setdefault(key, set()).add(CATEGORIES[category])
            track = tracks.setdefault(key, {"gtTrackId": key, "nativeClass": CATEGORIES[category], "frames": []})
            require(all(f["frameIndex"] != index for f in track["frames"][-1:]), f"{bad}:duplicate_track_frame")
            track["frames"].append({"frameIndex": index, "videoOffsetMs": offsets[index],
                                    "ignore": score == 0 or category == OTHERS, "box": clipped})
        for key, track in tracks.items():
            if len(classes[key]) > 1:  # a class change: no single native class, never scored
                for frame in track["frames"]:
                    frame["ignore"] = True
            seen = [f["frameIndex"] for f in track["frames"]]
            require(len(seen) == len(set(seen)), f"{bad}:duplicate_track_frame")
        document = {"sequenceId": sequence_id, "split": split, "frameSize": {"width": width, "height": height},
                    "instants": instants, "tracks": [copy.deepcopy(tracks[key]) for key in sorted(tracks)]}
        if regions:
            document["ignoreRegions"] = sorted(regions, key=lambda r: (r["frameIndex"], r["box"]["x"], r["box"]["y"],
                                                                       r["box"]["width"], r["box"]["height"]))
        return document
