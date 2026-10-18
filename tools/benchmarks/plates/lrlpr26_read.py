"""Stage 4 LRLPR-26 aggregation experiment, phases 0-2: fail-closed inventory and the OC1-S read. Development only.

Bound to the FROZEN ``docs/qualification/stage4/lrlpr-26-aggregation-rules-v1.json`` and ``lrlpr-26-split-v1.json``
by SHA-256. Phase 1 reads every LR frame of all 20,000 train tracks once with the unchanged OC1-S path
(``FastPlateOcrRecogniser.read`` on the whole LR image, ``cpu_session``: CPU provider, 1 intra-op and 1 inter-op
thread, sequential) and stores the rank-0 raw text and confidence per frame. Nothing is scored and no truth is read.
Phase 2 and the timing pass 2T are the same run again; each must be canonical-equal to phase 1, else INVALID.

Records are deterministic gzip of canonical JSON lines (B1/X4 pattern), bound in ``index.json`` by canonical and
gzip SHA-256 and row count. Per-call CPU and wall times are a separate ``timings.json`` (excluded from equality).
Outputs hold OCR raw texts and stay on controlled storage only; nothing here is for Git.

    python tools/benchmarks/plates/lrlpr26_read.py inventory --out INV.json
    python tools/benchmarks/plates/lrlpr26_read.py read --inventory INV.json --pass phase1|phase2|phase2T --out DIR
    python tools/benchmarks/plates/lrlpr26_read.py verify --inventory INV.json DIR
    python tools/benchmarks/plates/lrlpr26_read.py equal DIR1 DIR2
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT, ROOT / "src" / "vision", ROOT / "tools" / "benchmarks" / "plates"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lrlpr26_core as core  # noqa: E402
from lrlpr26_core import require  # noqa: E402

STAGE4 = ROOT / "docs" / "qualification" / "stage4"
RULES = STAGE4 / "lrlpr-26-aggregation-rules-v1.json"
RULES_ID = "lrlpr26-aggregation-rules-v1"
PARAMETERS = ROOT / "src" / "vision" / "config" / "plates" / "development-plates-onnx-pilot-parameters-v1.json"
PAYLOADS = ROOT / "tools" / "vision" / "plates-pilot-payloads-v1.json"
PACK = Path("E:/MAVI-Working/anpr-pilot/models/plates-oc1-s-dev-v1")
EXPECTED_RULES_SHA256 = "3c14f0523adfb9dae7b434cf141ce8447aaa04c81ca8db789a7aa0ac1c1684be"
PASSES = ("phase1", "phase2", "phase2T")
WORKERS = 10
CODE_FILES = [
    "tools/benchmarks/datasets/lrlpr26.py", "tools/benchmarks/plates/lrlpr26_core.py",
    "tools/benchmarks/plates/lrlpr26_read.py", "tools/benchmarks/plates/lrlpr26_eval.py",
    "src/vision/mavi_vision/plates/normalisation.py", "src/vision/mavi_vision/plates/adapters/fast_plate_ocr.py",
    "src/vision/mavi_vision/plates/adapters/onnx.py", "src/vision/mavi_vision/plates/contracts.py",
    "src/vision/mavi_vision/plates/pipeline.py",
    "src/vision/config/plates/development-plates-onnx-pilot-parameters-v1.json",
    "tools/vision/plates-pilot-payloads-v1.json",
    "docs/qualification/stage4/lrlpr-26-aggregation-rules-v1.json", "docs/qualification/stage4/lrlpr-26-split-v1.json",
]
_STATE: dict[str, Any] = {}


def sha_file(path: Path) -> str:
    return core.sha_bytes(path.read_bytes())


def load(path: Path) -> Any:
    return json.loads(path.read_bytes())


def dump(path: Path, document: Any) -> str:
    """Write-once canonical JSON; returns its SHA-256."""
    require(not path.exists(), f"lrlpr26_output_exists:{path.name}")
    data = core.canonical(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return core.sha_bytes(data)


def rules(path: Path = RULES, expected: str | None = None) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    digest = core.sha_bytes(data)
    require(digest == (EXPECTED_RULES_SHA256 if expected is None else expected), "lrlpr26_rules_sha_mismatch")
    record = json.loads(data)
    require(record.get("id") == RULES_ID, "lrlpr26_rules_id")
    return record, digest


def split_document(record: dict[str, Any]) -> tuple[dict[str, Any], str]:
    from tools.benchmarks.datasets import lrlpr26

    path = ROOT / record["data"]["split"]["path"]
    return lrlpr26.load_split(path, record["data"]["split"]["sha256"]), record["data"]["split"]["sha256"]


def floor_of(record: dict[str, Any]) -> float:
    from mavi_vision.plates.parameters import load_parameters

    data = PARAMETERS.read_bytes()
    require(core.sha_bytes(data) == record["parameters"]["sha256"], "lrlpr26_parameters_sha_mismatch")
    floor = load_parameters(data).ocr_confidence_floor
    require(floor == record["parameters"]["ocrConfidenceFloor"], "lrlpr26_parameters_floor_mismatch")
    return floor


def model_files(record: dict[str, Any]) -> dict[str, str]:
    files = {}
    for name, digest in record["ocr"]["files"].items():
        require(sha_file(PACK / name) == digest, f"lrlpr26_model_sha_mismatch:{name}")
        files[name] = digest
    require(sha_file(PAYLOADS) == record["ocr"]["payloadsFile"]["sha256"], "lrlpr26_payloads_sha_mismatch")
    payloads = {p["file"]: p["sha256"] for p in load(PAYLOADS)["payloads"] if p["packDirectory"] == "plates-oc1-s-dev-v1"}
    require(all(payloads.get(name) == digest for name, digest in files.items()), "lrlpr26_model_not_payload")
    return files


def git_identity() -> dict[str, Any]:
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout.strip()
    return {"head": head, "trackedChangesPresent": bool(dirty)}


def code_files() -> dict[str, str]:
    return {name: sha_file(ROOT / name) for name in CODE_FILES}


def require_clean_code(inventory: dict[str, Any]) -> dict[str, Any]:
    git = git_identity()
    require(not git["trackedChangesPresent"], "lrlpr26_code_tree_dirty")
    require(code_files() == inventory["code"]["files"], "lrlpr26_code_changed_since_inventory")
    return git


def machine_identity() -> dict[str, Any]:
    out: dict[str, Any] = {"python": platform.python_version(), "executable": sys.executable,
                           "platform": platform.platform(), "processor": platform.processor(),
                           "logicalCpus": os.cpu_count()}
    for module in ("numpy", "PIL", "onnxruntime", "cv2", "yaml"):
        try:
            out[module] = __import__(module).__version__
        except ImportError:
            out[module] = None
    return out


# phase 0: inventory -------------------------------------------------------------------------------------------------

def inventory() -> dict[str, Any]:
    """Hash-bind every input; the committed split must be regenerated byte-identically from the data."""
    from tools.benchmarks.datasets import lrlpr26

    record, rules_sha = rules()
    split, split_sha = split_document(record)
    floor = floor_of(record)
    files = model_files(record)
    for name, digest in record["ocr"]["codeSha256AtFreeze"].items():
        require(sha_file(ROOT / name) == digest, f"lrlpr26_code_changed_since_freeze:{name}")
    tracks, extra = lrlpr26.load_tracks()
    inv = extra["inventory"]
    require(inv["trainArchive"]["sha256"] == record["data"]["trainArchiveSha256"]
            and inv["trainManifest"]["sha256"] == record["data"]["trainManifestSha256"], "lrlpr26_dataset_not_rules")
    regenerated = core.canonical(lrlpr26.build_split(tracks, extra["imageHashes"], lrlpr26.split_identities(inv)))
    require(core.sha_bytes(regenerated) == split_sha, "lrlpr26_split_not_reproduced")
    require(sorted(split["tracks"]) == sorted(t.track_id for t in tracks), "lrlpr26_split_population")
    return {
        "kind": "lrlpr26-inventory", "rules": RULES_ID, "rulesSha256": rules_sha, "splitSha256": split_sha,
        "dataset": {"trainArchive": inv["trainArchive"], "trainManifest": inv["trainManifest"],
                    "annotationsDigest": inv["annotationsDigest"], "adapter": inv["adapter"]},
        "parametersSha256": record["parameters"]["sha256"], "ocrConfidenceFloor": floor, "models": files,
        "tracks": {t.track_id: {"stratum": t.stratum, "lr": [f.sha256 for f in t.lr_frames]} for t in tracks},
        "code": {"git": git_identity(), "files": code_files()},
    }


def load_inventory(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    inv = json.loads(data)
    require(inv.get("kind") == "lrlpr26-inventory", "lrlpr26_inventory_invalid")
    record, rules_sha = rules()
    require(inv["rulesSha256"] == rules_sha and inv["splitSha256"] == record["data"]["split"]["sha256"],
            "lrlpr26_inventory_rules_binding")
    require(len(inv["tracks"]) == 20000, "lrlpr26_inventory_population")
    return inv, core.sha_bytes(data)


# phases 1/2/2T: read ------------------------------------------------------------------------------------------------

def _init() -> None:
    from mavi_vision.plates.adapters.fast_plate_ocr import FastPlateOcrRecogniser
    from mavi_vision.plates.adapters.onnx import cpu_session

    _STATE["recogniser"] = FastPlateOcrRecogniser(
        {"onnx-model": PACK / "cct_s_v2_global.onnx", "plate-config": PACK / "cct_s_v2_global_plate_config.yaml"},
        session_factory=cpu_session)


def read_frame(recogniser, data: bytes) -> tuple[dict[str, Any], dict[str, float]]:
    """One LR frame through OC1-S: the stored reading and its CPU/wall clock (ms)."""
    from PIL import Image

    from mavi_vision.plates.contracts import is_raw_text
    from mavi_vision.plates.pipeline import _probability

    clock = {"decodeCpuMs": 0.0, "readCpuMs": 0.0, "readWallMs": 0.0}
    cpu = time.process_time()
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # noqa: BLE001 - an undecodable frame is an OCR error (ineligible), by the frozen rules.
        clock["decodeCpuMs"] = (time.process_time() - cpu) * 1000
        return {"status": "ocrError", "rawText": None, "confidence": None}, clock
    clock["decodeCpuMs"] = (time.process_time() - cpu) * 1000
    cpu, wall = time.process_time(), time.perf_counter()
    try:
        readings = list(recogniser.read(image, None, None))
    except Exception:  # noqa: BLE001 - any OCR fault makes the frame ineligible, by the frozen rules.
        readings = None
    clock["readCpuMs"] = (time.process_time() - cpu) * 1000
    clock["readWallMs"] = (time.perf_counter() - wall) * 1000
    if readings is None:
        return {"status": "ocrError", "rawText": None, "confidence": None}, clock
    if not readings:
        return {"status": "empty", "rawText": None, "confidence": None}, clock
    if len(readings) != 1 or not is_raw_text(readings[0].raw_text) or not _probability(readings[0].confidence):
        return {"status": "outputInvalid", "rawText": None, "confidence": None}, clock
    return {"status": "ok", "rawText": readings[0].raw_text, "confidence": float(readings[0].confidence)}, clock


def work(task: tuple[str, str, list[str]]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    from tools.benchmarks.datasets import lrlpr26

    track_id, stratum, shas = task
    scenario, layout = stratum.split("/")
    ext = lrlpr26.SCENARIOS[scenario]
    frames, clocks = [], []
    for frame, digest in zip(core.FRAMES, shas):
        data = (lrlpr26.TRAIN_ROOT / scenario / layout / track_id / f"{frame}.{ext}").read_bytes()
        require(core.sha_bytes(data) == digest, f"lrlpr26_frame_bytes_mismatch:{track_id}:{frame}")
        reading, clock = read_frame(_STATE["recogniser"], data)
        frames.append({"frame": frame, "sha256": digest, **reading})
        clocks.append({k: round(v, 4) for k, v in clock.items()})
    return track_id, {"trackId": track_id, "frames": frames}, {"frames": clocks}


def read(inventory_path: Path, pass_label: str, out: Path, workers: int = WORKERS) -> dict[str, Any]:
    from multiprocessing import Pool

    require(pass_label in PASSES, "lrlpr26_pass_invalid")
    inv, inv_sha = load_inventory(inventory_path)
    record, rules_sha = rules()
    git = require_clean_code(inv)
    split_document(record)
    require(floor_of(record) == inv["ocrConfidenceFloor"], "lrlpr26_floor_not_inventory")
    require(model_files(record) == inv["models"], "lrlpr26_models_not_inventory")
    out.mkdir(parents=True, exist_ok=False)
    order = sorted(inv["tracks"], key=lambda t: int(t.split("_")[1]))
    tasks = [(t, inv["tracks"][t]["stratum"], inv["tracks"][t]["lr"]) for t in order]
    rows, timings = [], {}
    started = time.perf_counter()
    with Pool(workers, initializer=_init) as pool:
        for n, (track_id, row, clock) in enumerate(pool.imap(work, tasks, chunksize=25), start=1):
            rows.append(row)
            timings[track_id] = clock
            if n % 1000 == 0:
                print(f"{pass_label} {n}/{len(tasks)} elapsed={time.perf_counter() - started:.0f}s", flush=True)
    require([r["trackId"] for r in rows] == order, "lrlpr26_read_order")
    data, entry = core.log_entry(rows)
    (out / "records.jsonl.gz").write_bytes(data)
    timing_sha = dump(out / "timings.json", timings)
    index = {"kind": "lrlpr26-read", "pass": pass_label, "inventorySha256": inv_sha, "rulesSha256": rules_sha,
             "splitSha256": inv["splitSha256"], "parametersSha256": inv["parametersSha256"],
             "ocrConfidenceFloor": inv["ocrConfidenceFloor"], "models": inv["models"],
             "code": {"git": git, "files": inv["code"]["files"]}, "machine": machine_identity(),
             "execution": {"workers": workers, "ortIntraOpThreads": 1, "ortInterOpThreads": 1,
                           "ortExecutionMode": "ORT_SEQUENTIAL", "provider": "CPUExecutionProvider"},
             "records": entry, "timingsSha256": timing_sha, "tracks": len(rows), "frames": 5 * len(rows),
             "statusCounts": _status_counts(rows), "wallSeconds": round(time.perf_counter() - started, 1)}
    dump(out / "index.json", index)
    return index


def _status_counts(rows: list[dict]) -> dict[str, int]:
    counts = {status: 0 for status in core.STATUSES}
    for row in rows:
        for frame in row["frames"]:
            counts[frame["status"]] += 1
    return counts


def verify(out: Path, inventory_path: Path | None = None) -> dict[str, Any]:
    """Fail closed on a missing, extra or changed record, timing file or binding; returns the decoded rows."""
    index = load(out / "index.json")
    require(index.get("kind") == "lrlpr26-read" and index.get("pass") in PASSES, "lrlpr26_read_index_invalid")
    require(sorted(p.name for p in out.iterdir()) == ["index.json", "records.jsonl.gz", "timings.json"],
            "lrlpr26_read_files_extra_or_missing")
    rows = core.decode_log((out / "records.jsonl.gz").read_bytes(), index["records"], "records.jsonl.gz")
    require(sha_file(out / "timings.json") == index["timingsSha256"], "lrlpr26_read_timings_mismatch")
    timings = load(out / "timings.json")
    require(sorted(timings) == sorted(r["trackId"] for r in rows), "lrlpr26_read_timings_population")
    if inventory_path is not None:
        inv, inv_sha = load_inventory(inventory_path)
        require(index["inventorySha256"] == inv_sha, "lrlpr26_read_inventory_binding")
        require([r["trackId"] for r in rows] == sorted(inv["tracks"], key=lambda t: int(t.split("_")[1])),
                "lrlpr26_read_population")
        for r in rows:
            require([f["sha256"] for f in r["frames"]] == inv["tracks"][r["trackId"]]["lr"]
                    and [f["frame"] for f in r["frames"]] == list(core.FRAMES), f"lrlpr26_read_frames:{r['trackId']}")
            for f in r["frames"]:
                core.validate_reading(f)
    require(_status_counts(rows) == index["statusCounts"], "lrlpr26_read_status_counts")
    return {"verified": True, "pass": index["pass"], "tracks": len(rows), "rows": rows, "index": index}


def equal(first: Path, second: Path) -> dict[str, Any]:
    a, b = verify(first), verify(second)
    ia, ib = a["index"], b["index"]
    keys = ("inventorySha256", "rulesSha256", "splitSha256", "parametersSha256", "models")
    same = all(ia[k] == ib[k] for k in keys) and ia["records"]["canonicalSha256"] == ib["records"]["canonicalSha256"]
    return {"canonicalEqual": same, "gzipBytesEqual": ia["records"]["gzipSha256"] == ib["records"]["gzipSha256"],
            "passes": [ia["pass"], ib["pass"]], "recordsCanonicalSha256": [ia["records"]["canonicalSha256"],
                                                                         ib["records"]["canonicalSha256"]]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    i = sub.add_parser("inventory")
    i.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("read")
    r.add_argument("--inventory", type=Path, required=True)
    r.add_argument("--pass", dest="pass_label", choices=PASSES, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--workers", type=int, default=WORKERS)
    v = sub.add_parser("verify")
    v.add_argument("--inventory", type=Path)
    v.add_argument("out", type=Path)
    e = sub.add_parser("equal")
    e.add_argument("first", type=Path)
    e.add_argument("second", type=Path)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        print(f"{args.out} sha256={dump(args.out, inventory())}")
    elif args.command == "read":
        require(args.workers == WORKERS, "lrlpr26_workers_not_frozen")
        index = read(args.inventory, args.pass_label, args.out, args.workers)
        print(f"{args.out / 'index.json'} sha256={sha_file(args.out / 'index.json')} "
              f"records={index['records']['canonicalSha256']} status={index['statusCounts']}")
    elif args.command == "verify":
        result = verify(args.out, args.inventory)
        print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "index")}))
    else:
        result = equal(args.first, args.second)
        print(json.dumps(result, indent=1))
        return 0 if result["canonicalEqual"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
