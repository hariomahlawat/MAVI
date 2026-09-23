"""The parent plan's three FFmpeg-scripted scene-analytics videos — NOT a MAVI runtime component.

One source of truth, ``tests/fixtures/scene-analytics/scripted-corpus-v1.json``,
drives three things so they cannot drift apart:

* the videos themselves, generated here with ffmpeg (a Development prerequisite);
* the fixture detections ``fixture_worker_harness.py`` reports for each video when
  ``MAVI_FIXTURE_SCENARIO`` names it; and
* the expected facts, asserted against the real .NET engine by
  ``tests/Mavi.Application.Tests/SceneAnalytics/ScriptedCorpusTests.cs``.

The box is drawn at integer pixel positions, and ``verify`` decodes a generated
video and checks every frame's box against the same position model, so "the
detector reports the box that is on screen" is checked rather than assumed.

Standard library only. Usage::

    python tools/vision/dev/scripted_corpus.py generate <out-dir> [scenario ...]
    python tools/vision/dev/scripted_corpus.py verify <video> <scenario>
    python tools/vision/dev/scripted_corpus.py apply-scene <api-base-url> <camera-id> <scenario>
    python tools/vision/dev/scripted_corpus.py check <api-base-url | track-detail.json> <track-id> <scenario>

``apply-scene`` saves the scenario's exact geometry as the camera's next scene revision
through the ordinary scene API, so no coordinate is placed by hand. ``check`` reads the
analysed Track's detail from the API (or a saved response) and asserts the expected facts;
it exits non-zero on any mismatch and never on a guess.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import urllib.request
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "scene-analytics" / "scripted-corpus-v1.json"

# Luma threshold separating the white box from the dark background, decoded as gray.
_BOX_LUMA = 200


def load_spec(path: Path = SPEC_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scenario(spec: dict, scenario_id: str) -> dict:
    for candidate in spec["scenarios"]:
        if candidate["id"] == scenario_id:
            return candidate
    raise KeyError(f"unknown scripted scenario: {scenario_id}")


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def centre_at(scene: dict, frame: int) -> tuple[int, int] | None:
    """The box centre in whole pixels at ``frame``, or None outside the keyframes."""
    keys = scene["centreKeyframes"]
    if frame < keys[0][0] or frame > keys[-1][0]:
        return None
    for (f0, x0, y0), (f1, x1, y1) in zip(keys, keys[1:]):
        if f0 <= frame <= f1:
            share = 0.0 if f1 == f0 else (frame - f0) / (f1 - f0)
            return _round_half_up(x0 + (x1 - x0) * share), _round_half_up(y0 + (y1 - y0) * share)
    raise AssertionError("keyframes do not cover their own span")


def detection_boxes(spec: dict, scene: dict) -> dict[int, tuple[float, float, float, float]]:
    """Normalised (left, top, width, height) per detection frame — what the fixture detector reports."""
    video = spec["video"]
    width, height = video["width"], video["height"]
    box_w, box_h = video["boxWidth"], video["boxHeight"]
    boxes = {}
    for frame in range(video["firstDetectionFrame"], video["lastDetectionFrame"] + 1):
        centre = centre_at(scene, frame)
        if centre is None:
            raise AssertionError(f"frame {frame} is a detection frame outside the scenario's keyframes")
        cx, cy = centre
        boxes[frame] = ((cx - box_w / 2) / width, (cy - box_h / 2) / height, box_w / width, box_h / height)
    return boxes


def _position_expression(scene: dict, axis: int, half_extent: int, fps: int) -> str:
    """An ffmpeg overlay expression for the box's top-left on one axis, frame by frame."""
    frame = f"floor(t*{fps}+0.5)"
    keys = scene["centreKeyframes"]
    expression = f"{keys[-1][axis]}"
    for (f0, *p0), (f1, *p1) in reversed(list(zip(keys, keys[1:]))):
        start, end = p0[axis - 1], p1[axis - 1]
        segment = f"floor({start}+({end}-{start})*({frame}-{f0})/{f1 - f0}+0.5)" if f1 != f0 else f"{start}"
        expression = f"if(lt({frame},{f1}),{segment},{expression})"
    return f"{expression}-{half_extent}"


