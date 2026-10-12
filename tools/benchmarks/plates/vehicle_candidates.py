"""Phase-1 detector vehicle candidates for still images (protocol §4.1 step 1) → ``benchmark-plate-vehicle-candidates-v1``.

Still-image plate releases (UC3M-LP, the DataCluster Indian sample) have no vehicle box. E-A needs the box MAVI itself
would crop, so this producer runs the **production** ``RTMDetDetector`` on every truth image, started through the
worker's own composition (``WorkerSettings`` → ``RuntimeSupervisor``, READY or stop) exactly as the Stage-3 detector
diagnostics did. It runs inside the qualified vision Runtime Pack's environment, configured by the worker's ``MAVI_*``
settings, and imports nothing from the benchmark harness (that environment carries no harness dependency).

Rule (frozen with the protocol): keep detections of the vehicle source classes (``car``, ``truck``, ``bus``,
``motorcycle``) whose confidence is at or above the pipeline profile's evidence ``confidenceFloor`` — the floor a
detection must meet to become qualified evidence (ADR-013 §4), so a weaker box is not one MAVI would crop as
qualified evidence. Boxes are converted to pixels of the image. Every image is verified against the truth's SHA-256
before decoding. The output binds the truth hash and the runtime's provenance.

    python tools/benchmarks/plates/vehicle_candidates.py <truth.json> <source-root> <out.json>
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path

SCHEMA = "benchmark-plate-vehicle-candidates-v1"
VEHICLE_CLASSES = ("bus", "car", "motorcycle", "truck")


def _image(source_root: Path, item: dict) -> "object":
    import numpy as np
    from PIL import Image

    data = (source_root / item["imagePath"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != item["imageSha256"]:
        raise SystemExit(f"image hash mismatch: {item['imagePath']}")
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def detect_all(runtime, profile, truth: dict, source_root: Path) -> dict:
    from mavi_vision.detection.rtmdet import RTMDetDetector
    from mavi_vision.video.reader import DecodedFrame

    detector = RTMDetDetector(runtime, profile)
    floor = profile.evidence.confidence_floor
    items = {}
    for item in truth["items"]:
        pixels = _image(source_root, item)
        height, width = pixels.shape[:2]
        boxes = []
        for detection in detector.detect(DecodedFrame(source_frame_number=0, offset_ms=0, image=pixels)):
            if detection.source_class not in VEHICLE_CLASSES or detection.confidence < floor:
                continue
            box = detection.bounding_box
            boxes.append({"x": box.x * width, "y": box.y * height, "width": box.width * width,
                          "height": box.height * height, "sourceClass": detection.source_class,
                          "confidence": detection.confidence})
        items[item["itemId"]] = sorted(boxes, key=lambda b: (b["y"], b["x"], b["width"], b["height"]))
    return {"confidenceFloor": floor, "items": items}


async def main(truth_path: Path, source_root: Path, out: Path) -> None:
    from mavi_vision.common.settings import WorkerSettings
    from mavi_vision.runtime.activity import InferenceActivity
    from mavi_vision.runtime.execution_lane import VisionExecutionLane
    from mavi_vision.runtime.gpu_identity import capture_gpu_identity
    from mavi_vision.runtime.supervisor import RuntimeState, RuntimeSupervisor
    from mavi_vision.worker.composition import role_composition_from_settings

    if out.exists():
        raise SystemExit(f"output exists: {out}")
    raw = truth_path.read_bytes()
    truth, truth_sha = json.loads(raw), hashlib.sha256(raw).hexdigest()
    settings = WorkerSettings()
    lane = VisionExecutionLane()
    supervisor = RuntimeSupervisor(
        lane=lane, activity=InferenceActivity(), composition=role_composition_from_settings(settings),
        deployment_profile_policy_path=settings.deployment_profile_policy_path,
        deployment_profile=settings.deployment_profile, device_policy=settings.device_policy,
        device_index=settings.device_index, production_mode=settings.production_mode,
        inference_watchdog_seconds=settings.inference_watchdog_seconds,
        device_resolution_reason=settings.device_resolution_reason,
        watchdog_grace_seconds=settings.watchdog_grace_seconds, build_id=settings.build_id,
        commit_sha=settings.commit_sha, gpu_identity_provider=capture_gpu_identity,
    )
    try:
        await supervisor.start()
        if supervisor.state is not RuntimeState.READY:
            raise SystemExit(f"qualified runtime not READY: {supervisor.unavailable_reason}")
        result = await lane.run(detect_all, supervisor.runtime, supervisor.profile, truth, source_root)
        provenance = json.loads(json.dumps(supervisor.provenance, default=lambda o: getattr(o, "__dict__", str(o))))
    finally:
        await supervisor.close()
    document = {"schemaVersion": SCHEMA, "truthSha256": truth_sha,
                "producer": {"provenance": provenance, "rule": {"classes": list(VEHICLE_CLASSES),
                                                                "confidenceFloor": result["confidenceFloor"]}},
                "items": result["items"]}
    data = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    out.write_bytes(data)
    print(hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
