"""Stage 4 B1 (#228) runner: fail-closed inventory, replay arms and canonical verification. Development only.

Reuses the X1 replay machinery: the retained X1 detector streams through the real ``ByteTrackTracker``,
``VideoProcessor``, ``JpegLadderEncoder`` and staging store, with the release profile unchanged. No detector
inference runs. Arms (each its own output directory and ProcessingRun identity
``uuid(sha256("stage4-b1/<arm>/<sequence>"))``):

* ``A``        — the production ``EvidenceSelector``, unmodified (the composition is asserted to be production);
* ``B``        — ``B1NearViewSelector`` in ``active`` mode (the frozen candidate);
* ``preflight``— ``B1NearViewSelector`` in ``shadow`` mode: production selection, plus a record of every b1-only
  candidate and whether the unchanged NearView duplicate/growth rules would have allowed it (holds nothing).

Every arm writes per-candidate Vehicle records with ``qualifiedOriginal`` / ``qualifiedNearB1`` and the B1
scalars, as deterministic gzip (``mtime=0``, no file name) of canonical JSON lines; the index binds the canonical
(uncompressed) SHA-256, the gzip SHA-256 and row count of every log, every result, every staged artefact and
every input. ``verify`` re-checks all of it from disk; ``equal`` compares two runs on canonical content.

    python tools/benchmarks/plates/b1_run.py inventory --out INV.json
    python tools/benchmarks/plates/b1_run.py replay --arm A|B|preflight --inventory INV.json --out DIR
    python tools/benchmarks/plates/b1_run.py verify --inventory INV.json DIR
    python tools/benchmarks/plates/b1_run.py equal DIR1 DIR2
"""
from __future__ import annotations

import argparse
import dataclasses
import gzip
import hashlib
import io
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT / "tools" / "vision" / "dev", ROOT / "src" / "vision", ROOT / "tools" / "benchmarks" / "plates"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import b1_nearview as b1  # noqa: E402

H3 = Path("E:/MAVI-Controlled/Stage3/H3-attempt2")
X1 = Path("E:/MAVI-Controlled/Benchmarks/stage4-x1")
PLATES = Path("E:/MAVI-Controlled/Benchmarks/stage4-bdd-plates")
MODEL_ROOT = Path("E:/MAVI-Controlled/Benchmarks/stage4-instruments")
PROFILE = ROOT / "src" / "vision" / "config" / "pipelines" / "phase1-detection-tracking-v1.json"
INSTRUMENT_SPECS = [ROOT / "docs" / "qualification" / "stage4" / "instruments" / name
                    for name in ("fast-plate-ocr-cct-s-v2-global.json", "rapidocr-ppocrv4.json")]

# Full digests already established by the retained record (docs and register); prefixes where only those are cited.
EXPECTED = {
    "manifest": "a295809d4e5865017b63fc4edd0b7a049e9e7391527ff008ca43b4f50da86cda",
    "profile": "afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf",
    "x1LiveIndex": "53b29146", "x1BaselineIndex": "98b1f7d3", "x1Verify": "69e7b828",
    "o5Truth": "8d1d03b2", "o5Ea": "db2656f1", "o5Eb": "b3aa0b4d", "o5Verdict": "6dc95563",
    "aiTruth": "709a560b", "aiEa": "cc718922", "aiEb": "3db69e53", "descriptor": "7169263a",
}
CODE_FILES = [
    "src/vision/mavi_vision/evidence/selector.py", "src/vision/mavi_vision/evidence/quality.py",
    "src/vision/mavi_vision/evidence/encoder.py", "src/vision/mavi_vision/evidence/policy.py",
    "src/vision/mavi_vision/evidence/roles.py", "src/vision/mavi_vision/quality/scoring.py",
    "src/vision/mavi_vision/pipeline/process_video.py", "src/vision/mavi_vision/tracking/bytetrack.py",
    "src/vision/mavi_vision/video/reader.py", "tools/vision/dev/measure_evidence_real_clips.py",
    "tools/benchmarks/plates/b1_nearview.py", "tools/benchmarks/plates/b1_run.py",
    "tools/benchmarks/plates/b1_eval.py", "tools/benchmarks/plates/x1_eval.py",
    "tools/benchmarks/capabilities/plates/coverage.py", "tools/benchmarks/capabilities/plates/measure.py",
    "docs/qualification/stage4/b1-candidate-v1.json",
]
ARMS = ("A", "B", "preflight")


