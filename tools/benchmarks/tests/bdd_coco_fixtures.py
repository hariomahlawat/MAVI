"""Synthetic derived (COCO-format) BDD100K MOT sources, made from the raw Scalabel fixtures by an independent
re-statement of the official conversion (``bdd100k_to_scalabel`` with ``box_track.toml``, then
``scalabel2coco_box_track``). No dataset bytes; every value comes from ``bdd_fixtures``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import bdd_fixtures as b

LEAVES = ["pedestrian", "rider", "car", "truck", "bus", "train", "motorcycle", "bicycle"]
NAME_MAPPING = {"bike": "bicycle", "caravan": "car", "motor": "motorcycle", "person": "pedestrian", "van": "car"}
IGNORED_MAPPING = {"other person": "pedestrian", "other vehicle": "car", "trailer": "truck"}
ANNOTATION = "labels/box_track_20_cocofmt/bdd_box_track_val_cocofmt.json"


def convert(documents: dict[str, list[dict]]) -> dict[str, Any]:
    out: dict[str, Any] = {"categories": [{"id": i + 1, "name": n, "supercategory": "none"}
                                          for i, n in enumerate(LEAVES)],
                           "videos": [], "images": [], "annotations": []}
    image_id = annotation_id = 0
    for video_id, (video, frames) in enumerate(sorted(documents.items()), start=1):
        out["videos"].append({"id": video_id, "name": video})
        numbers: dict[str, int] = {}
        for frame in sorted(frames, key=lambda f: f["frameIndex"]):
            image_id += 1
            out["images"].append({"id": image_id, "video_id": video_id, "frame_id": frame["frameIndex"],
                                  "file_name": f"{video}/{frame['name']}", "width": b.WIDTH, "height": b.HEIGHT})
            for label in frame["labels"]:
                category = NAME_MAPPING.get(label["category"], label["category"])
                ignored = category in IGNORED_MAPPING
                category = IGNORED_MAPPING.get(category, category)
                box = label["box2d"]
                annotation_id += 1
                numbers.setdefault(label["id"], len(numbers) + 1)
                width, height = box["x2"] - box["x1"] + 1, box["y2"] - box["y1"] + 1
                out["annotations"].append({
                    "id": annotation_id, "image_id": image_id, "category_id": LEAVES.index(category) + 1,
                    "instance_id": numbers[label["id"]], "scalabel_id": label["id"],
                    "iscrowd": int(bool(label["attributes"].get("crowd")) or ignored), "ignore": 0,
                    "bbox": [box["x1"], box["y1"], width, height], "area": float(width * height)})
    return out


def write_source(root: Path, document: dict[str, Any] | None = None, *, image: bytes | None = None,
                 videos: dict[str, list[dict]] | None = None) -> Path:
    """Images from ``bdd_fixtures`` (no raw label files) plus one derived annotation file."""
    root = Path(root)
    videos = b.labels() if videos is None else videos
    b.write_source(root, videos, image=image)
    for path in (root / "labels" / "box_track_20").rglob("*.json"):
        path.unlink()
    (root / "labels" / "box_track_20" / "val").rmdir()
    (root / "labels" / "box_track_20").rmdir()
    target = root / ANNOTATION
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(convert(b.labels()) if document is None else document), encoding="utf-8")
    return root