def ffmpeg_command(spec: dict, scene: dict, output: Path) -> list[str]:
    video = spec["video"]
    fps = video["fps"]
    first = video["firstDetectionFrame"] / fps
    last = video["lastDetectionFrame"] / fps
    x = _position_expression(scene, 1, video["boxWidth"] // 2, fps)
    y = _position_expression(scene, 2, video["boxHeight"] // 2, fps)
    # Composited in 4:4:4: in 4:2:0 the overlay filter snaps positions to the chroma
    # grid, which moves every odd-pixel box by one pixel off the position model.
    overlay = (
        "[0]format=yuv444p[matte];[1]format=yuv444p[box];"
        f"[matte][box]overlay=x='{x}':y='{y}':eval=frame:shortest=1:format=yuv444"
        f":enable='between(t,{first - 0.5 / fps},{last + 0.5 / fps})',format=yuv420p"
    )
    return [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x202020:s={video['width']}x{video['height']}:r={fps}:d={video['durationSeconds']}",
        "-f", "lavfi", "-i", f"color=c=white:s={video['boxWidth']}x{video['boxHeight']}:r={fps}",
        "-filter_complex", overlay,
        # Constrained High profile, not CRF 0: lossless x264 is High 4:4:4 Predictive,
        # which browser decoders commonly refuse, so Evidence Review could not play it.
        # CRF 1 on a flat box leaves every decoded centre exact (``verify`` still checks
        # each frame), and ``-bf 0`` keeps decode order equal to display order. The
        # worker and the import path already accept H.264 MP4.
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "1", "-profile:v", "high", "-bf", "0",
        "-pix_fmt", "yuv420p", "-g", str(fps),
        str(output),
    ]


def generate(spec: dict, out_dir: Path, scenario_ids: list[str]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for scenario_id in scenario_ids:
        scene = scenario(spec, scenario_id)
        output = out_dir / scene["file"]
        subprocess.run(ffmpeg_command(spec, scene, output), check=True)
        written.append(output)
    return written


def observed_centres(spec: dict, video_path: Path) -> list[tuple[float, float] | None]:
    """The drawn box's centre per decoded frame, from the luma plane."""
    video = spec["video"]
    width, height = video["width"], video["height"]
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    ).stdout
    frame_bytes = width * height
    centres: list[tuple[float, float] | None] = []
    for index in range(len(raw) // frame_bytes):
        plane = raw[index * frame_bytes:(index + 1) * frame_bytes]
        columns = [i % width for i, value in enumerate(plane) if value > _BOX_LUMA]
        if not columns:
            centres.append(None)
            continue
        rows = [i // width for i, value in enumerate(plane) if value > _BOX_LUMA]
        centres.append(((min(columns) + max(columns) + 1) / 2, (min(rows) + max(rows) + 1) / 2))
    return centres


def verify(spec: dict, video_path: Path, scenario_id: str) -> list[str]:
    """Every frame's drawn box against the position model. Returns the problems found."""
    scene = scenario(spec, scenario_id)
    video = spec["video"]
    expected_frames = video["fps"] * video["durationSeconds"]
    centres = observed_centres(spec, video_path)
    problems = []
    if len(centres) != expected_frames:
        problems.append(f"decoded {len(centres)} frames, expected {expected_frames}")
    first, last = video["firstDetectionFrame"], video["lastDetectionFrame"]
    for frame, observed in enumerate(centres):
        if first <= frame <= last:
            expected = centre_at(scene, frame)
            if observed != (float(expected[0]), float(expected[1])):
                problems.append(f"frame {frame}: box centre {observed}, model {expected}")
        elif observed is not None:
            problems.append(f"frame {frame}: a box is drawn outside the detection frames")
    return problems


def _request(url: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - local Development API only
        return json.loads(response.read().decode("utf-8"))


def scene_request(scene: dict, expected_revision_number: int) -> dict:
    """The scenario's geometry as the scene API's whole-scene save request."""
    point = lambda xy: {"x": xy[0], "y": xy[1]}  # noqa: E731
    return {
        "expectedRevisionNumber": expected_revision_number,
        "note": f"scripted corpus v1: {scene['id']}",
        "referenceFrameVideoAssetId": None,
        "referenceFrameOffsetMs": None,
        "zones": [
            {"name": zone["name"], "kind": "General", "enabled": True,
             "vertices": [point(vertex) for vertex in zone["vertices"]],
             "loiteringThresholdSeconds": zone["loiteringThresholdSeconds"]}
            for zone in scene["scene"]["zones"]
        ],
        "tripLines": [
            {"name": line["name"], "enabled": True, "a": point(line["a"]), "b": point(line["b"]),
             "directed": True, "aToBLabel": line["aToBLabel"], "bToALabel": line["bToALabel"]}
            for line in scene["scene"]["tripLines"]
        ],
    }


def apply_scene(api: str, camera_id: str, scene: dict) -> dict:
    current = _request(f"{api.rstrip('/')}/api/cameras/{camera_id}/scene")
    active = current.get("activeRevision")
    return _request(
        f"{api.rstrip('/')}/api/cameras/{camera_id}/scene", "PUT",
        scene_request(scene, active["revisionNumber"] if active else 0))


def _within(value: int, bracket: list[int]) -> bool:
    return bracket[0] <= value <= bracket[1]


def check_detail(spec: dict, scene: dict, detail: dict, revision: dict) -> list[str]:
    """The analysed Track's facts against the scenario's expected facts. Returns the problems found."""
    expected = scene["expected"]
    analytics = detail.get("analytics") or {}
    zones = {zone["zoneId"].lower(): zone["name"] for zone in revision.get("zones", [])}
    lines = {line["lineId"].lower(): line["name"] for line in revision.get("tripLines", [])}
    problems = []

    def need(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    need(analytics.get("status") == "Analysed", f"status is {analytics.get('status')}, expected Analysed")
    need((analytics.get("sceneRevisionId") or "").lower() == revision["revisionId"].lower(),
         "the facts are not pinned to the scenario's scene revision")
    need(analytics.get("sampleCount") == expected["sampleCount"],
         f"sampleCount {analytics.get('sampleCount')}, expected {expected['sampleCount']}")

    visits = analytics.get("zoneVisits", [])
    need(len(visits) == len(expected["zoneVisits"]), f"{len(visits)} zone visits, expected {len(expected['zoneVisits'])}")
    for want, got in zip(expected["zoneVisits"], visits):
        need(zones.get(got["zoneId"].lower()) == want["zone"], f"visit is in {zones.get(got['zoneId'].lower())}, expected {want['zone']}")
        for key in ("entryOffsetMs", "exitOffsetMs", "dwellMs"):
            need(_within(got[key], want[key]), f"visit {key} {got[key]} outside {want[key]}")
        for key in ("beganInside", "endedInside"):
            need(got[key] == want[key], f"visit {key} is {got[key]}, expected {want[key]}")
    for zone_name, loitering in expected.get("loitering", {}).items():
        summaries = [entry for entry in analytics.get("zoneSummaries", []) if zones.get(entry["zoneId"].lower()) == zone_name]
        need(len(summaries) == 1 and summaries[0]["loitering"] == loitering, f"{zone_name} loitering is not {loitering}")

    crossings = analytics.get("lineCrossings", [])
    need(len(crossings) == len(expected["lineCrossings"]), f"{len(crossings)} crossings, expected {len(expected['lineCrossings'])}")
    for want, got in zip(expected["lineCrossings"], crossings):
        need(lines.get(got["lineId"].lower()) == want["line"], f"crossing is of {lines.get(got['lineId'].lower())}, expected {want['line']}")
        # The wire vocabulary is camel-cased (aToB); the persisted one is not (AToB).
        need(got["direction"].lower() == want["direction"].lower(), f"direction {got['direction']}, expected {want['direction']}")
        need(_within(got["offsetMs"], want["offsetMs"]), f"crossing offset {got['offsetMs']} outside {want['offsetMs']}")

    motion = analytics.get("motion") or {}
    need(motion.get("heading") == expected["heading"], f"heading {motion.get('heading')}, expected {expected['heading']}")
    intervals = motion.get("stationaryIntervals", [])
    need(len(intervals) == len(expected["stationaryIntervals"]),
         f"{len(intervals)} stationary intervals, expected {len(expected['stationaryIntervals'])}")
    for want, got in zip(expected["stationaryIntervals"], intervals):
        need(_within(got["startOffsetMs"], want["startOffsetMs"]), f"stationary start {got['startOffsetMs']} outside {want['startOffsetMs']}")
        need(_within(got["endOffsetMs"], want["endOffsetMs"]), f"stationary end {got['endOffsetMs']} outside {want['endOffsetMs']}")
    return problems


def main(argv: list[str]) -> int:
    spec = load_spec()
    if len(argv) >= 2 and argv[0] == "generate":
        ids = argv[2:] or [entry["id"] for entry in spec["scenarios"]]
        for path in generate(spec, Path(argv[1]), ids):
            print(path)
        return 0
    if len(argv) == 3 and argv[0] == "verify":
        problems = verify(spec, Path(argv[1]), argv[2])
        for problem in problems:
            print(problem)
        print("ok" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1
    if len(argv) == 4 and argv[0] == "apply-scene":
        revision = apply_scene(argv[1], argv[2], scenario(spec, argv[3]))
        print(f"scene revision {revision['revisionNumber']} saved ({revision['revisionId']})")
        return 0
    if len(argv) == 4 and argv[0] == "check":
        scene = scenario(spec, argv[3])
        source = argv[1]
        if source.startswith("http"):
            detail = _request(f"{source.rstrip('/')}/api/tracks/{argv[2]}")
            number = detail["analytics"]["sceneRevisionNumber"]
            camera = detail["camera"]["id"]
            revision = _request(f"{source.rstrip('/')}/api/cameras/{camera}/scene/revisions/{number}")
        else:
            saved = json.loads(Path(source).read_text(encoding="utf-8"))
            detail, revision = saved["trackDetail"], saved["sceneRevision"]
        problems = check_detail(spec, scene, detail, revision)
        for problem in problems:
            print(problem)
        print("ok" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
