"""BDD100K MOT 2020 val from a **derived** COCO-format annotation (H3-v1 only; adapter ``bdd100k-mot-coco``).

The raw ``box_track_20`` labels are unavailable from BDD100K's distribution infrastructure, so H3-v1 uses one pinned
derivative: ``bdd_box_track_val_cocofmt.json`` from the MASA authors' Hugging Face repository
(``dereksiyuanli/masa``), SHA-256 ``074ff795…5d5d``. It is the output of the official conversion
``python -m bdd100k.label.to_coco -m box_track`` with ``configs/box_track.toml``; its fields are exactly those of
Scalabel's ``to_coco`` box-track converter of April to early May 2021 (scalabel commits ``55cd90e``..``d0a018f``),
which, unlike the current converter, also writes ``ignore = 1`` for a former distractor. It is never the raw
release, and this adapter accepts no other file: a different SHA-256 is refused before anything is parsed.

Source layout (the images exactly as the BDD100K MOT 2020 val image package ships them):

    labels/box_track_20_cocofmt/bdd_box_track_val_cocofmt.json
    images/track/val/<videoName>/<frame name>.jpg

What the official conversion keeps, and how it is read (each field is checked; anything else is refused):

- ``videos[] {id, name}``, ``images[] {id, video_id, frame_id, file_name = <videoName>/<name>, width, height}``: the
  raw video name, frame index and frame file name, so frame paths and timing are those of the raw adapter.
- ``annotations[] {image_id, category_id, instance_id, scalabel_id, iscrowd, ignore, bbox, area}``: ``scalabel_id``
  is the raw label id, used as ``gtTrackId`` exactly as the raw adapter does; ``bbox = [x1, y1, x2 - x1 + 1,
  y2 - y1 + 1]`` (Scalabel ``box2d_to_bbox``) is inverted to the raw inclusive box and then clipped to the image by
  the same rule, so a non-crowd box yields the same ground truth as the raw path.
- ``category_id`` is one of the eight leaf classes after the official name mapping.

What it changes: the raw distractor classes ``trailer``, ``other vehicle`` and ``other person`` are recoded as
``truck``, ``car`` and ``pedestrian`` with ``iscrowd = 1`` and ``ignore = 1`` (genuine crowd boxes carry
``iscrowd = 1`` and ``ignore = 0``); any raw ``van``/``caravan``, ``motor``, ``person`` or ``bike`` alias would be
folded into ``car``, ``motorcycle``, ``pedestrian`` or ``bicycle`` without trace; occluded and truncated attributes
are dropped. This adapter emits distractors only as ignored frames under their recoded class, never as native
classes, so H3-v1 makes no claim about trailer, van, caravan or other vehicle from this source.

Ground-truth ignore follows ``ignore = 1`` only, never ``iscrowd`` alone: a former distractor
(``iscrowd = 1, ignore = 1``) is an ignored frame, never scored GT, which keeps distractors out of class precision and
recall; a genuine crowd box (``iscrowd = 1, ignore = 0``) stays ordinary GT of its class, exactly as the raw adapter
keeps crowd boxes (BDD100K's overlap-based crowd rule is not MAVI's ignore rule).

A label id whose class changes between frames (46 of the 18,842 val tracks) has no single class meaning: every
frame of it is emitted as ignored, with its first class recorded but never scored. A track left without enough
non-ignored frames is ``ignoredGt``, which enters no population.
"""

from __future__ import annotations

import copy
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core.identity import rational, require
from tools.benchmarks.datasets import bdd100k_mot as raw

