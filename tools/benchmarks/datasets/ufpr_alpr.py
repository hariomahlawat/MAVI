"""The UFPR-ALPR adapter (Stage 4 PR-1: Track-level plate sequences for E-B, and stills for E-A).

UFPR-ALPR (Laroca et al., IJCNN 2018) holds 150 vehicles, each a sequence of 30 consecutive 1920×1080 PNG frames, with
one annotation text file per frame. It is the plan's Track-level sequence candidate (§3.3). Source layout under the
descriptor's source root (the release archive extracted, its top directory removed)::

    <split>/track<NNNN>/track<NNNN>[<FF>].png      frame FF (1-based, two digits)
    <split>/track<NNNN>/track<NNNN>[<FF>].txt      its annotation

Annotation facts (dataset page ``github.com/raysonlaroca/ufpr-alpr-dataset``; paper §III): ``key: value`` lines —
``camera``, ``position_vehicle`` (``x y w h`` pixels), ``type`` (``car`` or ``motorcycle``), ``make``, ``model``,
``year``, ``plate`` (the plate text), ``position_plate`` (``x y w h``) and ``char N`` boxes. Brazilian motorcycle
plates have two rows (3 letters over 4 characters); car plates have one. The dataset labels boxes, not corners, so the
plate polygon is axis-aligned and the oblique stratum is unavailable for this dataset.

The adapter is **fail-closed on format**: an unrecognised key, a missing required key, a malformed box, a box outside
the frame or a sequence with a gap refuses that annotation. In ``plate_truth`` a refused frame is listed in
``exclusions`` with its reason; ``ground_truth`` (vehicle tracks, for ``prepare``/association) refuses the sequence.
The documented format is confirmed on intake: the first reconciliation of the real release runs these refusals.

Splits (paper): training 40 %, validation 20 %, testing 40 %, by vehicle. **Measurement uses ``testing`` only**;
``training`` and ``validation`` stay unread by the adequacy experiments so any later fine-tuning event can use them
without leakage.

Mappings (ADR-017 §4): native ``car`` → plate layout ``one-line``, vehicle class ``car`` (exact); native
``motorcycle`` → layout ``two-line``, vehicle class ``motorcycle`` (exact; the two-row layout is the Brazilian
motorcycle plate format). Illumination and occlusion are not labelled: ``unknown``.
"""

from __future__ import annotations

import re
import struct
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from tools.benchmarks.capabilities.plates import truth as truths
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core.identity import S32Error, rational, require, sha256_hex

ADAPTER_ID = "ufpr-alpr"
ADAPTER_VERSION = "1"
DATASET_ID = "ufpr-alpr"
RELEASE = "UFPR-ALPR (IJCNN 2018 release; training/validation/testing)"
SPLITS = ("training", "validation", "testing")
MEASUREMENT_SPLIT = "testing"
FPS = (30, 1)
FRAMES_PER_SEQUENCE = 30
SEQUENCE = re.compile(r"track[0-9]{4}")
FRAME = re.compile(r"(track[0-9]{4})\[([0-9]{2})\]\.(png|txt)")
REQUIRED = ("camera", "position_vehicle", "type", "plate", "position_plate")
KNOWN = (*REQUIRED, "make", "model", "year")
CHAR = re.compile(r"char [0-9]{1,2}")
LAYOUT = {"car": "one-line", "motorcycle": "two-line"}
TERMS = "https://github.com/raysonlaroca/ufpr-alpr-dataset"