class B1Error(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise B1Error(code)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect(name: str, digest: str) -> str:
    require(digest.startswith(EXPECTED[name]), f"b1_inventory_hash_mismatch:{name}")
    return digest


def canonical_lines(rows: list[dict]) -> bytes:
    return b"".join(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8") + b"\n"
                    for r in rows)


def write_log(path: Path, rows: list[dict]) -> dict[str, Any]:
    """Deterministic gzip (mtime 0, empty name, level 9) of canonical JSON lines."""
    raw = canonical_lines(rows)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as handle:
        handle.write(raw)
    data = buffer.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"rows": len(rows), "canonicalSha256": sha_bytes(raw), "gzipSha256": sha_bytes(data)}


def read_log(path: Path, entry: dict[str, Any]) -> list[dict]:
    """Decode a log and require its gzip digest, canonical digest, canonical form and row count."""
    data = path.read_bytes()
    require(sha_bytes(data) == entry["gzipSha256"], f"b1_log_gzip_mismatch:{path.name}")
    raw = gzip.decompress(data)
    require(sha_bytes(raw) == entry["canonicalSha256"], f"b1_log_canonical_mismatch:{path.name}")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    require(canonical_lines(rows) == raw, f"b1_log_not_canonical:{path.name}")
    require(len(rows) == entry["rows"], f"b1_log_rowcount_mismatch:{path.name}")
    return rows


def git_identity() -> dict[str, Any]:
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout.strip()
    return {"head": head, "trackedChangesPresent": bool(dirty)}


def code_identity() -> dict[str, Any]:
    import numpy
    import PIL
    import av

    return {"files": {name: sha_file(ROOT / name) for name in CODE_FILES},
            "python": platform.python_version(), "numpy": numpy.__version__, "pillow": PIL.__version__,
            "av": av.__version__}


def sequences(manifest: dict) -> list[str]:
    ids = [row["sequenceId"] for row in manifest["sequences"]]
    require(len(ids) == len(set(ids)) == 200, "b1_manifest_population_not_200")
    return sorted(ids)


# inventory --------------------------------------------------------------------------------------------------------

