"""Stage 4 X4-0 inference: the unchanged #226 PD5-V5M/OC1-S crop analysis of every distinct crop. Development only.

Every sealed A0 Vehicle crop (B1 Arm A staging) and every extracted crop (``x4_extract``: encoded Pool frames and
native Track-frames) on the 70 pilot sequences is analysed once per distinct SHA-256 by the production
``pipeline.analyse_crop`` with the ``components_for`` adapters and the pilot parameters (``b1_plates.components``,
packs SHA-checked). The observation handle is an experiment object, not a lease contract: extra frames never
enter ``LeaseObservation``/``LeaseTrack``. ``OutputInvalid`` (over-bound model output) is recorded per crop.

Canonical records hold only the analysis; per-crop detector/OCR CPU and wall time are a separate timings file
(excluded from repeat equality). Adapters run single-threaded on the CPU provider, so a record is a function of
the crop bytes.

    python tools/benchmarks/plates/x4_infer.py run --inventory INV [--extract DIR] --out DIR [--workers N]
    python tools/benchmarks/plates/x4_infer.py verify --extract DIR DIR
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
import x4_common as c  # noqa: E402
from x4_common import B1, X4Error, require  # noqa: E402

EXPERIMENT_ROLE = "x4-extra"
_STATE: dict[str, Any] = {}


class _Timed:
    """Transparent adapter proxy accumulating process and wall time of each call into the current crop's clock."""

    def __init__(self, inner, method: str, clock: dict) -> None:
        self._inner, self._method, self._clock = inner, method, clock

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def _call(self, *args):
        cpu, wall = time.process_time(), time.perf_counter()
        try:
            return getattr(self._inner, self._method)(*args)
        finally:
            self._clock[f"{self._method}Cpu"] += time.process_time() - cpu
            self._clock[f"{self._method}Wall"] += time.perf_counter() - wall
            self._clock[f"{self._method}Calls"] += 1

    def detect(self, *args):
        return self._call(*args)

    def read(self, *args):
        return self._call(*args)


def _init() -> None:
    import b1_plates

    detector, recogniser, parameters, identity = b1_plates.components()
    clock: dict[str, float] = {}
    _STATE.update(detector=_Timed(detector, "detect", clock), recogniser=_Timed(recogniser, "read", clock),
                  parameters=parameters, identity=identity, clock=clock)


def record_of(crop) -> dict[str, Any]:
    """The canonical JSON form of a production ``CropRecord`` (observation handle fields excluded)."""
    return {"status": crop.status, "reason": crop.reason, "width": crop.width, "height": crop.height,
            "detections": [{"box": list(d.box), "score": d.score,
                            "plate": None if d.plate is None else {
                                "plateIndex": d.plate.plate_index, "outcome": d.plate.outcome,
                                "readings": [{"rank": r.rank, "rawText": r.raw_text, "rawLineCount": r.raw_line_count,
                                              "confidence": r.confidence} for r in d.plate.readings]}}
                           for d in crop.detections]}


def analyse(data: bytes, digest: str) -> tuple[dict[str, Any], dict[str, float]]:
    from mavi_vision.plates.inference import VerifiedCrop
    from mavi_vision.plates.pipeline import OutputInvalid, analyse_crop

    clock = _STATE["clock"]
    clock.clear()
    clock.update({f"{m}{k}": 0 for m in ("detect", "read") for k in ("Cpu", "Wall", "Calls")})
    handle = SimpleNamespace(observation_id=UUID(digest[:32]), role=EXPERIMENT_ROLE, evidence_rank=0)
    try:
        crop = analyse_crop(handle, VerifiedCrop(str(handle.observation_id), EXPERIMENT_ROLE, 0, digest, data),
                            _STATE["detector"], _STATE["recogniser"], _STATE["parameters"])
        record = record_of(crop)
    except OutputInvalid as error:
        record = {"status": "output_invalid", "reason": str(error), "width": None, "height": None, "detections": []}
    return record, {k: (round(v, 6) if isinstance(v, float) else v) for k, v in clock.items()}


def work(task: tuple[str, str, str]) -> tuple[str, list[dict], dict[str, dict]]:
    sequence, extract_dir, manifest_entry = task
    extract = Path(extract_dir) if extract_dir else None
    entry = json.loads(manifest_entry) if manifest_entry else None
    items: dict[str, tuple[str, Path]] = {}
    result = json.loads((B1 / "A" / "results" / f"{sequence}.json").read_bytes())
    for track in result["tracks"]:
        if track["objectClass"] == "vehicle":
            for o in track["observations"]:
                items[o["crop"]["sha256"]] = ("sealed", B1 / "A" / "staging" / sequence / o["crop"]["storageKey"])
    for row in (c.read_log(extract / "manifest" / f"{sequence}.jsonl.gz", entry) if extract else ()):
        for key, ext in (("jpeg", "jpg"), ("native", "png")):
            if row[key]:
                items.setdefault(row[key]["sha256"], (key, extract / "crops" / sequence / f"{row[key]['sha256']}.{ext}"))
    rows, timings = [], {}
    for digest in sorted(items):
        kind, path = items[digest]
        data = path.read_bytes()
        require(c.sha_bytes(data) == digest, f"x4_crop_bytes_mismatch:{sequence}:{digest[:12]}")
        record, clock = analyse(data, digest)
        rows.append({"sha256": digest, "kind": kind, "sizeBytes": len(data), "record": record})
        timings[digest] = clock
    return sequence, rows, timings


