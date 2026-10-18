"""Stage 4 X4-0: shared identities, fail-closed inventory and record helpers. Development experiment only.

X4-0 is the offline multi-frame counterfactual frozen in ``docs/qualification/stage4/x4-0-rules-v1.json``. It
reads extra Track-frames of the B1 Arm A replay through the unchanged #226 PD5-V5M/OC1-S crop analysis. The
extra frames stay in this experiment seam: they never become a plate lease, a ``LeaseObservation`` or anything
the platform sees, and no ``src/vision`` code, Production contract or release profile is changed.

The helpers restate B1's patterns (``b1_run``): deterministic gzip of canonical JSON lines, logs bound by their
canonical and gzip SHA-256 and row count, and fail-closed reads.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT, ROOT / "src" / "vision", ROOT / "tools" / "benchmarks" / "plates"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))



def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_lines(rows: list[dict]) -> bytes:
    """B1's canonical JSON lines (``b1_run.canonical_lines``), restated here so that inference does not import the
    replay stack (``b1_run`` pulls in the video reader, which the plates venv lacks)."""
    return b"".join(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8") + b"\n"
                    for r in rows)


def write_log(path: Path, rows: list[dict]) -> dict[str, Any]:
    """Deterministic gzip (mtime 0, empty name, level 9) of canonical JSON lines (B1 pattern)."""
    raw = canonical_lines(rows)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as handle:
        handle.write(raw)
    data = buffer.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"rows": len(rows), "canonicalSha256": sha_bytes(raw), "gzipSha256": sha_bytes(data)}


def read_log(path: Path, entry: dict[str, Any]) -> list[dict]:
    """Decode a log and require its gzip digest, canonical digest, canonical form and row count (B1 pattern)."""
    data = path.read_bytes()
    require(sha_bytes(data) == entry["gzipSha256"], f"x4_log_gzip_mismatch:{path.name}")
    raw = gzip.decompress(data)
    require(sha_bytes(raw) == entry["canonicalSha256"], f"x4_log_canonical_mismatch:{path.name}")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    require(canonical_lines(rows) == raw, f"x4_log_not_canonical:{path.name}")
    require(len(rows) == entry["rows"], f"x4_log_rowcount_mismatch:{path.name}")
    return rows


H3 = Path("E:/MAVI-Controlled/Stage3/H3-attempt2")
B1 = Path("E:/MAVI-Working/b1")
PILOT_RESULT = Path("E:/MAVI-Working/anpr-pilot-cuda/out/pilot-result.json")
PILOT_EXPORTS = Path("E:/MAVI-Working/anpr-pilot-cuda/exports")
O5 = Path("E:/MAVI-Controlled/Benchmarks/stage4-bdd-plates/results-human-reviewed")
PROFILE = ROOT / "src" / "vision" / "config" / "pipelines" / "phase1-detection-tracking-v1.json"
RULES = ROOT / "docs" / "qualification" / "stage4" / "x4-0-rules-v1.json"
RULES_ID = "x4-0-multiframe-counterfactual-rules-v1"

EXPECTED = {
    "rules": "ffac3f56757e9ff1993395ff6471cfba6798ab08646829269d333a69206da767",
    "b1Inventory": "706a38264f291473f613370c4e52d93cd0e7f97fbe122a04cceb2ee99a5bf0b4",
    "b1ArmAIndex": "1c9d84b0d692371290e3ec77d4d63b5f96caecca4ae979bc7e37530a3aa77a6a",
    "b1ArmAEval": "5fcd2c8ee807f9602766b7153802f1645621e2d6548f032ef19b44d166676dbc",
    "b1PlatesPhase2": "e8113709abba4f78c139a00b3f722779b56c909be988000763f60be2000ea1c2",
    "b1Account": "3812d292",
    "manifest": "a295809d4e5865017b63fc4edd0b7a049e9e7391527ff008ca43b4f50da86cda",
    "pilot": "4c346df937cd2d7c579e977b26ad2a3aea9c49d8d3e7282cccbcabe3dd00db15",
    "o5Truth": "8d1d03b2",
    "profile": "afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf",
    "pd5": "a4319856", "oc1": "384bbbd2", "parameters": "cce6ff6d",
}
CODE_FILES = [
    "tools/benchmarks/plates/x4_common.py", "tools/benchmarks/plates/x4_select.py",
    "tools/benchmarks/plates/x4_extract.py", "tools/benchmarks/plates/x4_infer.py",
    "tools/benchmarks/plates/x4_eval.py", "tools/benchmarks/plates/b1_run.py",
    "tools/benchmarks/plates/b1_plates.py", "tools/benchmarks/plates/b1_nearview.py",
    "src/vision/mavi_vision/video/reader.py", "src/vision/mavi_vision/quality/scoring.py",
    "src/vision/mavi_vision/evidence/encoder.py", "src/vision/mavi_vision/evidence/policy.py",
    "src/vision/mavi_vision/evidence/roles.py", "src/vision/mavi_vision/plates/pipeline.py",
    "src/vision/mavi_vision/plates/inference.py", "src/vision/mavi_vision/plates/normalisation.py",
    "src/vision/mavi_vision/plates/contracts.py", "src/vision/mavi_vision/plates/parameters.py",
    "src/vision/mavi_vision/plates/adapters/onnx.py", "src/vision/mavi_vision/plates/adapters/ppocr_db.py",
    "src/vision/mavi_vision/plates/adapters/fast_plate_ocr.py",
    "src/vision/config/plates/development-plates-onnx-pilot-parameters-v1.json",
    "tools/vision/plates-pilot-payloads-v1.json", "docs/qualification/stage4/x4-0-rules-v1.json",
]


class X4Error(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise X4Error(code)


def load(path: Path) -> Any:
    return json.loads(path.read_bytes())


def dump(path: Path, document: Any) -> str:
    data = json.dumps(document, indent=1, sort_keys=True, default=str).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha_bytes(data)


def rules() -> tuple[dict[str, Any], str]:
    """The frozen record, bound by its committed SHA-256."""
    data = RULES.read_bytes()
    digest = sha_bytes(data)
    require(digest == EXPECTED["rules"], "x4_rules_changed")
    record = json.loads(data)
    require(record["id"] == RULES_ID, "x4_rules_id")
    return record, digest


def git_identity() -> dict[str, Any]:
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout.strip()
    return {"head": head, "trackedChangesPresent": bool(dirty)}


def code_files() -> dict[str, str]:
    return {name: sha_file(ROOT / name) for name in CODE_FILES if (ROOT / name).exists()}


def runtime_identity() -> dict[str, Any]:
    out: dict[str, Any] = {"python": platform.python_version(), "executable": sys.executable}
    for module in ("numpy", "PIL", "av", "onnxruntime"):
        try:
            out[module] = __import__(module).__version__
        except ImportError:
            out[module] = None
    return out


def require_clean_code(inventory: dict[str, Any]) -> dict[str, Any]:
    """Runs execute committed code only, identical to the code the inventory bound."""
    git = git_identity()
    require(not git["trackedChangesPresent"], "x4_code_tree_dirty")
    require(code_files() == inventory["code"]["files"], "x4_code_changed_since_inventory")
    return git


def pilot_sequences(pilot: dict[str, Any]) -> list[str]:
    seqs = sorted({run["sequenceId"] for run in pilot["runs"]})
    require(len(seqs) == 70 and len(pilot["tracks"]) == 110, "x4_pilot_population")
    return seqs


def _expect(name: str, digest: str) -> str:
    require(digest.startswith(EXPECTED[name]), f"x4_inventory_hash_mismatch:{name}")
    return digest


def inventory() -> dict[str, Any]:
    """Hash-bind every X4-0 input; anything missing, extra or mismatched raises."""
    _, rules_sha = rules()
    pilot_sha = _expect("pilot", sha_file(PILOT_RESULT))
    pilot = load(PILOT_RESULT)
    seqs = pilot_sequences(pilot)
    b1_inv_path = B1 / "inventory.json"
    _expect("b1Inventory", sha_file(b1_inv_path))
    b1_inv = load(b1_inv_path)
    manifest_path = H3 / "derived" / "derivation-manifest.json"
    _expect("manifest", sha_file(manifest_path))
    require(b1_inv["manifest"]["sha256"] == EXPECTED["manifest"], "x4_b1_inventory_manifest")
    manifest = {row["sequenceId"]: row for row in load(manifest_path)["sequences"]}
    a_index_path = B1 / "A" / "index.json"
    _expect("b1ArmAIndex", sha_file(a_index_path))
    a_index = load(a_index_path)
    require(a_index["arm"] == "A" and a_index["mode"] == "production"
            and a_index["inventorySha256"] == EXPECTED["b1Inventory"], "x4_b1_arm_a_identity")
    require(set(seqs) <= set(a_index["results"]), "x4_pilot_sequence_not_in_b1")
    rows: dict[str, Any] = {}
    for s in seqs:
        video = H3 / "derived" / "sequences" / s / "video.mp4"
        v = sha_file(video)
        require(v == manifest[s]["derivedVideoSha256"] == b1_inv["sequences"][s]["videoSha256"]
                and v == a_index["inputs"][s]["videoSha256"], f"x4_video_mismatch:{s}")
        result_path = B1 / "A" / "results" / f"{s}.json"
        require(sha_file(result_path) == a_index["results"][s], f"x4_b1_result_mismatch:{s}")
        log = a_index["candidateLogs"][s]
        candidate_rows = read_log(B1 / "A" / "candidates" / f"{s}.jsonl.gz", log)
        result = load(result_path)
        crops = {}
        for track in result["tracks"]:
            if track["objectClass"] == "vehicle":
                for o in track["observations"]:
                    data = (B1 / "A" / "staging" / s / o["crop"]["storageKey"]).read_bytes()
                    require(sha_bytes(data) == o["crop"]["sha256"] and len(data) == o["crop"]["sizeBytes"],
                            f"x4_sealed_crop_mismatch:{s}")
                    crops[o["crop"]["sha256"]] = len(data)
        rows[s] = {"videoSha256": v, "videoSizeBytes": video.stat().st_size, "b1ResultSha256": a_index["results"][s],
                   "candidateLog": {k: log[k] for k in ("rows", "canonicalSha256", "gzipSha256")},
                   "vehicleCandidateRows": len(candidate_rows),
                   "vehicleTracks": sum(1 for t in result["tracks"] if t["objectClass"] == "vehicle"),
                   "sealedVehicleCrops": len(crops)}
    payloads_path = ROOT / "tools" / "vision" / "plates-pilot-payloads-v1.json"
    packs = Path("E:/MAVI-Working/anpr-pilot/models")
    model_files = {}
    for p in load(payloads_path)["payloads"]:
        path = packs / p["packDirectory"] / p["file"]
        if path.exists():
            require(sha_file(path) == p["sha256"], f"x4_pack_mismatch:{p['packDirectory']}/{p['file']}")
            model_files[f"{p['packDirectory']}/{p['file']}"] = p["sha256"]
    _expect("pd5", model_files["plates-pd5-v5m-dev-v1/inference.onnx"])
    _expect("oc1", model_files["plates-oc1-s-dev-v1/cct_s_v2_global.onnx"])
    parameters = ROOT / "src" / "vision" / "config" / "plates" / "development-plates-onnx-pilot-parameters-v1.json"
    return {
        "kind": "x4-inventory", "rules": RULES_ID, "rulesSha256": rules_sha,
        "pilot": {"path": str(PILOT_RESULT), "sha256": pilot_sha, "sequences": len(seqs), "gtTracks": 110},
        "b1": {"inventory": EXPECTED["b1Inventory"], "armAIndex": EXPECTED["b1ArmAIndex"],
               "armAEval": _expect("b1ArmAEval", sha_file(B1 / "A-eval.json")),
               "platesPhase2": _expect("b1PlatesPhase2", sha_file(B1 / "plates-phase2.json")),
               "account": _expect("b1Account", sha_file(B1 / "account.json"))},
        "manifestSha256": EXPECTED["manifest"],
        "o5Truth": _expect("o5Truth", sha_file(O5 / "truth-val.json")),
        "profileSha256": _expect("profile", sha_file(PROFILE)),
        "models": {"files": model_files, "parametersSha256": _expect("parameters", sha_file(parameters)),
                   "payloadsSha256": sha_file(payloads_path)},
        "sequences": rows,
        "totals": {"vehicleCandidateRows": sum(r["vehicleCandidateRows"] for r in rows.values()),
                   "vehicleTracks": sum(r["vehicleTracks"] for r in rows.values()),
                   "sealedVehicleCrops": sum(r["sealedVehicleCrops"] for r in rows.values())},
        "code": {"git": git_identity(), "files": code_files()},
    }


def load_inventory(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    inv = json.loads(data)
    require(inv.get("kind") == "x4-inventory", "x4_inventory_invalid")
    _, rules_sha = rules()
    require(inv["rulesSha256"] == rules_sha, "x4_inventory_rules_binding")
    return inv, sha_bytes(data)


def directory_digest(directory: Path) -> str:
    """One digest over the sorted (relative path, SHA-256, size) of every file under ``directory``."""
    items = sorted((p.relative_to(directory).as_posix(), sha_file(p), p.stat().st_size)
                   for p in directory.rglob("*") if p.is_file())
    return sha_bytes(json.dumps(items, separators=(",", ":")).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    require(not args.out.exists(), "x4_output_exists")
    print(f"{args.out} sha256={dump(args.out, inventory())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
