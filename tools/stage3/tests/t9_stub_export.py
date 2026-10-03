"""Stands in for ``Mavi.MeasurementExport --run --pipeline-profile --out`` in T9 tests: writes a T1-shaped
export for a run the stub API completed. ``--tamper`` switches inject the exit-check failures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s32fixtures as s32  # noqa: E402

import artefacts as a  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--tamper", default="")
    p.add_argument("--run", required=True)
    p.add_argument("--pipeline-profile", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    runs = json.loads(args.state.read_text(encoding="utf-8"))["runs"]
    state = runs.get(args.run)
    first = args.run == min(runs)  # identity tampers apply to one member only
    if state is None or args.out.exists():
        return 3
    source = Path(state["upload"]).read_bytes()
    profile_sha = a.sha256_hex(args.pipeline_profile.read_bytes())
    tamper = set(filter(None, args.tamper.split(",")))
    if "fail" in tamper:
        return 1
    run_id = "01a0ffb2-0000-7000-8000-00000000beef" if "run" in tamper and first else args.run
    video_id = "01a0ffb2-0000-7000-8000-00000000cafe" if "video" in tamper and first else state["videoAssetId"]
    if "source" in tamper:
        source = source + b"tampered"
    if "profile" in tamper:
        profile_sha = "f" * 64
    path = s32.write_export(args.out, run_id=run_id, video_id=video_id,
                            camera="S32-OTHER" if "camera" in tamper else state["cameraCode"], source=source,
                            profile_sha=profile_sha, tracks=[s32.TrackSpec(1, track_id=args.run[:-4] + "0001")])
    if "status" in tamper:
        document = json.loads(path.read_bytes())
        document["processingRun"]["status"] = "Failed"
        path.write_bytes(a.canonical_json(document))
    if "producer" in tamper and state["cameraCode"].endswith("C1"):
        document = json.loads(path.read_bytes())
        document["processingRun"]["attestation"]["modelVersion"] = "2"
        path.write_bytes(a.canonical_json(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
