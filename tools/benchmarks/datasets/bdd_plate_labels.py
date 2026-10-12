"""Verified plate labels on BDD100K MOT ground-truth vehicle Tracks → sequence plate truth (protocol R8; E-B).

BDD100K MOT (the Stage-3 H3 release, frozen descriptor ``bdd100k-mot-2020-cocofmt``) supplies the independent
ground-truth vehicle Tracks and per-frame vehicle boxes; ``tools/benchmarks/plates/annotate.py`` supplies the verified
``benchmark-plate-labels-v1`` (plate text per track where legible; plate box per frame where its geometry was
accepted). This adapter joins them into ``benchmark-plate-truth-v1`` items, one per (frame, track) with an accepted
plate box. Image bytes are the release's own frames, re-verified through the frozen manifest.

Mappings: BDD ``car`` → vehicle ``car``; ``truck`` and ``bus`` → ``commercial``; ``motorcycle`` → ``motorcycle``.
Layout, illumination and occlusion are not labelled (``unknown``). A track whose text was recorded illegible keeps its
boxes with no text (``unlabelled``) — it never enters R_oracle.

Domain: US dashcam footage (BDD100K), 1280×720, 5 fps labelled frames. Evidence-retention evidence only; never
Indian-domain validation and never OCR accuracy.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from tools.benchmarks.capabilities.plates import truth as truths
from tools.benchmarks.core.identity import require

ADAPTER_ID = "bdd-plate-labels"
ADAPTER_VERSION = "1"
VEHICLE = {"car": "car", "truck": "commercial", "bus": "commercial", "motorcycle": "motorcycle"}
LABELS = "benchmark-plate-labels-v1"


def plate_items(labels_bytes: bytes, entries: dict[str, dict[str, Any]], descriptor_sha256: str,
                size_of: Callable[[str], tuple[int, int]]) -> list[dict[str, Any]]:
    """Items of the verified labels; ``size_of`` gives an image's displayed size from its verified bytes."""
    labels = json.loads(labels_bytes)
    require(labels.get("schemaVersion") == LABELS, "plate_labels_invalid:schema")
    require(labels.get("descriptorSha256") == descriptor_sha256, "plate_labels_invalid:descriptor")
    items = []
    for track in labels["tracks"]:
        require(track["nativeClass"] in VEHICLE, f"plate_labels_invalid:class:{track['candidate']}")
        for index, frame in track["frames"].items():
            entry = entries.get(frame["imagePath"])
            require(entry is not None, f"plate_labels_invalid:image:{frame['imagePath']}")
            x1, y1, x2, y2 = frame["plateBox"]
            vx1, vy1, vx2, vy2 = frame["vehicleBox"]
            width, height = size_of(frame["imagePath"])
            vx1, vy1, vx2, vy2 = max(0.0, vx1), max(0.0, vy1), min(float(width), vx2), min(float(height), vy2)
            items.append({
                "itemId": f"{track['sequenceId']}/{int(index):06d}/{track['gtTrackId']}",
                "imagePath": frame["imagePath"], "imageSha256": entry["sha256"],
                "frameSize": {"width": width, "height": height}, "sequenceId": track["sequenceId"],
                "frameIndex": int(index), "gtTrackId": track["gtTrackId"],
                "vehicleBox": {"x": vx1, "y": vy1, "width": vx2 - vx1, "height": vy2 - vy1},
                "vehicleClass": VEHICLE[track["nativeClass"]],
                "plates": [truths.plate("plate", truths.box_polygon(x1, y1, x2 - x1, y2 - y1), track["text"],
                                        "unknown")]})
    return sorted(items, key=lambda item: item["itemId"])
