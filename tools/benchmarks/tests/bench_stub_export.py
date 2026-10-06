"""Stands in for ``Mavi.MeasurementExport --run --pipeline-profile --out`` in benchmark ``execute`` tests: writes a
T1 export, with one sealed trajectory, for a run the T9 stub API completed. ``--tamper`` injects exit failures."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
import track_fixtures as f  # noqa: E402

from tools.benchmarks.core.identity import canonical_json, sha256_hex  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--tamper", default="")
    p.add_argument("--attest-binding", default=None)  # the worker's componentBindingSha256 (Development producers)
    p.add_argument("--attest-pack", default=None)  # and its detector modelPackId
    p.add_argument("--run", required=True)
    p.add_argument("--pipeline-profile", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))["runs"].get(args.run)
    if state is None or args.out.exists():
        return 3
    tamper = set(filter(None, args.tamper.split(",")))
    upload = Path(state["upload"]).read_bytes()
    source_sha = hashlib.sha256(upload + b"tampered" if "source" in tamper else upload).hexdigest()
    number = int(args.run[-4:], 16)
    # A trajectory sealed somewhere other than the evidence root is a missing trajectory there.
    evidence = args.evidence.parent / "elsewhere" if "trajectory" in tamper else args.evidence
    path = f.write_export(args.out, evidence, [{"n": number, "points": [(0, 0.5, 0.5), (200, 0.5, 0.5)],
                                                "observations": [(0, (0.4, 0.4, 0.2, 0.2))], "subclass": "car"}],
                          profile_sha256=sha256_hex(args.pipeline_profile.read_bytes()), source_sha256=source_sha)
    document = json.loads(path.read_bytes())
    run, video = document["processingRun"], document["video"]
    run.update(processingRunId=args.run, videoAssetId=state["videoAssetId"])
    run["attestation"].update(processingRunId=args.run, videoAssetId=state["videoAssetId"])
    if args.attest_binding is not None:
        run["attestation"]["componentBindingSha256"] = args.attest_binding
    if args.attest_pack is not None:
        run["attestation"]["modelPackId"] = args.attest_pack
    video.update(videoAssetId=state["videoAssetId"], cameraCode=state["cameraCode"])
    path.write_bytes(canonical_json(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