def inventory() -> dict[str, Any]:
    """Hash-bind every input; any missing, extra or mismatched item raises."""
    manifest_path = H3 / "derived" / "derivation-manifest.json"
    manifest_sha = sha_file(manifest_path)
    require(manifest_sha == EXPECTED["manifest"], "b1_inventory_hash_mismatch:manifest")
    manifest = json.loads(manifest_path.read_bytes())
    seqs = sequences(manifest)
    by_id = {row["sequenceId"]: row for row in manifest["sequences"]}
    live_index_path = X1 / "live" / "index.json"
    live_index = json.loads(live_index_path.read_bytes())
    base_index_path = X1 / "baseline" / "index.json"
    base_index = json.loads(base_index_path.read_bytes())
    require(sorted(live_index["detections"]) == seqs, "b1_inventory_detections_population")
    require(sorted(base_index["results"]) == seqs, "b1_inventory_x1_baseline_population")
    require(base_index["manifestSha256"] == manifest_sha and live_index["manifestSha256"] == manifest_sha,
            "b1_inventory_x1_manifest_binding")
    present_detections = sorted(p.name[: -len(".detections.jsonl")] for p in (X1 / "live" / "detections").iterdir())
    require(present_detections == seqs, "b1_inventory_detections_extra_or_missing")
    present_videos = sorted(p.name for p in (H3 / "derived" / "sequences").iterdir() if p.is_dir())
    require(present_videos == seqs, "b1_inventory_videos_extra_or_missing")
    rows = {}
    for sequence in seqs:
        video = H3 / "derived" / "sequences" / sequence / "video.mp4"
        gt = H3 / "derived" / "sequences" / sequence / "ground-truth.json"
        detections = X1 / "live" / "detections" / f"{sequence}.detections.jsonl"
        v, g, d = sha_file(video), sha_file(gt), sha_file(detections)
        require(v == by_id[sequence]["derivedVideoSha256"], f"b1_inventory_video_mismatch:{sequence}")
        require(video.stat().st_size == by_id[sequence]["derivedVideoSizeBytes"], f"b1_inventory_video_size:{sequence}")
        require(g == by_id[sequence]["groundTruthSha256"], f"b1_inventory_gt_mismatch:{sequence}")
        require(d == live_index["detections"][sequence], f"b1_inventory_detections_mismatch:{sequence}")
        x1_result = X1 / "baseline" / "results" / f"{sequence}.json"
        require(sha_file(x1_result) == base_index["results"][sequence], f"b1_inventory_x1_result_mismatch:{sequence}")
        rows[sequence] = {"videoSha256": v, "groundTruthSha256": g, "detectionsSha256": d,
                          "x1BaselineResultSha256": base_index["results"][sequence]}
    hr, ai = PLATES / "results-human-reviewed", PLATES / "results"
    instruments = {}
    for spec_path in INSTRUMENT_SPECS:
        spec = json.loads(spec_path.read_bytes())
        files = {}
        for model_file in spec["modelFiles"]:
            path = MODEL_ROOT / spec["instrumentId"] / model_file["path"]
            require(sha_file(path) == model_file["sha256"], f"b1_inventory_instrument_file:{model_file['path']}")
            files[model_file["path"]] = model_file["sha256"]
        instruments[spec["instrumentId"]] = {"specSha256": sha_file(spec_path), "modelFiles": files,
                                             "packages": spec["packages"]}
    record, record_sha = b1.frozen_record()
    del record
    return {
        "kind": "b1-inventory", "rule": b1.RULE_ID, "frozenRecordSha256": record_sha,
        "manifest": {"path": str(manifest_path), "sha256": manifest_sha, "sequences": len(seqs)},
        "profileSha256": _expect("profile", sha_file(PROFILE)),
        "x1": {"liveIndex": _expect("x1LiveIndex", sha_file(live_index_path)),
               "baselineIndex": _expect("x1BaselineIndex", sha_file(base_index_path)),
               "verify": _expect("x1Verify", sha_file(X1 / "verify.json")),
               "liveProvenanceModel": live_index.get("provenance", {}).get("model") if isinstance(
                   live_index.get("provenance"), dict) else None},
        "descriptorSha256": _expect("descriptor", sha_file(H3 / "desc" / "frozen.json")),
        "o5": {"truth": _expect("o5Truth", sha_file(hr / "truth-val.json")), "ea": _expect("o5Ea", sha_file(hr / "ea.json")),
               "eb": _expect("o5Eb", sha_file(hr / "eb.json")), "verdict": _expect("o5Verdict", sha_file(hr / "verdict.json"))},
        "aiLabelHistorical": {"truth": _expect("aiTruth", sha_file(PLATES / "truth-val.json")),
                              "ea": _expect("aiEa", sha_file(ai / "ea.json")), "eb": _expect("aiEb", sha_file(ai / "eb.json"))},
        "instruments": instruments, "sequences": rows,
        "code": {"git": git_identity(), **code_identity()},
    }


# replay -----------------------------------------------------------------------------------------------------------

def job_id(arm: str, sequence: str) -> UUID:
    return UUID(sha_bytes(f"stage4-b1/{arm}/{sequence}".encode())[:32])


def _artefact(descriptor) -> dict:
    return {"storageKey": descriptor.storage_key, "sha256": descriptor.sha256, "sizeBytes": descriptor.size_bytes}