def run(inventory_path: Path, extract: Path | None, out: Path, workers: int) -> dict[str, Any]:
    """Analyse every distinct crop; with ``extract`` None, only the sealed A0 crops (the Phase-0 A0 gate)."""
    from multiprocessing import Pool

    import x4_extract

    inv, inv_sha = c.load_inventory(inventory_path)
    git = c.require_clean_code(inv)
    if extract is not None:
        x4_extract.verify(extract, inventory_path)
    ext_index = c.load(extract / "index.json") if extract is not None else None
    out.mkdir(parents=True, exist_ok=False)
    _init()
    identity = _STATE["identity"]
    require(identity["packs"] == {k: v for k, v in inv["models"]["files"].items()}
            and identity["parametersSha256"] == inv["models"]["parametersSha256"], "x4_models_not_inventory")
    tasks = [(s, str(extract) if extract else "", json.dumps(ext_index["sequences"][s]["crops"]) if ext_index else "")
             for s in sorted(inv["sequences"])]
    index: dict[str, Any] = {"kind": "x4-infer", "inventorySha256": inv_sha, "rulesSha256": inv["rulesSha256"],
                             "scope": "all" if extract is not None else "sealed-only",
                             "extractIndexSha256": c.sha_file(extract / "index.json") if extract else None,
                             "models": identity,
                             "code": {"git": git, "files": inv["code"]["files"]}, "runtime": c.runtime_identity(),
                             "workers": workers, "records": {}}
    timings: dict[str, Any] = {}
    started = time.perf_counter()
    with Pool(workers, initializer=_init) as pool:
        for n, (s, rows, clock) in enumerate(pool.imap_unordered(work, tasks), start=1):
            index["records"][s] = c.write_log(out / "records" / f"{s}.jsonl.gz", rows)
            timings[s] = clock
            print(f"infer {n} {s} crops={len(rows)} elapsed={time.perf_counter() - started:.0f}s", flush=True)
    index["records"] = dict(sorted(index["records"].items()))
    index["distinctCrops"] = sum(e["rows"] for e in index["records"].values())
    index["wallSeconds"] = round(time.perf_counter() - started, 1)
    c.dump(out / "index.json", index)
    c.dump(out / "timings.json", dict(sorted(timings.items())))
    return index


def verify(out: Path, extract: Path | None = None) -> dict[str, Any]:
    index = c.load(out / "index.json")
    require(index.get("kind") == "x4-infer", "x4_infer_index_invalid")
    seqs = sorted(index["records"])
    if extract is not None:
        require(index["extractIndexSha256"] == c.sha_file(extract / "index.json"), "x4_infer_extract_binding")
        require(seqs == sorted(c.load(extract / "index.json")["sequences"]), "x4_infer_population")
    require(sorted(p.name[: -len(".jsonl.gz")] for p in (out / "records").iterdir()) == seqs,
            "x4_infer_files_extra_or_missing")
    total = 0
    for s in seqs:
        rows = c.read_log(out / "records" / f"{s}.jsonl.gz", index["records"][s])
        require([r["sha256"] for r in rows] == sorted({r["sha256"] for r in rows}), f"x4_infer_records_order:{s}")
        total += len(rows)
    timings = c.load(out / "timings.json")
    require(sorted(timings) == seqs, "x4_infer_timings_population")
    return {"verified": True, "sequences": len(seqs), "records": total}


def canonical_view(out: Path) -> dict[str, Any]:
    index = c.load(out / "index.json")
    return {"inventory": index["inventorySha256"], "models": index["models"],
            "records": {s: e["canonicalSha256"] for s, e in index["records"].items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--inventory", type=Path, required=True)
    r.add_argument("--extract", type=Path, help="omit for the sealed-only A0 gate")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--workers", type=int, default=8)
    v = sub.add_parser("verify")
    v.add_argument("--extract", type=Path)
    v.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        index = run(args.inventory, args.extract, args.out, args.workers)
        print(f"{args.out / 'index.json'} sha256={c.sha_file(args.out / 'index.json')} crops={index['distinctCrops']}")
    else:
        print(json.dumps(verify(args.out, args.extract)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except X4Error as error:
        print(f"FAIL-CLOSED: {error}", file=sys.stderr)
        raise SystemExit(2)