def descriptor(entries: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """The release descriptor; the committed template is this with an empty manifest (pre-acquisition)."""
    document = {
        "schemaVersion": descriptors.SCHEMA,
        "datasetId": DATASET_ID,
        "datasetName": "UFPR-ALPR",
        "release": RELEASE,
        "task": "plate-recognition",
        "source": {"kind": "official", "url": TERMS, "retrievedOn": "2026-10-12"},
        "access": {"mechanism": "agreement", "preconditions": [
            "The owner requests the dataset through the authors' licence agreement (academic research, "
            "non-commercial); acquisition is never automated.",
            "The release archive's SHA-256 is recorded on intake; the manifest is frozen from the extracted tree."]},
        "intendedUse": "development-benchmarking",
        "researchUse": {
            "status": "RESEARCH-ADMISSIBLE",
            "basis": "The authors release UFPR-ALPR for academic research only, free to researchers at educational "
                     "or research institutes for non-commercial purposes, under a licence agreement the owner signs. "
                     "Development benchmarking is research evaluation; nothing is redistributed.",
            "termsReference": TERMS,
            "redistribution": "not-permitted-by-default"},
        "splits": [{"name": "testing", "labelled": True, "role": "evaluation"},
                   {"name": "training", "labelled": True, "role": "reserved-unread"},
                   {"name": "validation", "labelled": True, "role": "reserved-unread"}],
        "nativeTaxonomy": [
            {"code": "car", "name": "Car", "definition": "UFPR-ALPR vehicle type 'car' (one-row Brazilian plate)."},
            {"code": "motorcycle", "name": "Motorcycle",
             "definition": "UFPR-ALPR vehicle type 'motorcycle' (two-row Brazilian plate)."}],
        "frameTime": {"kind": "index-at-fps", "fpsNumerator": FPS[0], "fpsDenominator": FPS[1]},
        "manifest": {"kind": "file-hashes", "entries": [dict(entry) for entry in entries]},
        "exposure": {"status": "possible",
                     "basis": "The phase-1 detector trains on COCO 2017 only. Public plate recognisers (the "
                              "measuring instruments) may have trained on UFPR-ALPR; each instrument's exposure is "
                              "recorded in its specification."},
    }
    return descriptors.check(document)


def png_size(data: bytes, code: str) -> tuple[int, int]:
    require(len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR", code)
    width, height = struct.unpack(">II", data[16:24])
    require(width > 0 and height > 0, code)
    return width, height


def _path(split: str, sequence: str, number: int, extension: str) -> str:
    require(split in SPLITS, f"adapter_split_unknown:{split}")
    return f"{split}/{sequence}/{sequence}[{number:02d}].{extension}"


def _box(value: str, code: str) -> tuple[int, int, int, int]:
    fields = value.split()
    require(len(fields) == 4 and all(re.fullmatch(r"[0-9]+", f) for f in fields), code)
    x, y, w, h = (int(f) for f in fields)
    require(w > 0 and h > 0, code)
    return x, y, w, h


def parse_annotation(data: bytes, code: str) -> dict[str, Any]:
    """One frame's annotation, fail-closed: known keys only, each once, required keys present."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise S32Error(f"{code}:encoding") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.strip().partition(":")
        require(separator == ":", f"{code}:line")
        key, value = key.strip(), value.strip()
        if CHAR.fullmatch(key):
            _box(value, f"{code}:char_box")
            continue
        require(key in KNOWN, f"{code}:unknown_key")
        require(key not in values, f"{code}:duplicate_key")
        values[key] = value
    for key in REQUIRED:
        require(key in values, f"{code}:missing:{key.replace('_', '-')}")
    require(values["type"] in LAYOUT, f"{code}:type")
    require(values["plate"] != "", f"{code}:plate")
    return {"type": values["type"], "plate": values["plate"],
            "vehicle": _box(values["position_vehicle"], f"{code}:vehicle_box"),
            "plateBox": _box(values["position_plate"], f"{code}:plate_box")}


class UfprAlprAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def native_classes(self) -> set[str]:
        return set(LAYOUT)

    def sequences_described(self, manifest_paths: Iterable[str], split: str) -> list[str]:
        found = set()
        for path in manifest_paths:
            parts = path.split("/")
            if len(parts) == 3 and parts[0] == split and SEQUENCE.fullmatch(parts[1]):
                found.add(parts[1])
        return sorted(found)

    def _numbers(self, entries: Iterable[str], split: str, sequence: str, extension: str) -> list[int]:
        prefix = f"{split}/{sequence}/"
        numbers = []
        for path in entries:
            if path.startswith(prefix):
                match = FRAME.fullmatch(path[len(prefix):])
                require(match is not None and match.group(1) == sequence, f"adapter_frame_invalid:{sequence}:name")
                if match.group(3) == extension:
                    numbers.append(int(match.group(2)))
        return sorted(numbers)

    def discover(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str) -> list[str]:
        """Complete: frames and annotations 1..30 with no gap."""
        expected = list(range(1, FRAMES_PER_SEQUENCE + 1))
        return [sequence for sequence in self.sequences_described(entries, split)
                if self._numbers(entries, split, sequence, "png") == expected
                and self._numbers(entries, split, sequence, "txt") == expected]

    def frame_paths(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str,
                    sequence: str) -> list[tuple[int, str]]:
        numbers = self._numbers(entries, split, sequence, "png")
        require(numbers == list(range(1, FRAMES_PER_SEQUENCE + 1)), f"derivation_frames_not_contiguous:{sequence}")
        return [(number - 1, _path(split, sequence, number, "png")) for number in numbers]

    def require_descriptor(self, document: dict[str, Any]) -> None:
        reference = descriptor()
        for field in ("datasetId", "release", "task", "frameTime"):
            require(document.get(field) == reference[field], f"adapter_descriptor_mismatch:{field}")

    def _frames(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str, sequence: str):
        """``(index, image path, image bytes, (width, height), annotation | refusal code)`` per frame."""
        for index, path in self.frame_paths(source_root, entries, split, sequence):
            image = descriptors.read_verified(entries, source_root, path)
            size = png_size(image, f"adapter_frame_invalid:{sequence}:{index}")
            annotation_path = path.removesuffix(".png") + ".txt"
            code = f"adapter_label_invalid:{sequence}:{index}"
            try:
                annotation = parse_annotation(descriptors.read_verified(entries, source_root, annotation_path), code)
                for x, y, w, h in (annotation["vehicle"], annotation["plateBox"]):
                    require(x + w <= size[0] and y + h <= size[1], f"{code}:box_outside_image")
            except S32Error as exc:
                annotation = str(exc)
            yield index, path, image, size, annotation_path, annotation

    def ground_truth(self, source_root: Path, entries: dict[str, dict[str, Any]], descriptor: dict[str, Any],
                     split: str, sequence_id: str) -> dict[str, Any]:
        """The ``vehicle_tracks`` ground truth of one sequence: one vehicle track over its 30 frames."""
        self.require_descriptor(descriptor)
        size, frames, native = None, [], None
        for index, _path_, _image, frame_size, _ann_path, annotation in self._frames(source_root, entries, split,
                                                                                    sequence_id):
            require(isinstance(annotation, dict), annotation if isinstance(annotation, str) else "adapter_label_invalid")
            require(size is None or frame_size == size, f"adapter_frame_invalid:{sequence_id}:frame_size")
            size = frame_size
            require(native is None or annotation["type"] == native, f"adapter_label_invalid:{sequence_id}:type_change")
            native = annotation["type"]
            x, y, w, h = annotation["vehicle"]
            width, height = size
            frames.append({"frameIndex": index,
                           "videoOffsetMs": rational(descriptors.index_offset_ms(descriptor, index)),
                           "ignore": False,
                           "box": {"x": float(Fraction(x, width)), "y": float(Fraction(y, height)),
                                   "width": float(Fraction(w, width)), "height": float(Fraction(h, height))}})
        width, height = size  # type: ignore[misc]
        instants = [{"frameIndex": frame["frameIndex"], "videoOffsetMs": frame["videoOffsetMs"]} for frame in frames]
        return {"sequenceId": sequence_id, "split": split, "frameSize": {"width": width, "height": height},
                "instants": instants, "tracks": [{"gtTrackId": "vehicle", "nativeClass": native, "frames": frames}]}

    def plate_items(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str,
                    sequence: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Plate truth items (one per labelled frame) and the refused annotations of one sequence."""
        items, exclusions = [], []
        for index, path, image, size, annotation_path, annotation in self._frames(source_root, entries, split,
                                                                                 sequence):
            if isinstance(annotation, str):
                exclusions.append({"path": annotation_path,
                                   "reason": _reason(annotation, f"adapter_label_invalid:{sequence}:{index}:")})
                continue
            x, y, w, h = annotation["plateBox"]
            vx, vy, vw, vh = annotation["vehicle"]
            items.append({
                "itemId": f"{sequence}/{index:06d}", "imagePath": path, "imageSha256": sha256_hex(image),
                "frameSize": {"width": size[0], "height": size[1]}, "sequenceId": sequence, "frameIndex": index,
                "gtTrackId": "vehicle", "vehicleBox": {"x": vx, "y": vy, "width": vw, "height": vh},
                "vehicleClass": annotation["type"],
                "plates": [truths.plate("plate", truths.box_polygon(x, y, w, h), annotation["plate"],
                                        LAYOUT[annotation["type"]])]})
        return items, exclusions


def _reason(code: str, prefix: str) -> str:
    """The closed exclusion reason of an annotation refusal (the refusal code after its sequence/frame prefix)."""
    tail = code[len(prefix):] if code.startswith(prefix) else "annotation-invalid"
    reason = re.sub(r"[^a-z0-9]+", "-", tail.lower()).strip("-")
    return reason or "annotation-invalid"