def run_sequence(profile, arm: str, sequence: str, video: Path, out: Path, detector, scorer,
                 expected_video_sha: str) -> dict:
    from mavi_vision.common.lease import LeaseGuard
    from mavi_vision.evidence.encoder import JpegLadderEncoder
    from mavi_vision.pipeline.process_video import VideoProcessor
    from mavi_vision.storage.artifact_store import StagingArtifactStore
    from mavi_vision.tracking.bytetrack import ByteTrackTracker

    job = job_id(arm, sequence)
    staging = out / "staging" / sequence
    staging.mkdir(parents=True, exist_ok=False)
    data = video.read_bytes()
    require(sha_bytes(data) == expected_video_sha, f"b1_video_changed:{sequence}")
    processor = VideoProcessor(detector, ByteTrackTracker(profile.tracker), StagingArtifactStore(staging, job, 1),
                               evidence_policy=profile.evidence, evidence_scorer=scorer,
                               evidence_encoder=JpegLadderEncoder(profile.evidence.encoder))
    result = processor.process(job_id=job, attempt_count=1, source_path=video, expected_source_size_bytes=len(data),
                               expected_source_sha256=expected_video_sha,
                               lease_guard=LeaseGuard(datetime.now(timezone.utc) + timedelta(days=1)))
    tracks = [{"trackId": t.track_id, "objectClass": t.object_class.value, "startOffsetMs": t.start_offset_ms,
               "endOffsetMs": t.end_offset_ms, "trajectory": _artefact(t.trajectory_artifact),
               "observations": [{"role": o.role.value, "rank": o.rank, "offsetMs": o.offset_ms,
                                 "sourceFrameNumber": o.source_frame_number, "confidence": o.confidence,
                                 "boundingBox": dataclasses.asdict(o.bounding_box), "qualityMicro": o.quality_micro,
                                 "selectionMicro": o.selection_micro, "crop": _artefact(o.crop)}
                                for o in t.observations]} for t in result.tracks]
    return {"sequenceId": sequence, "processingRunId": str(job), "videoSha256": expected_video_sha,
            "framesProcessed": result.frames_processed, "tracks": tracks}


def _mark_admitted(row: dict, admitted: set[tuple[str, int]]) -> None:
    """Flag, in the result, every NearView observation that a b1-only candidate supplied (experiment-admitted)."""
    for track in row["tracks"]:
        for o in track["observations"]:
            o["b1Admitted"] = o["role"] == "near-view" and (str(track["trackId"]), o["sourceFrameNumber"]) in admitted


