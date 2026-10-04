"""Evaluator scenarios through the real path: descriptor and mapping → canonical GT → T1 export with sealed
trajectories → class-free projection → association → evaluation. Each object is a GT track on its own grid cell;
a matched object gets a MAVI Vehicle Track that follows it exactly (so association assigns it) with the given
stored subclass (``None`` = abstained → ``undetermined``)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import track_fixtures as f
from tools.benchmarks.capabilities.vehicle_subclass import evaluate as evaluation
from tools.benchmarks.capabilities.vehicle_tracks import mavi_tracks as mt
from tools.benchmarks.core import mavi
from tools.benchmarks.core.identity import document_sha256

REQUIREMENTS = f.ROOT / "docs" / "qualification" / "stage3" / "s3-2-subclass-requirements.json"
FRAMES = 10


def cell(index: int) -> tuple[float, float, float, float]:
    column, row = index % 8, index // 8
    return 0.02 + 0.12 * column, 0.02 + 0.19 * row, 0.08, 0.08


def mapping_doc(rows: list[tuple]) -> dict[str, Any]:
    """Rows ``(native, maviClass | None, kind, unsupportedKind | None)``."""
    evaluation_of = {"exact": "scored", "subset": "subset-conditional", "unsupported": "excluded"}
    items = []
    for native, mavi_class, kind, unsupported in sorted(rows):
        item = {"nativeClass": native, "maviClass": mavi_class, "kind": kind, "reason": "Fixture mapping.",
                "evaluation": evaluation_of[kind]}
        if unsupported:
            item["unsupportedKind"] = unsupported
        items.append(item)
    return {"schemaVersion": "benchmark-class-mapping-v1", "datasetId": "synthetic-vehicles",
            "release": "synthetic-v1", "capability": "mavi-vehicle-subclass-v1", "mappings": items}


def descriptor_for(mapping: dict[str, Any]) -> dict[str, Any]:
    document = copy.deepcopy(f.descriptor())
    document["nativeTaxonomy"] = [{"code": row["nativeClass"], "name": row["nativeClass"].title(),
                                   "definition": f"Fixture class {row['nativeClass']}."} for row in mapping["mappings"]]
    return document


class Scenario:
    def __init__(self, tmp: Path, objects: list[dict[str, Any]], rows: list[tuple], *, sequence: str = "seq-1",
                 mapping: dict[str, Any] | None = None, descriptor: dict[str, Any] | None = None) -> None:
        self.mapping = mapping or mapping_doc(rows)
        self.descriptor = descriptor or descriptor_for(self.mapping)
        tracks, specs = {}, []
        for index, item in enumerate(objects):
            box = cell(index)
            gt_id = item.get("id", f"g{index:03d}")
            tracks[gt_id] = f.static(box, range(FRAMES))
            if item.get("matched", True):
                observed = item.get("observation", box)  # a mismatching box fails the IoU gate (unverified)
                spec = {"n": index + 1, "points": f.follow(box, range(FRAMES)), "observations": [(400, observed)]}
                if "subclass" in item:
                    spec["subclass"] = item["subclass"]
                specs.append(spec)
        self.classes = {item.get("id", f"g{index:03d}"): item["native"] for index, item in enumerate(objects)}
        self.document = f.gt_document(tracks, sequence=sequence, classes=self.classes)
        path = f.write_export(tmp / "run", tmp / "evidence", specs or [{"n": 99, "points": [(0, 0.99, 0.99)]}])
        self.exports = mavi.load_exports([path])
        self.run = mt.project(next(iter(self.exports.values())), tmp / "evidence")
        self.requirements, self.requirements_sha = evaluation.load_requirements(REQUIREMENTS)
        self.association = f.associate([self.document], [self.run], descriptor_document=self.descriptor,
                                       mapping_sha256=document_sha256(self.mapping),
                                       requirements_sha256=self.requirements_sha)

    def evaluate(self, **changes: Any) -> dict[str, Any]:
        inputs = {"association": self.association, "descriptor": self.descriptor, "mapping": self.mapping,
                  "ground_truth": {self.document["sequenceId"]: self.document}, "exports": self.exports,
                  "requirements": self.requirements, "requirements_sha256": self.requirements_sha}
        inputs.update(changes)
        return evaluation.evaluate(**inputs)


def cls(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in result["scopeB"]["classes"] if item["maviClass"] == name)


def value(fraction: dict[str, Any] | None):
    return None if fraction is None else fraction["value"]


def load_requirements_sha() -> str:
    return evaluation.load_requirements(REQUIREMENTS)[1]