ADAPTER_ID = "bdd100k-mot-coco"
ADAPTER_VERSION = "1"
DATASET_ID = "bdd100k-mot-2020-cocofmt"
RELEASE = "MOT 2020 val (box_track_20) via MASA COCO-format derivative sha256:074ff795"
ANNOTATION = "labels/box_track_20_cocofmt/bdd_box_track_val_cocofmt.json"
ANNOTATION_SHA256 = "074ff79555483296cf7ccadddeeceeec7a83452c900506dc46588ed3a3e65d5d"
ANNOTATION_COMMIT = "25ed372c47f2c46cf36fd446d1b657b656bc7ea9"
# Pinned to the recorded repository commit, so the URL keeps naming these bytes if the branch moves.
ANNOTATION_URL = f"https://huggingface.co/dereksiyuanli/masa/resolve/{ANNOTATION_COMMIT}/bdd_box_track_val_cocofmt.json"
SPLIT = "val"
# scalabel2coco_box_track: the leaf categories of configs/box_track.toml, numbered from 1 in config order.
CATEGORIES = ("pedestrian", "rider", "car", "truck", "bus", "train", "motorcycle", "bicycle")
FOLDED = "after the official box_track name mapping"
TAXONOMY = (
    ("bicycle", "Bicycle", f"BDD100K 'bicycle' {FOLDED} (raw 'bike' folded in)."),
    ("bus", "Bus", f"BDD100K 'bus' {FOLDED}."),
    ("car", "Car", f"BDD100K 'car' {FOLDED} (which maps 'van' and 'caravan' to 'car' if such aliases are present; "
                   f"'other vehicle' only as an ignored distractor)."),
    ("motorcycle", "Motorcycle", f"BDD100K 'motorcycle' {FOLDED} (raw 'motor' folded in)."),
    ("pedestrian", "Pedestrian", f"BDD100K 'pedestrian' {FOLDED} (raw 'person' folded in; 'other person' only as "
                                 f"an ignored distractor)."),
    ("rider", "Rider", f"BDD100K 'rider' {FOLDED}."),
    ("train", "Train", f"BDD100K 'train' {FOLDED}."),
    ("truck", "Truck", f"BDD100K 'truck' {FOLDED} ('trailer' only as an ignored distractor)."),
)
MAPPINGS = (
    ("bicycle", None, "unsupported", "outside-capability", "Not one of the four MAVI motor-vehicle classes."),
    ("bus", "bus", "exact", None, "Same practical meaning: passenger buses and coaches."),
    ("car", "car", "exact", None,
     "Same practical meaning: passenger cars. The generic BDD box_track conversion maps 'van' and 'caravan' to "
     "'car' if such aliases are present; the published MOT 2020 taxonomy does not list them as native MOT classes. "
     "Caveat: BDD100K does not define every body-style boundary (the MAVI guide puts windowless cargo vans in "
     "truck)."),
    ("motorcycle", "motorcycle", "exact", None, "Same practical meaning: motorised two-wheelers ridden seated."),
    ("pedestrian", None, "unsupported", "outside-capability", "A person, not a Vehicle."),
    ("rider", None, "unsupported", "outside-capability", "The person on a two-wheeler, not the vehicle."),
    ("train", None, "unsupported", "outside-capability", "Rail vehicle, outside the four MAVI road-vehicle classes."),
    ("truck", "truck", "exact", None,
     "Same practical meaning: goods and work vehicles. Former 'trailer' distractors (ignore = 1) are ignored "
     "frames, never scored truck GT."),
)
# configs/box_track.toml [ignored_mapping]: other person -> pedestrian, other vehicle -> car, trailer -> truck.
IGNORED_MAPPING = {"other person": "pedestrian", "other vehicle": "car", "trailer": "truck"}
DISTRACTOR_TARGETS = frozenset(IGNORED_MAPPING.values())
_TOP = {"categories", "videos", "images", "annotations"}
_VIDEO = {"id", "name"}
_IMAGE = {"id", "video_id", "frame_id", "file_name", "width", "height"}
_ANNOTATION = {"id", "image_id", "category_id", "instance_id", "scalabel_id", "iscrowd", "ignore", "bbox", "area"}