def replay(arm: str, inventory_path: Path, out: Path) -> dict[str, Any]:
    from mavi_vision.evidence.quality import scorer_for_policy
    from mavi_vision.evidence.selector import EvidenceSelector
    from mavi_vision.pipeline import process_video
    from mavi_vision.runtime.profile import load_pipeline_profile
    from measure_evidence_real_clips import RecordingScorer, ReplayDetector, read_detections

    require(arm in ARMS, "b1_arm_invalid")
    inv_bytes = inventory_path.read_bytes()
    inv = json.loads(inv_bytes)
    require(inv["kind"] == "b1-inventory", "b1_inventory_invalid")
    _, record_sha = b1.frozen_record()
    require(record_sha == inv["frozenRecordSha256"], "b1_frozen_record_changed")
    require(sha_file(PROFILE) == inv["profileSha256"], "b1_profile_changed")
    git = git_identity()
    require(not git["trackedChangesPresent"], "b1_code_tree_dirty")
    code = code_identity()
    require(code["files"] == inv["code"]["files"], "b1_code_changed_since_inventory")
    out.mkdir(parents=True, exist_ok=False)
    profile = load_pipeline_profile(PROFILE)
    seqs = sorted(inv["sequences"])
    require(len(seqs) == 200, "b1_inventory_population")
    index: dict[str, Any] = {"kind": "b1-arm", "arm": arm, "rule": b1.RULE_ID if arm != "A" else None,
                             "mode": {"A": "production", "B": "active", "preflight": "shadow"}[arm],
                             "inventorySha256": sha_bytes(inv_bytes), "frozenRecordSha256": record_sha,
                             "profileSha256": inv["profileSha256"], "code": {"git": git, **code},
                             "results": {}, "candidateLogs": {}, "b1Logs": {}, "staging": {}, "inputs": {}}
    timings = {}
    for n, sequence in enumerate(seqs, start=1):
        entry = inv["sequences"][sequence]
        detections_path = X1 / "live" / "detections" / f"{sequence}.detections.jsonl"
        require(sha_file(detections_path) == entry["detectionsSha256"], f"b1_detections_changed:{sequence}")
        candidate_rows: list[dict] = []
        b1_rows: list[dict] = []
        scorer = b1.B1RecordingScorer(RecordingScorer(scorer_for_policy(profile.evidence), profile.evidence,
                                                      sequence, candidate_rows), profile.evidence, candidate_rows)
        detector = ReplayDetector(read_detections(detections_path))
        video = H3 / "derived" / "sequences" / sequence / "video.mp4"
        started, cpu = time.perf_counter(), time.process_time()
        if arm == "A":
            require(process_video.EvidenceSelector is EvidenceSelector, "b1_arm_a_not_production")
            row = run_sequence(profile, arm, sequence, video, out, detector, scorer, entry["videoSha256"])
        else:
            mode = "active" if arm == "B" else "shadow"

            def factory(**kwargs):
                return b1.B1NearViewSelector(**kwargs, sink=b1_rows, mode=mode)

            with b1.b1_composition(factory):
                row = run_sequence(profile, arm, sequence, video, out, detector, scorer, entry["videoSha256"])
        timings[sequence] = {"wallSeconds": round(time.perf_counter() - started, 3),
                             "cpuSeconds": round(time.process_time() - cpu, 3)}
        _mark_admitted(row, {(r["trackId"], r["frame"]) for r in b1_rows if r.get("held")})
        result_path = out / "results" / f"{sequence}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_bytes(json.dumps(row, sort_keys=True).encode("utf-8"))
        index["results"][sequence] = sha_file(result_path)
        vehicle_rows = [r for r in candidate_rows if r["object_class"] == "vehicle"]
        index["candidateLogs"][sequence] = write_log(out / "candidates" / f"{sequence}.jsonl.gz", vehicle_rows)
        index["candidateLogs"][sequence]["personCandidates"] = len(candidate_rows) - len(vehicle_rows)
        index["b1Logs"][sequence] = write_log(out / "b1" / f"{sequence}.jsonl.gz", b1_rows)
        index["staging"][sequence] = _staging_digest(out / "staging" / sequence)
        index["inputs"][sequence] = {"videoSha256": entry["videoSha256"], "detectionsSha256": entry["detectionsSha256"]}
        print(f"{arm} {n} {sequence} tracks={len(row['tracks'])} b1={len(b1_rows)} "
              f"held={sum(1 for r in b1_rows if r.get('held'))}", flush=True)
    (out / "index.json").write_bytes(json.dumps(index, indent=1, sort_keys=True).encode("utf-8"))
    (out / "timings.json").write_bytes(json.dumps(timings, indent=1, sort_keys=True).encode("utf-8"))
    return index


def _staging_digest(staging: Path) -> str:
    """One digest over the sorted (relative path, SHA-256, size) of every staged file."""
    items = sorted((p.relative_to(staging).as_posix(), sha_file(p), p.stat().st_size)
                   for p in staging.rglob("*") if p.is_file())
    return sha_bytes(json.dumps(items, separators=(",", ":")).encode("utf-8"))


# verify / equal ---------------------------------------------------------------------------------------------------

def verify(arm_dir: Path, inventory_path: Path | None = None) -> dict[str, Any]:
    """Fail closed on a missing, extra or changed result, log, staged artefact or input binding."""
    index = json.loads((arm_dir / "index.json").read_bytes())
    require(index.get("kind") == "b1-arm" and index.get("arm") in ARMS, "b1_index_invalid")
    seqs = sorted(index["results"])
    for key in ("candidateLogs", "b1Logs", "staging", "inputs"):
        require(sorted(index[key]) == seqs, f"b1_index_population_differs:{key}")
    if inventory_path is not None:
        inv_bytes = inventory_path.read_bytes()
        require(sha_bytes(inv_bytes) == index["inventorySha256"], "b1_inventory_binding")
        inv = json.loads(inv_bytes)
        require(seqs == sorted(inv["sequences"]) and len(seqs) == 200, "b1_population_not_inventory")
        for s in seqs:
            require(index["inputs"][s] == {"videoSha256": inv["sequences"][s]["videoSha256"],
                                           "detectionsSha256": inv["sequences"][s]["detectionsSha256"]},
                    f"b1_input_binding:{s}")
    for directory, suffix in (("results", ".json"), ("candidates", ".jsonl.gz"), ("b1", ".jsonl.gz")):
        present = sorted(p.name[: -len(suffix)] for p in (arm_dir / directory).iterdir())
        require(present == seqs, f"b1_files_extra_or_missing:{directory}")
    require(sorted(p.name for p in (arm_dir / "staging").iterdir()) == seqs, "b1_files_extra_or_missing:staging")
    rows = {"candidates": 0, "b1": 0, "artefacts": 0}
    for s in seqs:
        raw = (arm_dir / "results" / f"{s}.json").read_bytes()
        require(sha_bytes(raw) == index["results"][s], f"b1_result_mismatch:{s}")
        result = json.loads(raw)
        require(result["sequenceId"] == s and result["videoSha256"] == index["inputs"][s]["videoSha256"],
                f"b1_result_identity:{s}")
        rows["candidates"] += len(read_log(arm_dir / "candidates" / f"{s}.jsonl.gz", index["candidateLogs"][s]))
        rows["b1"] += len(read_log(arm_dir / "b1" / f"{s}.jsonl.gz", index["b1Logs"][s]))
        staging = arm_dir / "staging" / s
        require(_staging_digest(staging) == index["staging"][s], f"b1_staging_mismatch:{s}")
        referenced = {}
        for track in result["tracks"]:
            for artefact in [track["trajectory"], *(o["crop"] for o in track["observations"])]:
                referenced[artefact["storageKey"]] = artefact
        files = {p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()}
        require(files == set(referenced), f"b1_staging_files_differ_from_result:{s}")
        for key, artefact in referenced.items():
            data = (staging / key).read_bytes()
            require(len(data) == artefact["sizeBytes"] and sha_bytes(data) == artefact["sha256"],
                    f"b1_artefact_mismatch:{s}:{key}")
        rows["artefacts"] += len(referenced)
    return {"arm": index["arm"], "sequences": len(seqs), "verified": True, **rows}


def canonical_view(arm_dir: Path) -> dict[str, Any]:
    """The run's content, independent of gzip bytes: per-sequence result digest, decoded-log digests, staging."""
    index = json.loads((arm_dir / "index.json").read_bytes())
    return {"arm": index["arm"], "inventory": index["inventorySha256"], "results": index["results"],
            "candidateLogs": {s: e["canonicalSha256"] for s, e in index["candidateLogs"].items()},
            "b1Logs": {s: e["canonicalSha256"] for s, e in index["b1Logs"].items()}, "staging": index["staging"]}


def equal(first: Path, second: Path) -> dict[str, Any]:
    verify(first)
    verify(second)
    a, b = canonical_view(first), canonical_view(second)
    differing = {key: sorted(s for s in set(a[key]) | set(b[key]) if a[key].get(s) != b[key].get(s))
                 for key in ("results", "candidateLogs", "b1Logs", "staging")}
    same = a["arm"] == b["arm"] and a["inventory"] == b["inventory"] and not any(differing.values())
    gzip_same = all(json.loads((first / "index.json").read_bytes())[k] == json.loads(
        (second / "index.json").read_bytes())[k] for k in ("candidateLogs", "b1Logs"))
    return {"canonicalEqual": same, "gzipBytesEqual": gzip_same, "differing": differing,
            "indexSha256": [sha_file(first / "index.json"), sha_file(second / "index.json")]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    i = sub.add_parser("inventory")
    i.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("replay")
    r.add_argument("--arm", choices=ARMS, required=True)
    r.add_argument("--inventory", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--inventory", type=Path)
    v.add_argument("arm_dir", type=Path)
    e = sub.add_parser("equal")
    e.add_argument("first", type=Path)
    e.add_argument("second", type=Path)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        require(not args.out.exists(), "b1_output_exists")
        data = json.dumps(inventory(), indent=1, sort_keys=True).encode("utf-8")
        args.out.write_bytes(data)
        print(f"{args.out} sha256={sha_bytes(data)}")
    elif args.command == "replay":
        replay(args.arm, args.inventory, args.out)
        print(f"{args.out / 'index.json'} sha256={sha_file(args.out / 'index.json')}")
    elif args.command == "verify":
        print(json.dumps(verify(args.arm_dir, args.inventory)))
    else:
        result = equal(args.first, args.second)
        print(json.dumps(result, indent=1))
        return 0 if result["canonicalEqual"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