def descriptor(entries: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """The derived-source release descriptor (the template is this with an empty manifest)."""
    document = {
        "schemaVersion": descriptors.SCHEMA,
        "datasetId": DATASET_ID,
        "datasetName": "BDD100K box tracking (derived COCO-format annotation)",
        "release": RELEASE,
        "task": "box-tracking",
        "source": {
            "kind": "research-mirror", "url": ANNOTATION_URL, "retrievedOn": "2026-10-05",
            "credibilityBasis": f"Annotation: the MASA authors' Hugging Face repository at commit {ANNOTATION_COMMIT}, "
                                f"pinned by SHA-256 {ANNOTATION_SHA256} (the Hub's LFS object id); produced by the "
                                "official bdd100k.label.to_coco box_track conversion. Its lineage against raw official "
                                "labels is a required check (lineage()) whose result is recorded with the H3 run, "
                                "not asserted here. Images: the BDD100K MOT 2020 val image archive the owner obtained from "
                                "the Berkeley BDD100K MOT mirror (archive SHA-256 recorded with the run)."},
        "access": {"mechanism": "registration", "preconditions": [
            "The images are the BDD100K MOT 2020 val archive obtained by the owner from the Berkeley BDD100K MOT "
            "mirror under the BDD100K license; acquisition is never automated.",
            "The derived annotation is public; it is accepted only with the pinned SHA-256."]},
        "intendedUse": "development-benchmarking",
        "researchUse": {
            "status": "RESEARCH-ADMISSIBLE",
            "basis": "The annotation is a converted representation of BDD100K labels hosted by the MASA authors. "
                     "Development use of the underlying labels is governed by the BDD100K data and label license, "
                     "which permits use 'for educational, research, and not-for-profit purposes, without fee'. "
                     "MASA is the retrieval and conversion source; its repository licence is not treated as "
                     "relicensing the BDD100K annotation data.",
            "termsReference": f"{raw.SOURCE_DOCS}/license.rst",
            "redistribution": "not-permitted-by-default"},
        "splits": [{"name": SPLIT, "labelled": True, "role": "evaluation"}],
        "nativeTaxonomy": [{"code": code, "name": name, "definition": definition}
                           for code, name, definition in TAXONOMY],
        "frameTime": {"kind": "index-at-fps", "fpsNumerator": raw.FPS[0], "fpsDenominator": raw.FPS[1]},
        "manifest": {"kind": "file-hashes", "entries": [dict(entry) for entry in entries]},
        "exposure": {"status": "none-known",
                     "basis": "The qualified detector (RTMDet-m COCO, resolved config sha256 377d9f57…) trains on COCO "
                              "2017 only, loads no other checkpoint and declares no pretrained backbone; no MAVI "
                              "record names BDD100K use."},
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


def _int(value: Any) -> bool:
    return type(value) is int


def parse(data: bytes) -> dict[str, dict[str, Any]]:
    """The derived annotation, checked field by field, as ``{videoName: {"size": (w, h), "frames": [...]}}`` with
    frames sorted by ``frame_id``, each ``{frameIndex, name, objects[{id, class, box (x1, y1, x2, y2), ignore}]}``."""
    from tools.benchmarks.core._stage3 import artefacts

    bad = "adapter_label_invalid:annotation"
    document = artefacts.parse_json(data, bad)
    require(isinstance(document, dict) and set(document) == _TOP, f"{bad}:fields")
    categories = document["categories"]
    require(isinstance(categories, list) and all(isinstance(c, dict) for c in categories)
            and [(c.get("id"), c.get("name")) for c in categories] == list(enumerate(CATEGORIES, start=1)),
            f"{bad}:categories")
    videos: dict[int, str] = {}
    for video in document["videos"] if isinstance(document["videos"], list) else [None]:
        require(isinstance(video, dict) and _VIDEO <= set(video) <= _VIDEO | {"attributes"} and _int(video["id"])
                and isinstance(video["name"], str) and raw.GT_TRACK_ID.fullmatch(video["name"]) is not None,
                f"{bad}:video")
        require(video["id"] not in videos and video["name"] not in videos.values(), f"{bad}:duplicate_video")
        videos[video["id"]] = video["name"]
    images: dict[int, tuple[str, dict[str, Any]]] = {}
    result: dict[str, dict[str, Any]] = {name: {"size": None, "frames": {}} for name in videos.values()}
    for image in document["images"] if isinstance(document["images"], list) else [None]:
        require(isinstance(image, dict) and _IMAGE <= set(image) <= _IMAGE | {"attributes"}
                and all(_int(image[key]) for key in ("id", "video_id", "frame_id", "width", "height")),
                f"{bad}:image")
        name = videos.get(image["video_id"])
        require(name is not None and image["id"] not in images, f"{bad}:image_video")
        sequence = result[name]
        file_name = image["file_name"]
        require(isinstance(file_name, str) and file_name.startswith(f"{name}/")
                and raw.FRAME_NAME.fullmatch(file_name[len(name) + 1:]) is not None, f"adapter_label_invalid:{name}:file_name")
        require(image["frame_id"] >= 0 and image["frame_id"] not in sequence["frames"],
                f"adapter_label_invalid:{name}:duplicate_frame_index")
        size = (image["width"], image["height"])
        require(sequence["size"] in (None, size) and size[0] > 0 and size[1] > 0, f"adapter_label_invalid:{name}:frame_size")
        sequence["size"] = size
        frame = {"frameIndex": image["frame_id"], "name": file_name[len(name) + 1:], "objects": [], "ids": set()}
        sequence["frames"][image["frame_id"]] = frame
        images[image["id"]] = (name, frame)
    identities: dict[tuple[str, int], str] = {}
    annotation_ids: set[int] = set()
    for item in document["annotations"] if isinstance(document["annotations"], list) else [None]:
        require(isinstance(item, dict) and _ANNOTATION <= set(item) <= _ANNOTATION | {"score"}
                and all(_int(item[key]) for key in ("id", "image_id", "category_id", "instance_id")),
                f"{bad}:annotation")
        require(item["id"] not in annotation_ids and item["image_id"] in images, f"{bad}:annotation_image")
        annotation_ids.add(item["id"])
        name, frame = images[item["image_id"]]
        where = f"adapter_label_invalid:{name}"
        track_id = item["scalabel_id"]
        require(isinstance(track_id, str) and raw.GT_TRACK_ID.fullmatch(track_id) is not None, f"{where}:object_id")
        # instance_id is the converter's per-video number for one scalabel_id: the two must agree both ways.
        known = identities.setdefault((name, item["instance_id"]), track_id)
        require(known == track_id, f"{where}:instance_id")
        require(track_id not in frame["ids"], f"{where}:duplicate_track_id")
        frame["ids"].add(track_id)
        require(1 <= item["category_id"] <= len(CATEGORIES), f"{where}:category")
        # The converter that produced this file (Scalabel to_coco, April-May 2021) writes iscrowd = crowd or
        # ignored and ignore = 1 for a former distractor, which the ignored mapping recodes only as pedestrian,
        # car or truck. Any other combination is not that converter's output.
        crowd = (item["iscrowd"], item["ignore"])
        require(_int(item["iscrowd"]) and _int(item["ignore"]) and crowd in ((0, 0), (1, 0), (1, 1)),
                f"{where}:crowd")
        require(item["ignore"] == 0 or CATEGORIES[item["category_id"] - 1] in DISTRACTOR_TARGETS,
                f"{where}:ignore_category")
        box = item["bbox"]
        require(isinstance(box, list) and len(box) == 4, f"{where}:box")
        x, y, width, height = (raw._coordinate(value, f"{where}:box") for value in box)
        require(width >= 1 and height >= 1, f"{where}:box")  # x2 >= x1 under width = x2 - x1 + 1
        frame["objects"].append({"id": track_id, "class": CATEGORIES[item["category_id"] - 1],
                                 "box": (x, y, x + width - 1, y + height - 1),
                                 # Ground-truth ignore is the former-distractor flag only; genuine crowd
                                 # (iscrowd = 1, ignore = 0) stays ordinary GT, as in the raw adapter.
                                 "ignore": item["ignore"] == 1})
    numbers: dict[tuple[str, str], int] = {}
    for (name, number), track_id in identities.items():
        require(numbers.setdefault((name, track_id), number) == number, f"adapter_label_invalid:{name}:instance_id")
    for name, sequence in result.items():
        require(sequence["frames"], f"adapter_label_invalid:{name}:frames")
        sequence["frames"] = [{key: value for key, value in frame.items() if key != "ids"}
                              for _, frame in sorted(sequence["frames"].items())]
    return result


class Bdd100kMotCocoAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self) -> None:
        self._parsed: dict[str, dict[str, Any]] | None = None

    def native_classes(self) -> set[str]:
        return {code for code, _, _ in TAXONOMY}

    def sequences_described(self, manifest_paths: Iterable[str], split: str) -> list[str]:
        found = set()
        for path in manifest_paths:
            parts = path.split("/")
            if parts[:3] == [*raw.IMAGES.split("/"), split] and len(parts) == 5:
                found.add(parts[3])
        return sorted(found)

    def _annotation(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str) -> dict[str, Any]:
        """The pinned derivative, parsed once per adapter instance (it is one file for the whole split)."""
        require(split == SPLIT, f"adapter_split_unsupported:{split}")
        entry = entries.get(ANNOTATION)
        require(entry is not None, f"source_manifest_incomplete:{ANNOTATION}")
        # Provenance first: only the one verified derivative is ever parsed.
        require(entry["sha256"] == ANNOTATION_SHA256, "adapter_source_unverified:annotation_sha256")
        if self._parsed is None:
            self._parsed = parse(descriptors.read_verified(entries, source_root, ANNOTATION))
        return self._parsed

    def discover(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str) -> list[str]:
        """Every annotated video must have all its frame images; a video with images and no annotation is left
        undiscovered, so discovery and the manifest disagree and ``prepare`` refuses."""
        complete = []
        for name, sequence in sorted(self._annotation(source_root, entries, split).items()):
            missing = [frame for frame in sequence["frames"]
                       if raw.frame_path(split, name, frame["name"]) not in entries]
            require(not missing, f"source_manifest_incomplete:sequence:{name}")
            complete.append(name)
        return complete

    def frame_paths(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str,
                    sequence: str) -> list[tuple[int, str]]:
        frames = self._sequence(source_root, entries, split, sequence)["frames"]
        return [(frame["frameIndex"], raw.frame_path(split, sequence, frame["name"])) for frame in frames]

    def _sequence(self, source_root, entries, split, sequence) -> dict[str, Any]:
        found = self._annotation(source_root, entries, split).get(sequence)
        require(found is not None, f"adapter_label_invalid:{sequence}:not_annotated")
        return found

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
        sequence = self._sequence(source_root, entries, split, sequence_id)
        for frame in sequence["frames"]:
            path = raw.frame_path(split, sequence_id, frame["name"])
            require(path in entries, f"adapter_frame_missing:{sequence_id}:{frame['frameIndex']}")
            found = raw.jpeg_size(descriptors.read_verified(entries, source_root, path),
                                  f"adapter_frame_invalid:{sequence_id}:{frame['frameIndex']}")
            # The annotation's declared size must be the frames' real size: the boxes are in that pixel frame.
            require(found == sequence["size"], f"adapter_frame_invalid:{sequence_id}:frame_size")
        width, height = sequence["size"]
        instants, tracks = [], {}
        for frame in sequence["frames"]:
            index = frame["frameIndex"]
            offset = rational(descriptors.index_offset_ms(descriptor, index))
            instants.append({"frameIndex": index, "videoOffsetMs": offset})
            for item in frame["objects"]:
                x1, y1, x2, y2 = item["box"]
                left, top = max(x1, Fraction(0)), max(y1, Fraction(0))
                right, bottom = min(x2 + 1, Fraction(width)), min(y2 + 1, Fraction(height))
                require(right > left and bottom > top, f"{bad}:box_outside_image")
                track = tracks.setdefault(item["id"], {"gtTrackId": item["id"], "nativeClass": item["class"],
                                                       "frames": []})
                track.setdefault("classes", set()).add(item["class"])
                track["frames"].append({
                    "frameIndex": index, "videoOffsetMs": offset, "ignore": item["ignore"],
                    "box": {"x": float(left / width), "y": float(top / height),
                            "width": float((right - left) / width), "height": float((bottom - top) / height)}})
        for track in tracks.values():
            # A label id whose class changes between frames has no single class meaning (in the real val labels:
            # 46 of 18,842 tracks, mostly id reuse such as car -> pedestrian). It is kept as ignore evidence on
            # every frame, so it is ignoredGt and enters no population; its first class is recorded, not scored.
            if len(track.pop("classes")) > 1:
                for frame in track["frames"]:
                    frame["ignore"] = True
        return {"sequenceId": sequence_id, "split": split, "frameSize": {"width": width, "height": height},
                "instants": instants, "tracks": [copy.deepcopy(tracks[key]) for key in sorted(tracks)]}


def lineage(document: dict[str, Any], raw_frames: list[dict[str, Any]], raw_id=lambda value: value) -> dict[str, Any]:
    """Compares the derived records of one video with that video's raw Scalabel frames under the official
    conversion semantics; returns counts and every mismatch (empty when the lineage is consistent). ``raw_id`` maps
    a raw label id to the expected ``scalabel_id``: the identity unless a declared, uniform id transformation
    between the two sources is being tested (and reported)."""
    name = raw_frames[0]["videoName"]
    video = next((v for v in document["videos"] if v["name"] == name), None)
    require(video is not None, f"lineage_video_missing:{name}")
    images = {i["id"]: i for i in document["images"] if i["video_id"] == video["id"]}
    by_frame: dict[int, dict[str, Any]] = {}
    for item in document["annotations"]:
        if item["image_id"] in images:
            by_frame.setdefault(images[item["image_id"]]["frame_id"], {})[item["scalabel_id"]] = item
    file_names = {i["frame_id"]: i["file_name"] for i in images.values()}
    mismatches, compared = [], 0
    # Exact frame-index sets on both sides: a derived image record with no annotations still counts.
    raw_indices = {frame["frameIndex"] for frame in raw_frames}
    derived_indices = {image["frame_id"] for image in images.values()}
    for index in sorted(raw_indices - derived_indices):
        mismatches.append(("frame_missing_in_derived", index, None))
    for index in sorted(derived_indices - raw_indices):
        mismatches.append(("frame_missing_in_raw", index, None))
    ignored_mapping = IGNORED_MAPPING
    aliases = {"bike": "bicycle", "caravan": "car", "motor": "motorcycle", "person": "pedestrian", "van": "car"}
    for frame in raw_frames:
        index = frame["frameIndex"]
        if index not in derived_indices:
            continue  # already a frame_missing_in_derived mismatch
        if file_names[index] != f"{name}/{frame['name']}":
            mismatches.append(("file_name", index, None))
        expected = {}
        for label in frame.get("labels") or []:
            if label.get("box2d") is None:
                continue
            category = aliases.get(label["category"], label["category"])
            attributes = dict(label.get("attributes") or {})
            if category in ignored_mapping:
                category, attributes["ignored"] = ignored_mapping[category], True
            if category not in CATEGORIES:
                continue
            box = label["box2d"]
            expected[raw_id(label["id"])] = (
                CATEGORIES.index(category) + 1,
                [box["x1"], box["y1"], box["x2"] - box["x1"] + 1, box["y2"] - box["y1"] + 1],
                int(bool(attributes.get("crowd")) or bool(attributes.get("ignored"))),
                int(bool(attributes.get("ignored"))))
        found = by_frame.get(index, {})
        if set(expected) != set(found):
            mismatches.append(("track_ids", index, sorted(set(expected) ^ set(found))[:5]))
        for track_id in sorted(set(expected) & set(found)):
            compared += 1
            item = found[track_id]
            category, box, crowd, ignored = expected[track_id]
            if item["category_id"] != category:
                mismatches.append(("category", index, track_id))
            if any(abs(a - b) > 1e-6 for a, b in zip(item["bbox"], box)):
                mismatches.append(("bbox", index, track_id))
            if item["iscrowd"] != crowd:
                mismatches.append(("crowd", index, track_id))
            if item["ignore"] != ignored:
                mismatches.append(("ignore", index, track_id))
    return {"video": name, "rawFrames": len(raw_indices), "derivedFrames": len(derived_indices),
            "comparedBoxes": compared, "mismatches": mismatches}
